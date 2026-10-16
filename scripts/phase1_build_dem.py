"""Phase 1 — Construit le premier MNT géoréférencé et harmonise les couches vecteur.

Usage :
    python scripts/phase1_build_dem.py

Entrées (data/raw) :
    srtm_dted2/DTED_*.DT2           tuiles SRTM DTED2 complètes (1", ≈30 m) — source principale
    srtm_dted2_ovr/DTED_*.DT2.ovr   vues réduites (≈2") — repli à 60 m si les .DT2 manquent
    quartiers/Ville_Kinshasa_quartier.shp
    ravines_fils/erosions.shp, Export_Output_*.shp   ravines digitalisées
Sorties :
    data/interim/   tuiles GeoTIFF géoréférencées + mosaïque WGS84
    data/processed/ MNT UTM 33S (domaine hydrologique et ville-province) + couches GPKG
    outputs/        rapports JSON et figures de contrôle
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import rasterio.mask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from engine.raster_io import (UTM33S, georeference_dted_overview, mosaic,  # noqa: E402
                              reproject_dem, dem_report, write_json)

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
RAW, INTERIM, PROC, OUT = (ROOT / "data/raw", ROOT / "data/interim",
                           ROOT / "data/processed", ROOT / "outputs")
for d in (INTERIM, PROC, OUT):
    d.mkdir(parents=True, exist_ok=True)

from dem_config import dem_source, dem_paths, DOMAIN_WGS84  # noqa: E402

SRC = dem_source()
RES = SRC["res"]
PATHS = dem_paths(SRC)
log: dict = {"source_mnt": SRC["kind"], "resolution_m": RES, "fichiers": [f.name for f in SRC["files"]]}

# 1. Tuiles géoréférencées ----------------------------------------------------
tiles = []
if SRC["kind"] == "dt2":
    # GDAL lit le format DTED nativement (géoréférencement inclus dans l'en-tête)
    tiles = list(SRC["files"])
    for t in tiles:
        with rasterio.open(t) as s:
            log.setdefault("tiles", []).append({"file": t.name, "shape": [s.height, s.width],
                                                "pixel_deg": s.res[0], "crs": s.crs.to_string(),
                                                "nodata_count": int((s.read(1) == s.nodata).sum())})
else:
    for ovr in SRC["files"]:
        dst = INTERIM / (ovr.name.replace(".DT2.ovr", "_2s.tif"))
        log.setdefault("tiles", []).append(georeference_dted_overview(ovr, dst))
        tiles.append(dst)


# 2. Contrôle des raccords : les tuiles DTED partagent leur ligne/colonne de bord
def edge(path, which):
    with rasterio.open(path) as s:
        a = s.read(1).astype(float)
        a[a == s.nodata] = np.nan
    return {"N": a[0], "S": a[-1], "W": a[:, 0], "E": a[:, -1]}[which]


by_name = {t.name.split(".")[0].replace("_2s", ""): t for t in tiles}
# Copernicus GLO-30 ne partage pas sa ligne de bord avec le SRTM : les lignes comparées sont
# voisines (≈30 m d'écart). L'écart moyen et le biais signé mesurent le raccord des deux produits.
pairs = [("DTED_E015_S05", "S", "DTED_E015_S06", "N"), ("DTED_E016_S05", "S", "DTED_E016_S06", "N"),
         ("DTED_E015_S05", "E", "DTED_E016_S05", "W"), ("DTED_E015_S06", "E", "DTED_E016_S06", "W"),
         ("DTED_E016_S04", "S", "DTED_E016_S05", "N"),
         ("Copernicus_DSM_COG_10_S04_00_E015_00_DEM", "S", "DTED_E015_S05", "N")]
seams = []
for a, ea, b, eb in pairs:
    if a in by_name and b in by_name:
        ea_, eb_ = edge(by_name[a], ea), edge(by_name[b], eb)
        n = min(ea_.size, eb_.size)  # DTED : 3601 échantillons par bord, Copernicus : 3600
        d = ea_[:n] - eb_[:n]
        seams.append({"pair": f"{a}:{ea} / {b}:{eb}", "identical_fraction": float(np.nanmean(d == 0)),
                      "mean_abs_diff_m": float(np.nanmean(np.abs(d))), "biais_moyen_m": float(np.nanmean(d)),
                      "biais_median_m": float(np.nanmedian(d))})
log["seams"] = seams

# 3. Mosaïque WGS84 -----------------------------------------------------------
mos = PATHS["mosaique"]
mosaic(tiles, mos)
log["mosaic_wgs84"] = dem_report(mos).__dict__

# 4. Couches vecteur harmonisées en UTM 33S -----------------------------------
# La limite de la ville-province est reconstruite à partir des 367 quartiers
# (24 communes, Maluku compris). KIN.shp ne contient que 23 communes (sans Maluku).
quartiers = gpd.read_file(RAW / "quartiers/Ville_Kinshasa_quartier.shp").to_crs(UTM33S)
quartiers["geometry"] = quartiers.geometry.make_valid()
communes = quartiers.dissolve(by="Commune", as_index=False)[["Commune", "Com_id", "geometry"]]
communes["nom"] = communes["Commune"].replace({"Kinsenso": "Kisenso"})  # graphie usuelle
communes["superficie_km2"] = communes.area / 1e6
from shapely.geometry import Polygon, MultiPolygon  # noqa: E402


def clean_union(geom, hole_max_m2=1e5, part_min_m2=5e4):
    """Supprime les interstices entre quartiers (trous < 0,1 km²) et les éclats (< 0,05 km²)."""
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    out = [Polygon(q.exterior, [r for r in q.interiors if Polygon(r).area >= hole_max_m2])
           for q in parts if q.area >= part_min_m2]
    return MultiPolygon(out) if len(out) > 1 else out[0]


communes["geometry"] = [clean_union(g) for g in communes.geometry]
province = gpd.GeoDataFrame({"nom": ["Ville-province de Kinshasa"]},
                            geometry=[clean_union(communes.union_all())], crs=UTM33S)
province["superficie_km2"] = province.area / 1e6

rav_main = gpd.read_file(RAW / "ravines_fils/erosions.shp")  # déjà en UTM 33S
rav_main = rav_main[rav_main.geometry.notna() & ~rav_main.geometry.is_empty].copy()
rav_main["Surface_m2"] = pd.to_numeric(rav_main["Surface"].astype(str).str.replace(",", "."),
                                       errors="coerce")
rav_main["source"] = "Fils_CartoRavin/erosions.shp"

exports = []
for p in sorted((RAW / "ravines_fils").glob("Export_Output_*.shp")):
    g = gpd.read_file(p)
    if g.crs is None:  # .prj absent de la livraison : coordonnées en degrés (vérifié)
        g = g.set_crs(4326)
    g = g.to_crs(UTM33S)
    g["source"] = f"Fils_CartoRavin/{p.name}"
    g["annee"] = g["Name"].astype(str).str.extract(r"(\d{4})")[0] if "Name" in g else None
    exports.append(g[["source", "annee", "geometry"]])
rav_exp = gpd.GeoDataFrame(pd.concat(exports, ignore_index=True), crs=UTM33S)
rav_exp["geometry"] = rav_exp.geometry.force_2d()

ravines = pd.concat([
    rav_main[["Noms", "Long", "Surface_m2", "source", "geometry"]]
    .rename(columns={"Noms": "nom", "Long": "longueur_m_attr"}), rav_exp], ignore_index=True)
ravines = gpd.GeoDataFrame(ravines, crs=UTM33S)
ravines["aire_calc_m2"] = ravines.geometry.area
ravines["statut_donnee"] = "indicatif"  # données de démonstration fournies pour une partie de la ville
ravines = gpd.sjoin(ravines, communes[["nom", "geometry"]].rename(columns={"nom": "commune"}),
                    how="left", predicate="intersects").drop(columns="index_right")
ravines = ravines[~ravines.index.duplicated()]

gpkg = PROC / "georiskin_vecteurs_utm33s.gpkg"
if gpkg.exists():
    gpkg.unlink()
province.to_file(gpkg, layer="province", driver="GPKG")
communes.to_file(gpkg, layer="communes", driver="GPKG")
quartiers.to_file(gpkg, layer="quartiers", driver="GPKG")
ravines.to_file(gpkg, layer="ravines_observees", driver="GPKG")
log["province_km2"] = float(province.superficie_km2.iloc[0])
log["communes_km2"] = communes.set_index("nom")["superficie_km2"].round(1).to_dict()
log["ravines"] = {"n_total": int(len(ravines)),
                  "par_commune": ravines["commune"].fillna("hors communes").value_counts().to_dict()}

# 5. MNT de la ville-province --------------------------------------------------
# Domaine hydrologique = toute la mosaïque (15–17°E, 6–4°S) : les rivières qui
# traversent Kinshasa (Ndjili, Lukaya, Nsele…) prennent leur source au sud de la
# limite provinciale ; leurs bassins doivent être complets pour l'accumulation.
dem_dom = PATHS["domaine"]
reproject_dem(mos, dem_dom, UTM33S, RES, DOMAIN_WGS84)
log["mnt_domaine_hydrologique"] = dem_report(dem_dom).__dict__

dem_kin = PATHS["kinshasa"]
with rasterio.open(dem_dom) as s:
    arr, tr = rasterio.mask.mask(s, province.buffer(2000).geometry, crop=True, nodata=np.nan)
    prof = s.profile.copy()
prof.update(width=arr.shape[2], height=arr.shape[1], transform=tr)
with rasterio.open(dem_kin, "w", **prof) as d:
    d.write(arr)
    d.update_tags(ZONE="Ville-province de Kinshasa + 2 km", UNITS="m",
                  VERTICAL_DATUM="EGM96 (geoide)")
log["mnt_kinshasa"] = dem_report(dem_kin).__dict__

# Partie de la province non couverte par les 4 tuiles (au nord de 4°S)
from shapely.geometry import box  # noqa: E402
with rasterio.open(mos) as s_:
    mb = s_.bounds
cover = gpd.GeoSeries([box(mb.left, mb.bottom, mb.right, mb.top)], crs=4326).to_crs(UTM33S).iloc[0]
log["province_hors_mnt_km2"] = float(province.geometry.iloc[0].difference(cover).area / 1e6)

# 6. Contrôles de plausibilité altimétrique -----------------------------------
with rasterio.open(dem_kin) as s:
    def sample(gdf):
        pts = [(p.x, p.y) for p in gdf.geometry.representative_point()]
        return np.array([v[0] for v in s.sample(pts)], dtype=float)
    communes["z_point_interieur_m"] = sample(communes)
    ravines["z_m"] = sample(ravines)
log["z_communes"] = communes.set_index("nom")["z_point_interieur_m"].round(0).to_dict()
log["z_ravines"] = {"min": float(np.nanmin(ravines.z_m)), "median": float(np.nanmedian(ravines.z_m)),
                    "max": float(np.nanmax(ravines.z_m))}

write_json(log, OUT / "phase1_rapport.json")
print(json.dumps(log, indent=1, ensure_ascii=False, default=str)[:6000])
