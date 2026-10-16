"""Charge en base les sorties des phases 1 et 2 (catalogue, limites, bassins, ravines indicatives).

    python manage.py load_georiskin [--reset]

Lit data/processed/*.gpkg, data/processed/topo/*.tif et outputs/phase*_rapport.json.
"""
import json
from pathlib import Path

import geopandas as gpd
import rasterio
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, MultiLineString, Point, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction
from shapely import force_2d

from geodata.models import AdministrativeUnit, Dataset, TerrainProduct
from hydrology.models import HydroRun, StreamSegment, Watershed
from ravines.models import InventoryCampaign, Ravine
from ravines.services import import_campaign

SRID = settings.GEORISKIN_SRID
ENGINE_VERSION = "0.2.0"


LS_META = {"methode": "LS RUSLE : L Desmet & Govers 1996 x S McCool 1987, 30 m",
           "hors_domaine": "cellules a ecoulement concentre (aire drainee >= 0,1 km2) exclues"}


EXTRA_PREFIXES = ("pct_", "k_moyen", "a_moy_", "perte_", "part_domaine", "geol_")


def ls_stats(r):
    out = {}
    if "ls_moyen" in r and r["ls_moyen"] == r["ls_moyen"]:
        out = {"ls_moyen": round(float(r["ls_moyen"]), 3), "ls_median": round(float(r["ls_median"]), 3),
               "ls_p90": round(float(r["ls_p90"]), 3),
               "part_ecoulement_concentre_pct": round(float(r["part_ecoulement_concentre_pct"]), 2), **LS_META}
    for k, v in r.items():
        if not isinstance(k, str) or not k.startswith(EXTRA_PREFIXES):
            continue
        if isinstance(v, str):
            out[k] = v
        elif v is not None and v == v:
            out[k] = round(float(v), 4)
    return out


def geos(g, kind=None):
    g = GEOSGeometry(memoryview(force_2d(g).wkb), srid=SRID)
    if kind is MultiPolygon and g.geom_type == "Polygon":
        g = MultiPolygon(g, srid=SRID)
    if kind is MultiLineString and g.geom_type == "LineString":
        g = MultiLineString(g, srid=SRID)
    return g


class Command(BaseCommand):
    help = "Charge le catalogue, les limites, le calcul hydrologique et les ravines indicatives"

    def add_arguments(self, p):
        p.add_argument("--reset", action="store_true", help="vide d'abord les tables concernées")

    @transaction.atomic
    def handle(self, *a, **o):
        data = Path(settings.GEORISKIN_DATA_DIR)
        proc, out = data / "processed", settings.PROJECT_ROOT / "outputs"
        if o["reset"]:
            for m in (StreamSegment, Watershed, HydroRun, TerrainProduct, InventoryCampaign, Ravine, AdministrativeUnit):
                m.objects.all().delete()
            Dataset.objects.all().delete()

        # Catalogue -------------------------------------------------------------
        import sys
        sys.path.insert(0, str(settings.PROJECT_ROOT / "scripts"))
        from dem_config import dem_source, dem_paths
        src = dem_source()
        dem_path = dem_paths(src)["domaine"]
        res = src["res"]
        with rasterio.open(dem_path) as s:
            b = s.bounds
        emprise = Polygon.from_bbox((b.left, b.bottom, b.right, b.top))
        emprise.srid = SRID
        nom_mnt = (f"MNT SRTM DTED2 1\" ({res:g} m)" if src["kind"] == "dt2"
                   else f"MNT SRTM DTED2 vue réduite ({res:g} m)")
        mnt, _ = Dataset.objects.update_or_create(nom=nom_mnt, defaults=dict(
            type="raster", statut="observe", source="NGA/NASA SRTM via OSFAC, tuiles DTED2 E015-016 S05-06",
            licence="SRTM : domaine public", scr="EPSG:32733", resolution_m=res, unites="m (géoïde EGM96)",
            fichier=str(dem_path.relative_to(data)),
            description=("Tuiles DTED2 1\" reprojetées (bilinéaire) en UTM 33S." if src["kind"] == "dt2"
                         else "Vues réduites ≈2\" des tuiles DTED2 ré-échantillonnées (bilinéaire) en UTM 33S."),
            limites_connues="Modèle de surface (bâti, végétation). Géoréférencement reconstruit (±30 m). "
                            "Bande au nord de 4°S (≈114 km² de Maluku) non couverte.",
            emprise=emprise))
        if any("Copernicus" in f.name for f in src["files"]):
            Dataset.objects.update_or_create(nom="Copernicus DEM GLO-30, tuile S04 E015", defaults=dict(
                type="raster", statut="observe", source="ESA / Airbus, Copernicus DEM GLO-30 (fourni par l'utilisateur)",
                licence="Licence Copernicus DEM GLO-30 (libre, attribution)", scr="EPSG:4326", resolution_m=30,
                unites="m (géoïde EGM2008)", fichier="raw/srtm_dted2/Copernicus_DSM_COG_10_S04_00_E015_00_DEM.tif",
                description="Complète le SRTM au nord de 4°S (Maluku). Mosaïqué avec priorité au SRTM.",
                limites_connues="Autre capteur (TanDEM-X 2011-2015) et autre géoïde (EGM2008) que le SRTM ; "
                                "biais au raccord +0,4 m en moyenne. Modèle de surface."))
        quart_ds, _ = Dataset.objects.update_or_create(nom="Quartiers de Kinshasa (CENI)", defaults=dict(
            type="vecteur", statut="observe", source="Ville_Kinshasa_quartier.shp, champ Source = CENI",
            licence="non précisée", scr="EPSG:4326 -> 32733", description="367 quartiers, 24 communes"))
        rav_ds, _ = Dataset.objects.update_or_create(nom="Ravines Fils_CartoRavin (indicatif)", defaults=dict(
            type="vecteur", statut="indicatif", source="Prof. Fils : erosions.shp, Export_Output_*.shp",
            description="Données fournies à titre indicatif pour Kisenso et Lemba."))

        # Limites -----------------------------------------------------------------
        AdministrativeUnit.objects.all().delete()
        g = proc / "georiskin_vecteurs_utm33s.gpkg"
        prov = gpd.read_file(g, layer="province").iloc[0]
        p = AdministrativeUnit.objects.create(niveau="province", nom="Kinshasa", superficie_km2=prov.superficie_km2,
                                              source=quart_ds, geom=geos(prov.geometry, MultiPolygon))
        communes = {}
        for _, r in gpd.read_file(g, layer="communes").iterrows():
            communes[r.Commune] = AdministrativeUnit.objects.create(
                niveau="commune", nom=r.nom, code=str(r.Com_id), parent=p, superficie_km2=r.superficie_km2,
                statistiques=ls_stats(r),
                source=quart_ds, geom=geos(r.geometry, MultiPolygon))
        q = gpd.read_file(g, layer="quartiers")
        AdministrativeUnit.objects.bulk_create([
            AdministrativeUnit(niveau="quartier", nom=r.Nom, code=str(r.Quartie_id), parent=communes.get(r.Commune),
                               superficie_km2=r.geometry.area / 1e6, source=quart_ds,
                               geom=geos(r.geometry.buffer(0), MultiPolygon))
            for _, r in q.iterrows()], ignore_conflicts=True)

        # Produits topographiques -------------------------------------------------
        rep2 = json.loads((out / "phase2_rapport.json").read_text(encoding="utf-8"))
        for f in sorted((proc / "topo").glob("*.tif")):
            with rasterio.open(f) as s:
                tags = s.tags()
                res = s.res[0]
            TerrainProduct.objects.update_or_create(variable=f.stem, mnt_source=mnt, defaults=dict(
                nom=tags.get("DESCRIPTION", f.stem), unites=tags.get("UNITS", ""),
                methode=tags.get("DESCRIPTION", ""), fichier=str(f.relative_to(data)), resolution_m=res,
                parametres=rep2.get("parametres", {}), version_moteur=ENGINE_VERSION))

        # Hydrologie ------------------------------------------------------------------
        HydroRun.objects.filter(actif=True).update(actif=False)
        run = HydroRun.objects.create(mnt=mnt, parametres=rep2.get("parametres", {}),
                                      version_moteur=ENGINE_VERSION, rapport=rep2)
        h = proc / "georiskin_hydro_utm33s.gpkg"
        basins = {}
        for _, r in gpd.read_file(h, layer="bassins_versants").iterrows():
            nm = r.get("nom") if isinstance(r.get("nom"), str) else ""
            basins[r.code] = Watershed.objects.create(
                run=run, niveau="bassin", code=r.code, nom=nm,
                nom_source=(r.get("nom_source") or "") if nm else "", superficie_km2=r.superficie_km2,
                exutoire=Point(r.exutoire_x, r.exutoire_y, srid=SRID), exutoire_type=r.exutoire_type,
                part_dans_province_pct=r.part_dans_province_pct, statistiques=ls_stats(r),
                geom=geos(r.geometry, MultiPolygon))
        sb = gpd.read_file(h, layer="sous_bassins")
        Watershed.objects.bulk_create([
            Watershed(run=run, niveau="sous_bassin", code=f"SB{int(r.id_noeud)}", parent=basins.get(r.code_bassin),
                      nom=r.nom if isinstance(r.get("nom"), str) else "",
                      nom_source="carte des cours d'eau fournie" if isinstance(r.get("nom"), str) else "",
                      superficie_km2=r.superficie_km2, exutoire=Point(r.exutoire_x, r.exutoire_y, srid=SRID),
                      statistiques=ls_stats(r), geom=geos(r.geometry, MultiPolygon))
            for _, r in sb.iterrows()], batch_size=500)
        net = gpd.read_file(h, layer="reseau_hydrographique")
        StreamSegment.objects.bulk_create([
            StreamSegment(run=run, id_troncon=int(r.id_troncon), ordre_strahler=int(r.ordre_strahler),
                          nom=r.nom if isinstance(r.get("nom"), str) else "",
                          aire_drainee_km2=float(r.aire_drainee_km2), bassin=basins.get(r.code_bassin),
                          geom=geos(r.geometry, MultiLineString)) for _, r in net.iterrows()], batch_size=1000)

        # Ravines indicatives : deux campagnes (date inconnue / 2010) ------------------
        rav = gpd.read_file(g, layer="ravines_observees")
        n_imp = 0
        for nom, date, sel in [
            ("Fils_CartoRavin erosions.shp (indicatif, date inconnue)", None,
             rav.source == "Fils_CartoRavin/erosions.shp"),
            ("Fils_CartoRavin KML 2010 (indicatif)", "2010-01-01", rav.annee.astype(str) == "2010"),
        ]:
            sub = rav[sel]
            if sub.empty:
                continue
            camp, _ = InventoryCampaign.objects.get_or_create(nom=nom, defaults=dict(
                date_observation=date, methode="imagerie", source="Prof. Fils (Fils_CartoRavin)",
                statut="indicatif", description="Date au 1er janvier : seule l'année est connue." if date else ""))
            def clean(v):
                return None if v is None or (isinstance(v, float) and v != v) else v
            recs = [{"geom": geos(r.geometry), "nom": clean(r.get("nom")),
                     "longueur_m": clean(r.get("longueur_m_attr")), "attributs": {"source": r.source}}
                    for _, r in sub.iterrows()]
            rep = import_campaign(recs, camp)
            n_imp += rep.importees
        self.stdout.write(self.style.SUCCESS(
            f"Chargé : {AdministrativeUnit.objects.count()} unités administratives, "
            f"{Watershed.objects.filter(run=run).count()} bassins/sous-bassins, "
            f"{StreamSegment.objects.filter(run=run).count()} tronçons, {n_imp} observations de ravines, "
            f"{TerrainProduct.objects.count()} produits topographiques."))
