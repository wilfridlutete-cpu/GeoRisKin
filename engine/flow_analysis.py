"""Hydrologie de surface sur MNT : conditionnement, D8, accumulation, réseau, bassins.

Choix documentés :
- conditionnement : Priority-Flood + epsilon (Barnes, Lehman & Mulla 2014),
  exutoires = bord du MNT et voisins de NoData (eau libre, fleuve) ;
  La différence MNT conditionné − MNT brut est renvoyée pour garder la trace
  des modifications (aucune modification n'est silencieuse) ;
- direction d'écoulement D8 (O'Callaghan & Mark, 1984), codage ESRI :
  1=E, 2=SE, 4=S, 8=SO, 16=O, 32=NO, 64=N, 128=NE ; 0 = exutoire / sans aval ;
- accumulation = nombre de cellules amont, cellule comprise ;
- réseau : cellules dont l'aire drainée dépasse un seuil (km²) explicite ;
- bassins : chaque cellule reçoit l'identifiant de son exutoire final
  (bord du domaine, NoData ou cuvette résiduelle) ;
- sous-bassins : chaque cellule reçoit l'identifiant du premier « nœud » du
  réseau rencontré vers l'aval (cellule juste en amont d'une confluence ou d'un
  exutoire), soit la décomposition classique par tronçons de réseau.

Limite : le MNT SRTM est un modèle de surface ; en ville, bâti et canaux
modifient l'écoulement réel, ce que D8 sur MNT ne représente pas.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import heapq

from numba import njit

# décalages (dl, dc) pour chaque code ESRI
D8_CODES = np.array([1, 2, 4, 8, 16, 32, 64, 128], dtype=np.int32)
D8_DROW = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.int32)
D8_DCOL = np.array([1, 1, 0, -1, -1, -1, 0, 1], dtype=np.int32)


@dataclass
class Conditioned:
    dem: np.ndarray          # MNT conditionné (float64 : les incréments de résolution des plats
                             # sont < précision float32 ; ne pas convertir avant le routage)
    fill_depth: np.ndarray   # MNT conditionné − brut (m), ≥ 0 sauf corrections de plat infimes
    stats: dict


def condition_dem(z: np.ndarray, transform=None, crs=None) -> Conditioned:
    """Conditionne le MNT pour l'hydrologie : Priority-Flood + epsilon.

    Exutoires = cellules du bord et cellules voisines d'un NoData (eau libre,
    fleuve, limite du MNT). Toute dépression fermée est comblée jusqu'à son
    point de débordement, avec une pente infinitésimale vers l'exutoire.

    Note : PySheds (fill_depressions) a été testé puis écarté ici, car il ne
    considère pas les NoData intérieurs comme exutoires et comble alors toute la
    plaine qui se jette dans le Pool Malebo (test test_interior_nodata_is_outlet).
    `transform` et `crs` sont acceptés pour compatibilité, non utilisés.
    """
    out = priority_flood_epsilon(z)
    depth = out - z
    mod = depth > 1e-3  # au-delà des incréments epsilon
    stats = {
        "cellules_modifiees_plus_1mm": int(np.nansum(mod)),
        "part_modifiee_pct": float(100 * np.nanmean(mod)),
        "profondeur_max_m": float(np.nanmax(depth)),
        "profondeur_moy_cellules_modifiees_m": float(np.nanmean(np.where(mod, depth, np.nan))),
    }
    return Conditioned(out, depth.astype("float32"), stats)


@njit(cache=True)
def _d8(z, res):
    nr, nc = z.shape
    out = np.zeros((nr, nc), np.int32)
    diag = res * np.sqrt(2.0)
    for r in range(nr):
        for c in range(nc):
            zc = z[r, c]
            if np.isnan(zc):
                continue
            best = 0.0
            code = 0
            for k in range(8):
                rr = r + D8_DROW[k]
                cc = c + D8_DCOL[k]
                if rr < 0 or rr >= nr or cc < 0 or cc >= nc:
                    continue
                zn = z[rr, cc]
                if np.isnan(zn):
                    continue
                dist = res if (D8_DROW[k] == 0 or D8_DCOL[k] == 0) else diag
                s = (zc - zn) / dist
                if s > best:
                    best = s
                    code = D8_CODES[k]
            out[r, c] = code
    return out


def flow_direction(z_cond: np.ndarray, res: float) -> np.ndarray:
    """D8 sur MNT conditionné ; 0 = pas de voisin plus bas (exutoire ou bord)."""
    return _d8(z_cond.astype("float64"), float(res))


@njit(cache=True)
def _downstream_index(fdir):
    nr, nc = fdir.shape
    down = np.full(nr * nc, -1, np.int64)
    for r in range(nr):
        for c in range(nc):
            code = fdir[r, c]
            if code == 0:
                continue
            for k in range(8):
                if D8_CODES[k] == code:
                    rr = r + D8_DROW[k]
                    cc = c + D8_DCOL[k]
                    if 0 <= rr < nr and 0 <= cc < nc:
                        down[r * nc + c] = rr * nc + cc
                    break
    return down


@njit(cache=True)
def _accumulate(down, valid, weights):
    n = down.size
    indeg = np.zeros(n, np.int64)
    for i in range(n):
        if valid[i] and down[i] >= 0:
            indeg[down[i]] += 1
    acc = weights.copy()
    stack = np.empty(n, np.int64)
    top = 0
    for i in range(n):
        if valid[i] and indeg[i] == 0:
            stack[top] = i
            top += 1
    while top > 0:
        top -= 1
        i = stack[top]
        j = down[i]
        if j >= 0:
            acc[j] += acc[i]
            indeg[j] -= 1
            if indeg[j] == 0:
                stack[top] = j
                top += 1
    return acc


def flow_accumulation(fdir: np.ndarray, valid: np.ndarray, weights: np.ndarray | None = None):
    """Accumulation (nombre de cellules amont, cellule comprise, ou somme de poids)."""
    down = _downstream_index(fdir)
    w = np.ones(fdir.size, "float64") if weights is None else weights.ravel().astype("float64")
    w = np.where(valid.ravel(), w, 0.0)
    acc = _accumulate(down, valid.ravel(), w).reshape(fdir.shape)
    acc[~valid] = np.nan
    return acc


@njit(cache=True)
def _label_to_targets(down, valid, is_target):
    """Étiquette chaque cellule par la première cellule cible rencontrée vers l'aval
    (la cellule elle-même si elle est cible) ; -1 si aucune."""
    n = down.size
    lab = np.full(n, -2, np.int64)  # -2 = non résolu
    path = np.empty(n, np.int64)
    for s in range(n):
        if not valid[s] or lab[s] != -2:
            continue
        k = 0
        i = s
        res = -1
        while True:
            if lab[i] != -2:
                res = lab[i]
                break
            path[k] = i
            k += 1
            if is_target[i]:
                res = i
                break
            j = down[i]
            if j < 0 or not valid[j]:
                res = -1
                break
            i = j
        for m in range(k):
            lab[path[m]] = res
    return lab


def basins(fdir: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Bassins versants : identifiant = indice de la cellule exutoire finale (int64, -1 hors domaine)."""
    down = _downstream_index(fdir)
    v = valid.ravel()
    d = np.where(down >= 0, down, 0)
    outlet = v & ((down < 0) | ~v[d])
    lab = _label_to_targets(down, v, outlet)
    lab = lab.reshape(fdir.shape)
    lab[~valid] = -1
    return lab


def stream_mask(acc: np.ndarray, cell_area_m2: float, threshold_km2: float) -> np.ndarray:
    """Réseau hydrographique : aire drainée ≥ seuil."""
    return np.nan_to_num(acc) * cell_area_m2 / 1e6 >= threshold_km2


def subbasins(fdir: np.ndarray, valid: np.ndarray, streams: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sous-bassins par tronçon de réseau. Renvoie (étiquettes, masque des nœuds exutoires)."""
    down = _downstream_index(fdir)
    s = streams.ravel() & valid.ravel()
    n_up_stream = np.zeros(s.size, np.int64)
    idx = np.nonzero(s & (down >= 0))[0]
    np.add.at(n_up_stream, down[idx], 1)
    d = np.where(down >= 0, down, 0)
    downstream_is_stream = (down >= 0) & s[d]
    junction_below = downstream_is_stream & (n_up_stream[d] >= 2)
    nodes = s & (~downstream_is_stream | junction_below)
    lab = _label_to_targets(down, valid.ravel(), nodes).reshape(fdir.shape)
    lab[~valid] = -1
    return lab, nodes.reshape(fdir.shape)


def catchment(fdir: np.ndarray, valid: np.ndarray, row: int, col: int) -> np.ndarray:
    """Bassin versant amont d'une cellule exutoire donnée (masque booléen)."""
    down = _downstream_index(fdir)
    target = np.zeros(fdir.size, np.bool_)
    target[row * fdir.shape[1] + col] = True
    lab = _label_to_targets(down, valid.ravel(), target)
    return (lab == row * fdir.shape[1] + col).reshape(fdir.shape)


def snap_to_stream(acc: np.ndarray, row: int, col: int, radius: int) -> tuple[int, int]:
    """Déplace un exutoire vers la cellule d'accumulation maximale dans un rayon (cellules)."""
    r0, r1 = max(0, row - radius), min(acc.shape[0], row + radius + 1)
    c0, c1 = max(0, col - radius), min(acc.shape[1], col + radius + 1)
    win = np.nan_to_num(acc[r0:r1, c0:c1], nan=-1)
    k = np.unravel_index(np.argmax(win), win.shape)
    return r0 + int(k[0]), c0 + int(k[1])


def flat_water_mask(z: np.ndarray, min_cells: int) -> np.ndarray:
    """Masque des surfaces d'eau aplanies lors de l'édition du SRTM.

    Hypothèse documentée : dans le SRTM édité (NGA), lacs et grands fleuves ont
    été remplacés par des surfaces d'altitude constante. Toute zone connexe de
    cellules strictement égales à leurs 4 voisines et d'au moins `min_cells`
    cellules est considérée comme de l'eau libre. À contrôler visuellement.
    """
    from scipy import ndimage as ndi

    eq = np.zeros(z.shape, bool)
    c = z[1:-1, 1:-1]
    eq[1:-1, 1:-1] = ((c == z[:-2, 1:-1]) & (c == z[2:, 1:-1])
                      & (c == z[1:-1, :-2]) & (c == z[1:-1, 2:]))
    lab, n = ndi.label(eq)
    if n == 0:
        return eq
    sizes = ndi.sum(eq, lab, np.arange(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= min_cells
    return ndi.binary_dilation(keep[lab])


@njit(cache=True)
def _strahler(down, stream):
    n = down.size
    indeg = np.zeros(n, np.int64)
    for i in range(n):
        if stream[i] and down[i] >= 0 and stream[down[i]]:
            indeg[down[i]] += 1
    order = np.zeros(n, np.int32)
    maxin = np.zeros(n, np.int32)
    cntmax = np.zeros(n, np.int32)
    stack = np.empty(n, np.int64)
    top = 0
    for i in range(n):
        if stream[i] and indeg[i] == 0:
            stack[top] = i
            top += 1
    while top > 0:
        top -= 1
        i = stack[top]
        if maxin[i] == 0:
            order[i] = 1
        elif cntmax[i] >= 2:
            order[i] = maxin[i] + 1
        else:
            order[i] = maxin[i]
        j = down[i]
        if j >= 0 and stream[j]:
            if order[i] > maxin[j]:
                maxin[j] = order[i]
                cntmax[j] = 1
            elif order[i] == maxin[j]:
                cntmax[j] += 1
            indeg[j] -= 1
            if indeg[j] == 0:
                stack[top] = j
                top += 1
    return order


def strahler_order(fdir: np.ndarray, streams: np.ndarray) -> np.ndarray:
    """Ordre de Strahler du réseau (0 hors réseau)."""
    down = _downstream_index(fdir)
    return _strahler(down, streams.ravel()).reshape(fdir.shape)


def stream_segments(fdir: np.ndarray, streams: np.ndarray, link_id: np.ndarray, transform):
    """Vectorise le réseau : une ligne par tronçon (link_id), du centre des cellules."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    down = _downstream_index(fdir)
    nc = fdir.shape[1]
    s = streams.ravel()
    idx = np.nonzero(s & (down >= 0))[0]
    idx = idx[s[down[idx]]]
    def xy(k):
        r, c = np.divmod(k, nc)
        return transform.c + (c + 0.5) * transform.a, transform.f + (r + 0.5) * transform.e
    x0, y0 = xy(idx)
    x1, y1 = xy(down[idx])
    lid = link_id.ravel()[idx]
    out = {}
    for k in np.unique(lid):
        sel = np.nonzero(lid == k)[0]
        segs = [LineString([(x0[i], y0[i]), (x1[i], y1[i])]) for i in sel]
        m = linemerge(MultiLineString(segs))
        out[int(k)] = m
    return out


def fill_interior_voids(z: np.ndarray, exclude: np.ndarray | None = None):
    """Comble les vides intérieurs (NoData entourés de terrain) pour le routage seulement.

    Les vides SRTM agiraient sinon comme des puits. Interpolation GDAL
    (pondération inverse à la distance, rasterio.fill.fillnodata). Les NoData qui
    touchent le bord du raster et les cellules de `exclude` (eau) ne sont pas
    comblés. Renvoie (z_comblé, masque des cellules comblées).
    """
    from scipy import ndimage as ndi
    from rasterio.fill import fillnodata

    nan = np.isnan(z)
    if exclude is not None:
        nan &= ~exclude
    lab, n = ndi.label(nan)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    interior = nan & ~np.isin(lab, border)
    if not interior.any():
        return z.copy(), interior
    filled = fillnodata(np.where(np.isnan(z), 0, z).astype("float32"),
                        mask=(~np.isnan(z)).astype("uint8"), max_search_distance=100)
    out = z.copy()
    out[interior] = filled[interior]
    return out, interior


@njit(cache=True)
def _priority_flood_eps(z):
    """Priority-Flood + epsilon (Barnes, Lehman & Mulla, 2014).

    Exutoires = cellules valides du bord ou voisines d'un NoData. Chaque cellule
    reçoit au minimum nextafter(altitude de la cellule qui l'a atteinte) : toute
    cellule a ensuite un chemin strictement descendant vers un exutoire.
    """
    nr, nc = z.shape
    out = z.copy()
    closed = np.zeros((nr, nc), np.bool_)
    heap = [(0.0, np.int64(0))]
    heap.pop()
    for r in range(nr):
        for c in range(nc):
            if np.isnan(z[r, c]):
                closed[r, c] = True
                continue
            edge = r == 0 or c == 0 or r == nr - 1 or c == nc - 1
            if not edge:
                for k in range(8):
                    if np.isnan(z[r + D8_DROW[k], c + D8_DCOL[k]]):
                        edge = True
                        break
            if edge:
                closed[r, c] = True
                heapq.heappush(heap, (out[r, c], np.int64(r * nc + c)))
    while len(heap) > 0:
        zc, i = heapq.heappop(heap)
        r = i // nc
        c = i % nc
        for k in range(8):
            rr = r + D8_DROW[k]
            cc = c + D8_DCOL[k]
            if rr < 0 or rr >= nr or cc < 0 or cc >= nc or closed[rr, cc]:
                continue
            closed[rr, cc] = True
            lim = np.nextafter(zc, np.inf)
            if out[rr, cc] < lim:
                out[rr, cc] = lim
            heapq.heappush(heap, (out[rr, cc], np.int64(rr * nc + cc)))
    return out


def priority_flood_epsilon(z: np.ndarray) -> np.ndarray:
    return _priority_flood_eps(z.astype("float64"))
