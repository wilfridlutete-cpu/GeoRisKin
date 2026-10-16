"""Numérisation automatique de la Carte géologique du Congo, feuille Léopoldville S.5/15
(1/200 000, Service géologique / MRAC, IGM Belgique 1963), fournie en image.

Étapes (documentées ; résultat à vérifier visuellement, ce n'est pas une numérisation experte) :
 1. calage affine sur trois coins du cadre lus sur l'image : (15°E, 5°S), (16°E, 5°S), (16°E, 4°S) ;
 2. classification des couleurs par plus proche voisin (espace CIE Lab) sur les couleurs de la
    légende, seuil de distance au-delà duquel le pixel est « indéterminé » (traits, textes) ;
 3. filtre majoritaire 9×9 pixels (≈ 560 m) pour combler traits et étiquettes ;
 4. reprojection (plus proche voisin) sur la grille de travail UTM 33S à 30 m, vectorisation.
Regroupements : Ccb + Cca (grès crétacés tendres, limite non cartographiée sur la carte
elle-même) ; I1 + P (couleurs trop proches à cette résolution).
"""
import json
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import shapes, rasterize
from rasterio.transform import Affine
from rasterio.warp import reproject
from scipy import ndimage as ndi
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "data/raw/geologie/carte_geologique_leopoldville_S5-15_1963.jpg"
OUTD = ROOT / "data/processed/geologie"
OUTD.mkdir(parents=True, exist_ok=True)

UNITS = {  # code: (libellé, couleur de légende RGB, regroupement)
    1: ("Ho – alluvions de fonds de vallée et basses terrasses (Holocène)", (177, 193, 152)),
    2: ("Q – alluvions de moyennes terrasses et anciennes du Pool", (168, 143, 96)),
    3: ("QPs – sables plus ou moins argileux sur aplanissements", (164, 168, 98)),
    4: ("QSo – sables remaniés des sables ocre", (250, 249, 102)),
    5: ("So – sables ocre, série du Kalahari supérieur (Néogène)", (248, 225, 42)),
    6: ("Gp – grès polymorphes (Paléogène)", (170, 198, 43)),
    7: ("Ccb/Cca – grès tendres crétacés (blanchâtres ou rouges)", (68, 129, 85)),
    8: ("Cc/I2 – Crétacé indifférencié et/ou série de l'Inkisi", (125, 104, 45)),
    9: ("I2 – Inkisi, étage supérieur : quartzites, arkoses, schistes", (159, 115, 48)),
    10: ("I1/P – Inkisi inférieur et Mpioka : arkoses, quartzites, schistes rouges", (104, 62, 30)),
    11: ("Eau libre (fleuve, Pool) / non cartographié", (232, 232, 222)),
}
MAX_DE = 28.0  # distance Lab maximale pour accepter une couleur


def rgb2lab(rgb):
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


a = np.asarray(Image.open(IMG).convert("RGB")).astype("float64")
H, W = a.shape[:2]
# 1. calage : pixel (col, ligne) -> (lon, lat), trois points de contrôle
P = np.array([[104.0, 2190.0], [1881.0, 2180.0], [1870.0, 415.0]])
G = np.array([[15.0, -5.0], [16.0, -5.0], [16.0, -4.0]])
A = np.c_[P, np.ones(3)]
cx = np.linalg.solve(A, G[:, 0])
cy = np.linalg.solve(A, G[:, 1])
img_tr = Affine(cx[0], cx[1], cx[2], cy[0], cy[1], cy[2])

# 2. classification
lab = rgb2lab(a)
ref = rgb2lab(np.array([v[1] for v in UNITS.values()], dtype="float64"))
d = np.linalg.norm(lab[:, :, None, :] - ref[None, None, :, :], axis=-1)
cls = np.array(list(UNITS))[np.argmin(d, axis=-1)].astype("uint8")
cls[np.min(d, axis=-1) > MAX_DE] = 0
# masque : intérieur du cadre (cellules dont la position est dans 15–16°E, 5–4°S, avec débord nord-est)
cols, rows = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
lon = img_tr.a * cols + img_tr.b * rows + img_tr.c
lat = img_tr.d * cols + img_tr.e * rows + img_tr.f
inside = (lon >= 15.0) & (lon <= 16.0) & (lat >= -5.0) & (lat <= -3.99) & (cols < 1885)
cls[~inside] = 0
undetermined_before = float(np.mean(cls[inside] == 0))

# 3. filtre majoritaire (les 0 ne votent pas)
votes = np.zeros((len(UNITS) + 1, H, W), "float32")
for k in UNITS:
    votes[k] = ndi.uniform_filter((cls == k).astype("float32"), size=9)
maj = np.argmax(votes[1:], axis=0).astype("uint8") + 1
maj[(votes[1:].max(axis=0) == 0) | ~inside] = 0

# 4. reprojection sur la grille 30 m
with rasterio.open(ROOT / "data/processed/topo/pente_deg.tif") as g:
    prof, tr, crs, shp = g.profile.copy(), g.transform, g.crs, (g.height, g.width)
geo = np.zeros(shp, "uint8")
reproject(maj, geo, src_transform=img_tr, src_crs="EPSG:4326", dst_transform=tr, dst_crs=crs,
          src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
prof.update(dtype="uint8", nodata=0, compress="deflate", predictor=1)
with rasterio.open(OUTD / "geologie_1963_30m.tif", "w", **prof) as o:
    o.write(geo, 1)
    o.update_tags(SOURCE="Carte geologique du Congo, feuille Leopoldville S.5/15, 1/200 000, 1963 "
                         "(numerisation automatique GeoRisKin, a verifier)",
                  CLASSES=json.dumps({k: v[0] for k, v in UNITS.items()}, ensure_ascii=False))

rows_ = [{"code": int(v), "unite": UNITS[int(v)][0], "geometry": shape(g)}
         for g, v in shapes(geo, mask=geo > 0, transform=tr)]
gdf = gpd.GeoDataFrame(rows_, crs=crs).dissolve(by=["code", "unite"], as_index=False)
gdf["superficie_km2"] = gdf.area / 1e6
gdf["source"] = "Carte géologique Léopoldville S.5/15, 1963, numérisation automatique (à vérifier)"
gdf.to_file(OUTD / "geologie_1963.gpkg", layer="unites_geologiques", driver="GPKG")

# Contrôles : alluvions (Ho) vs aire drainée et pente ; communes
with rasterio.open(ROOT / "data/processed/topo/aire_drainee_km2.tif") as s:
    acc = s.read(1)
with rasterio.open(ROOT / "data/processed/topo/pente_deg.tif") as s:
    sl = s.read(1)
covered = geo > 0
rep = {"calage_m_par_pixel": float(np.hypot(img_tr.a, img_tr.d) * 111320),
       "rotation_deg": float(np.degrees(np.arctan2(img_tr.d, img_tr.a))),
       "part_pixels_indetermines_avant_filtre_pct": round(100 * undetermined_before, 1),
       "superficie_par_unite_km2": {UNITS[int(r.code)][0].split(" –")[0]: round(r.superficie_km2, 1)
                                    for r in gdf.itertuples()},
       "pente_mediane_par_unite_deg": {UNITS[k][0].split(" –")[0]: round(float(np.nanmedian(sl[geo == k])), 2)
                                       for k in UNITS if (geo == k).any()},
       "aire_drainee_mediane_par_unite_km2": {UNITS[k][0].split(" –")[0]: round(float(np.nanmedian(acc[geo == k])), 4)
                                              for k in UNITS if (geo == k).any()},
       "part_province_couverte_pct": None}
B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
prov = gpd.read_file(B, layer="province")
pm = rasterize(((g, 1) for g in prov.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
rep["part_province_couverte_pct"] = round(float(100 * covered[pm].mean()), 1)
rav = gpd.read_file(B, layer="ravines_observees")
rm = rasterize(((g, 1) for g in rav.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
u, c = np.unique(geo[rm & covered], return_counts=True)
rep["unites_sous_ravines_indicatives_pct"] = {UNITS[int(k)][0].split(" –")[0]: round(100 * n / c.sum(), 1)
                                              for k, n in zip(u, c)}
(ROOT / "outputs/geologie_1963_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
print(json.dumps(rep, indent=1, ensure_ascii=False))
