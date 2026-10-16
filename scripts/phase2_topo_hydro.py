"""Phase 2 — Moteur topographique et hydrologique sur toute la ville-province.

Usage :
    python scripts/phase2_topo_hydro.py [--stream-km2 1.0] [--subbasin-km2 2.0] [--contour-m 10]

Entrées : data/processed/mnt_srtm2s_domaine_utm33s_60m.tif (phase 1),
          data/interim/srtm_kinshasa_2s_wgs84.tif (pour le masque d'eau),
          data/processed/georiskin_vecteurs_utm33s.gpkg (province).
Sorties : data/processed/topo/*.tif (découpés sur la province + 2 km),
          data/processed/georiskin_hydro_utm33s.gpkg (réseau, bassins, sous-bassins,
          courbes de niveau, masque d'eau), outputs/phase2_rapport.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
import rasterio.mask
from rasterio.enums import Resampling
from rasterio.features import shapes, geometry_mask
from rasterio.warp import reproject
from shapely.geometry import shape, Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import terrain_metrics as tm  # noqa: E402
from engine import flow_analysis as fa  # noqa: E402

PROC, INTERIM, OUT = ROOT / "data/processed", ROOT / "data/interim", ROOT / "outputs"
TOPO = PROC / "topo"
TOPO.mkdir(parents=True, exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--stream-km2", type=float, default=1.0, help="seuil d'aire drainée du réseau")
ap.add_argument("--subbasin-km2", type=float, default=2.0, help="seuil du réseau servant aux sous-bassins")
ap.add_argument("--contour-m", type=float, default=10.0, help="équidistance des courbes de niveau")
ap.add_argument("--water-min-km2", type=float, default=0.5, help="surface minimale d'une zone d'eau aplanie")
args = ap.parse_args()

log: dict = {"parametres": vars(args)}
timings: dict = {}
tracemalloc.start()


def tick(name, t0):
    timings[name] = round(time.perf_counter() - t0, 2)
    return time.perf_counter()


t = time.perf_counter()
sys.path.insert(0, str(ROOT / "scripts"))
from dem_config import dem_source, dem_paths  # noqa: E402

SRC = dem_source()
PATHS = dem_paths(SRC)
log["source_mnt"] = {"type": SRC["kind"], "resolution_m": SRC["res"], "fichier": PATHS["domaine"].name}
with rasterio.open(PATHS["domaine"]) as s:
    z = s.read(1).astype("float64")
    prof = s.profile.copy()
    tr, crs, res = s.transform, s.crs, s.res[0]
cell_km2 = res * res / 1e6
gpkg_base = PROC / "georiskin_vecteurs_utm33s.gpkg"
province = gpd.read_file(gpkg_base, layer="province")
clip_geom = province.buffer(2000).geometry
# Fenêtre de sortie = emprise province + 2 km (les calculs hydrologiques restent sur tout le domaine)
from rasterio.windows import from_bounds  # noqa: E402
WIN = from_bounds(*clip_geom.total_bounds, transform=tr).round_offsets().round_lengths()
R0, C0 = int(WIN.row_off), int(WIN.col_off)
R1, C1 = min(z.shape[0], R0 + int(WIN.height)), min(z.shape[1], C0 + int(WIN.width))
R0, C0 = max(0, R0), max(0, C0)
WTR = rasterio.windows.transform(rasterio.windows.Window(C0, R0, C1 - C0, R1 - R0), tr)
OUTMASK = geometry_mask(clip_geom, (R1 - R0, C1 - C0), WTR)  # True = hors zone

# --- Masque d'eau (zones aplanies SRTM), calculé sur la grille native puis reprojeté
with rasterio.open(PATHS["mosaique"]) as s:
    zn = s.read(1).astype("float32")
    zn[zn == s.nodata] = np.nan
    px_km2 = (s.res[0] * 111.32) * (s.res[1] * 110.6)  # approx. à 4,5°S
    wn = fa.flat_water_mask(zn, int(args.water_min_km2 / px_km2)).astype("uint8")
    del zn
    water = np.zeros(z.shape, "uint8")
    reproject(wn, water, src_transform=s.transform, src_crs=s.crs, dst_transform=tr,
              dst_crs=crs, resampling=Resampling.nearest)
water = water.astype(bool) & ~np.isnan(z)
log["eau_km2"] = float(water.sum() * cell_km2)
t = tick("masque_eau", t)

# --- Indicateurs topographiques (MNT brut, non conditionné), par bandes avec recouvrement
# d'une ligne : ce sont des opérateurs 3×3, le découpage ne change pas le résultat.
def new_out(name, dtype, nodata, desc, units):
    p = prof.copy()
    p.update(dtype=dtype, nodata=nodata, count=1, compress="deflate", width=C1 - C0, height=R1 - R0,
             transform=WTR, tiled=True, blockxsize=256, blockysize=256, predictor=1)
    d = rasterio.open(TOPO / f"{name}.tif", "w", **p)
    d.update_tags(DESCRIPTION=desc, UNITS=units, SOURCE_DEM=f"SRTM DTED2, {SRC['res']:g} m",
                  ENGINE="georiskin phase 2")
    return d


TERRAIN = {
    "altitude_m": ("float32", np.nan, "Altitude SRTM (geoide EGM96)", "m", lambda zz: zz),
    "pente_deg": ("float32", np.nan, "Pente, Horn 1981", "degres", lambda zz: tm.slope(zz, res, "degrees")),
    "pente_pct": ("float32", np.nan, "Pente, Horn 1981", "%", lambda zz: tm.slope(zz, res, "percent")),
    "exposition_deg": ("float32", np.nan, "Exposition depuis le nord, sens horaire", "degres",
                       lambda zz: tm.aspect(zz, res)),
    "ombrage": ("uint8", 0, "Ombrage az 315 h 45", "0-255", lambda zz: tm.hillshade(zz, res)),
    "courbure_profil": ("float32", np.nan, "Zevenbergen-Thorne, >0 convexe", "1/m",
                        lambda zz: tm.curvatures(zz, res)[0]),
    "courbure_plan": ("float32", np.nan, "Zevenbergen-Thorne, >0 divergent", "1/m",
                      lambda zz: tm.curvatures(zz, res)[1]),
}
outs = {k: new_out(k, *v[:4]) for k, v in TERRAIN.items()}
STRIP = 512
for r in range(R0, R1, STRIP):
    a0, a1 = max(0, r - 1), min(z.shape[0], r + STRIP + 1)
    zz = z[a0:a1, max(0, C0 - 1):min(z.shape[1], C1 + 1)]
    top = r - a0
    left = C0 - max(0, C0 - 1)
    h = min(STRIP, R1 - r)
    m = OUTMASK[r - R0:r - R0 + h]
    for k, (dtype, nod, _, _, fn) in TERRAIN.items():
        v = np.asarray(fn(zz))[top:top + h, left:left + (C1 - C0)].astype(dtype)
        v[m] = nod
        outs[k].write(v, 1, window=rasterio.windows.Window(0, r - R0, C1 - C0, h))
for d in outs.values():
    d.close()
t = tick("indicateurs_topographiques", t)

# --- Conditionnement et écoulements.
# 1) Nettoyage : îlots de moins de 10 cellules isolés par l'eau ou le NoData -> NoData
#    (sinon le comblement les traite comme des cuvettes fermées).
from scipy import ndimage as ndi  # noqa: E402

def drop_islands(zz, min_cells=10):
    v = ~np.isnan(zz)
    lab, n = ndi.label(v, structure=np.ones((3, 3)))
    sizes = ndi.sum(v, lab, np.arange(1, n + 1))
    small = np.zeros(n + 1, bool)
    small[1:] = sizes < min_cells
    out = zz.copy()
    out[small[lab]] = np.nan
    return out

# 2) Tracé du fleuve Congo : le SRTM n'aplanit que le Pool Malebo et quelques biefs ;
#    en aval (rapides), le lit n'est pas plat. On route d'abord l'écoulement avec l'eau
#    incluse, puis on suit le chemin D8 descendant depuis chaque bief aplani du Congo
#    (altitude <= CONGO_MAX_Z) jusqu'à la limite du MNT. Lit = biefs aplanis + chemins.
CONGO_MAX_Z = 275.0
z0, _ = fa.fill_interior_voids(drop_islands(z))
cond0 = fa.condition_dem(z0, tr, crs)
fdir0 = fa.flow_direction(cond0.dem, res)
wlab, wn_ = ndi.label(water)
congo_seed = np.zeros(z.shape, bool)
for k in range(1, wn_ + 1):
    m = wlab == k
    if np.nanmedian(z[m]) <= CONGO_MAX_Z:
        congo_seed |= m
down0 = fa._downstream_index(fdir0)
path = congo_seed.ravel().copy()
stack = list(np.nonzero(congo_seed.ravel())[0])
while stack:
    i = stack.pop()
    j = down0[i]
    if j >= 0 and not path[j]:
        path[j] = True
        stack.append(j)
fleuve = ndi.binary_dilation(path.reshape(z.shape)) & ~np.isnan(z)
del z0, cond0, fdir0, down0, path, wlab
autre_eau = water & ~fleuve
log["fleuve_congo_km2"] = float(fleuve.sum() * cell_km2)
t = tick("trace_congo", t)

# 3) Conditionnement final : fleuve et eau libre = exutoires (NoData pour le routage).
z_fill, voids = fa.fill_interior_voids(z, exclude=fleuve | water)  # vides SRTM d'origine seulement
z_h = drop_islands(np.where(fleuve | water, np.nan, z_fill))
log["vides_srtm_combles_pour_routage"] = int(voids.sum())
cond = fa.condition_dem(z_h, tr, crs)
log["conditionnement"] = cond.stats
t = tick("conditionnement", t)
valid = ~np.isnan(cond.dem)
fdir = fa.flow_direction(cond.dem, res)
t = tick("direction_d8", t)
acc = fa.flow_accumulation(fdir, valid)
area_km2 = (acc * cell_km2).astype("float32")
t = tick("accumulation", t)
streams = fa.stream_mask(acc, res * res, args.stream_km2)
order = fa.strahler_order(fdir, streams)
lab_b = fa.basins(fdir, valid)
streams_sb = fa.stream_mask(acc, res * res, args.subbasin_km2)
lab_sb, nodes = fa.subbasins(fdir, valid, streams_sb)
links, _ = fa.subbasins(fdir, valid, streams)  # identifiant de tronçon pour la vectorisation
t = tick("reseau_bassins", t)


# --- Écriture des rasters hydrologiques sur la fenêtre province + 2 km
def write_clip(name, arr, dtype, nodata, desc, units, deja_fenetre=False):
    d = new_out(name, dtype, nodata, desc, units)
    v = np.asarray(arr if deja_fenetre else arr[R0:R1, C0:C1]).astype(dtype)
    v[OUTMASK] = nodata
    d.write(v, 1)
    d.close()
    return f"{name}.tif"


files = list(f"{k}.tif" for k in TERRAIN) + [
    write_clip("mnt_conditionne_m", np.where(np.isnan(cond.dem[R0:R1, C0:C1]), z[R0:R1, C0:C1],
                                             cond.dem[R0:R1, C0:C1]), "float32", np.nan,
               "MNT conditionne (Priority-Flood), eau libre exclue", "m", deja_fenetre=True),
    write_clip("profondeur_comblement_m", np.nan_to_num(cond.fill_depth[R0:R1, C0:C1]), "float32", np.nan,
               "MNT conditionne - MNT brut", "m", deja_fenetre=True),
    write_clip("direction_d8", fdir, "uint8", 255, "D8 code ESRI 1=E..128=NE, 0=exutoire", "code"),
    write_clip("aire_drainee_km2", area_km2, "float32", np.nan,
               "Aire drainee amont (D8)", "km2"),
    write_clip("ordre_strahler", order, "uint8", 0, f"Strahler, reseau >= {args.stream_km2} km2", "ordre"),
    write_clip("eau_libre", (water | fleuve).astype("uint8") + fleuve.astype("uint8"), "uint8", 255,
               "1 = eau aplanie SRTM, 2 = lit du Congo trace (hypothese)", "classe"),
]
log["rasters"] = files
t = tick("ecriture_rasters", t)

# --- Vecteurs
in_prov = ~geometry_mask(province.geometry, z.shape, tr)


def polygonize(labels, keep_ids, field):
    rows = []
    m = np.isin(labels, list(keep_ids))
    for geom, v in shapes(labels.astype("int32") if labels.max() < 2**31 else labels, mask=m, transform=tr):
        rows.append({field: int(v), "geometry": shape(geom)})
    g = gpd.GeoDataFrame(rows, crs=crs).dissolve(by=field, as_index=False)
    return g


def outlet_info(ids):
    nc = z.shape[1]
    r, c = np.divmod(np.asarray(ids, dtype=np.int64), nc)
    x = tr.c + (c + 0.5) * tr.a
    y = tr.f + (r + 0.5) * tr.e
    return x, y, r, c


# Bassins principaux : exutoire final, intersectant la province, > 1 km²
ids, counts = np.unique(lab_b[in_prov & valid], return_counts=True)
area_all = {i: n for i, n in zip(*np.unique(lab_b[valid], return_counts=True))}
keep = [i for i in ids if area_all[i] * cell_km2 >= 1.0]
bas = polygonize(lab_b, keep, "id_exutoire")
x, y, r, c = outlet_info(bas["id_exutoire"])
bas["superficie_km2"] = [area_all[i] * cell_km2 for i in bas["id_exutoire"]]
bas["exutoire_x"], bas["exutoire_y"] = x, y
def neigh(mask):
    m = np.zeros(z.shape, bool)
    p = np.pad(mask, 1)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                m |= p[1 + dr:1 + dr + z.shape[0], 1 + dc:1 + dc + z.shape[1]]
    return m

near_congo, near_water = neigh(fleuve), neigh(autre_eau)
near_nodata = neigh(np.isnan(z) | (np.isnan(z_h) & ~fleuve & ~water))
on_edge = (r == 0) | (c == 0) | (r == z.shape[0] - 1) | (c == z.shape[1] - 1)
bas["exutoire_type"] = np.select(
    [near_congo[r, c], near_water[r, c], near_nodata[r, c] | on_edge],
    ["fleuve Congo", "autre eau libre", "limite du MNT (bassin possiblement incomplet)"],
    default="cuvette residuelle")
bas["part_dans_province_pct"] = [100 * float(((lab_b == i) & in_prov).sum()) / area_all[i]
                                 for i in bas["id_exutoire"]]
bas["nom"] = None  # à renseigner (Funa, Ndjili, Lukunga…) : non déduit automatiquement
bas = bas.sort_values("superficie_km2", ascending=False).reset_index(drop=True)
bas.insert(0, "code", [f"BV{k+1:04d}" for k in range(len(bas))])

# Sous-bassins
ids_sb = np.unique(lab_sb[in_prov & valid])
ids_sb = ids_sb[ids_sb >= 0]
sb = polygonize(lab_sb, ids_sb, "id_noeud")
cnt_sb = dict(zip(*np.unique(lab_sb[valid], return_counts=True)))
sb["superficie_km2"] = [cnt_sb[i] * cell_km2 for i in sb["id_noeud"]]
x, y, r, c = outlet_info(sb["id_noeud"])
sb["exutoire_x"], sb["exutoire_y"] = x, y
sb["aire_drainee_exutoire_km2"] = area_km2[r, c]
sb["code_bassin"] = None
code_of = dict(zip(bas["id_exutoire"], bas["code"]))
sb["code_bassin"] = [code_of.get(int(lab_b[rr, cc])) for rr, cc in zip(r, c)]

# Réseau
segs = fa.stream_segments(fdir, streams & in_prov, links, tr)
nc_ = z.shape[1]
rows = []
for k, geom in segs.items():
    rr, cc = divmod(k, nc_)
    rows.append({"id_troncon": k, "ordre_strahler": int(order[rr, cc]),
                 "aire_drainee_km2": float(area_km2[rr, cc]),
                 "code_bassin": code_of.get(int(lab_b[rr, cc])), "geometry": geom})
net = gpd.GeoDataFrame(rows, crs=crs)
t = tick("vectorisation", t)

# Courbes de niveau (sur la province)
zc = np.where(in_prov | ~geometry_mask(clip_geom, z.shape, tr), z, np.nan)
cl = tm.contours(zc, tr, args.contour_m)
cont = gpd.GeoDataFrame({"altitude_m": [lv for lv, _ in cl]}, geometry=[g for _, g in cl], crs=crs)
cont = cont[cont.length >= 2 * res]
t = tick("courbes_de_niveau", t)

# Eau libre
cls = np.where(fleuve, 2, np.where(water, 1, 0)).astype("uint8")
wp = gpd.GeoDataFrame([{"classe": "fleuve Congo (trace)" if v == 2 else "eau aplanie SRTM", "geometry": shape(g)}
                       for g, v in shapes(cls, mask=cls > 0, transform=tr)], crs=crs).dissolve(by="classe", as_index=False)

hydro = PROC / "georiskin_hydro_utm33s.gpkg"
if hydro.exists():
    hydro.unlink()
bas.to_file(hydro, layer="bassins_versants", driver="GPKG")
sb.to_file(hydro, layer="sous_bassins", driver="GPKG")
net.to_file(hydro, layer="reseau_hydrographique", driver="GPKG")
cont.to_file(hydro, layer="courbes_de_niveau", driver="GPKG")
wp.to_file(hydro, layer="eau_libre_srtm", driver="GPKG")
t = tick("ecriture_vecteurs", t)

# --- Rapport
log["bassins"] = {"n": int(len(bas)),
                  "par_type_exutoire": bas["exutoire_type"].value_counts().to_dict(),
                  "plus_grands": bas.head(12)[["code", "superficie_km2", "exutoire_type",
                                               "part_dans_province_pct"]].round(1).to_dict("records")}
log["sous_bassins"] = {"n": int(len(sb)), "superficie_mediane_km2": float(sb.superficie_km2.median())}
log["reseau"] = {"troncons": int(len(net)), "longueur_km": float(net.length.sum() / 1000),
                 "ordre_max": int(net.ordre_strahler.max())}
log["courbes_de_niveau"] = {"n": int(len(cont)), "equidistance_m": args.contour_m}
log["temps_s"] = timings
log["memoire_pic_python_Mo"] = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
log["grille"] = {"shape": list(z.shape), "res_m": res}
(OUT / "phase2_rapport.json").write_text(json.dumps(log, indent=2, ensure_ascii=False, default=float),
                                        encoding="utf-8")
print(json.dumps(log, indent=1, ensure_ascii=False, default=float))
