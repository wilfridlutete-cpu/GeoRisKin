"""Import d'une campagne d'inventaire de ravines et rattachement aux ravines existantes."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.db import transaction

from geodata.models import AdministrativeUnit
from .models import InventoryCampaign, Ravine, RavineObservation

SRID = settings.GEORISKIN_SRID


@dataclass
class ImportReport:
    campagne: str
    lues: int = 0
    importees: int = 0
    nouvelles_ravines: int = 0
    rattachees: int = 0
    ignorees: list = field(default_factory=list)


def _to_multipolygon(geom: GEOSGeometry) -> MultiPolygon | None:
    if geom.geom_type == "Polygon":
        return MultiPolygon(geom, srid=geom.srid)
    if geom.geom_type == "MultiPolygon":
        return geom
    return None


def _next_code(commune: AdministrativeUnit | None) -> str:
    prefix = "RAV-" + (commune.nom[:3].upper().replace("'", "") if commune else "KIN")
    n = Ravine.objects.filter(code__startswith=prefix + "-").count() + 1
    while Ravine.objects.filter(code=f"{prefix}-{n:04d}").exists():
        n += 1
    return f"{prefix}-{n:04d}"


def match_ravine(geom: GEOSGeometry, tolerance_m: float, exclude_campaign=None) -> Ravine | None:
    """Ravine existante dont la dernière observation est à moins de `tolerance_m`.

    En cas de plusieurs candidates, celle qui recouvre le plus la nouvelle géométrie.
    """
    qs = RavineObservation.objects.filter(geom__dwithin=(geom, tolerance_m))
    if exclude_campaign is not None:
        qs = qs.exclude(campagne=exclude_campaign)
    best, best_area = None, -1.0
    for obs in qs.select_related("ravine"):
        a = obs.geom.intersection(geom.buffer(tolerance_m)).area
        if a > best_area:
            best, best_area = obs.ravine, a
    return best


@transaction.atomic
def import_campaign(records, campagne: InventoryCampaign, tolerance_m: float = 20.0) -> ImportReport:
    """Importe des enregistrements {geom (GEOS, SRID quelconque), nom, longueur_m,
    largeur_m, profondeur_m, profondeur_mesuree, etat, attributs}."""
    rep = ImportReport(campagne=str(campagne))
    for i, rec in enumerate(records):
        rep.lues += 1
        geom = rec["geom"]
        if geom is None or geom.empty:
            rep.ignorees.append((i, "géométrie vide"))
            continue
        if geom.srid != SRID:
            geom = geom.transform(SRID, clone=True)
        if not geom.valid:
            geom = geom.make_valid()
        mp = _to_multipolygon(geom)
        if mp is None:
            rep.ignorees.append((i, f"type {geom.geom_type} non surfacique"))
            continue
        ravine = match_ravine(mp, tolerance_m, exclude_campaign=campagne)
        if ravine is None:
            commune = (AdministrativeUnit.objects.filter(niveau="commune", geom__intersects=mp.point_on_surface)
                       .first())
            ravine = Ravine.objects.create(code=_next_code(commune), nom=rec.get("nom") or "", commune=commune)
            rep.nouvelles_ravines += 1
        else:
            rep.rattachees += 1
            if RavineObservation.objects.filter(ravine=ravine, campagne=campagne).exists():
                # deux polygones de la même campagne sur la même ravine : on fusionne
                obs = RavineObservation.objects.get(ravine=ravine, campagne=campagne)
                obs.geom = _to_multipolygon(obs.geom.union(mp))
                obs.save()
                rep.importees += 1
                continue
        RavineObservation.objects.create(
            ravine=ravine, campagne=campagne, geom=mp,
            longueur_m=rec.get("longueur_m"), largeur_m=rec.get("largeur_m"),
            profondeur_m=rec.get("profondeur_m"), profondeur_mesuree=bool(rec.get("profondeur_mesuree")),
            etat=rec.get("etat") or RavineObservation.State.UNKNOWN,
            attributs_origine=rec.get("attributs") or {},
        )
        rep.importees += 1
    return rep


def read_vector_file(path: str, field_map: dict | None = None):
    """Lit un fichier vecteur (SHP, GPKG, GeoJSON, KML) avec geopandas -> enregistrements."""
    import geopandas as gpd
    import pandas as pd

    field_map = field_map or {}
    g = gpd.read_file(path)
    if g.crs is None:
        raise ValueError(f"{path} : système de coordonnées absent (.prj manquant) — préciser --srid")
    srid = g.crs.to_epsg()
    out = []
    for _, row in g.iterrows():
        attrs = {k: (None if pd.isna(v) else (v if isinstance(v, (int, float, str, bool)) else str(v)))
                 for k, v in row.drop(labels="geometry").items()}
        geom = None
        if row.geometry is not None and not row.geometry.is_empty:
            from shapely import force_2d
            geom = GEOSGeometry(memoryview(force_2d(row.geometry).wkb), srid=srid)  # les KML portent un Z inutile
        def num(key):
            col = field_map.get(key)
            if not col or attrs.get(col) in (None, ""):
                return None
            try:
                return float(str(attrs[col]).replace(",", "."))
            except ValueError:
                return None
        out.append({"geom": geom, "nom": attrs.get(field_map.get("nom", ""), None),
                    "longueur_m": num("longueur_m"), "largeur_m": num("largeur_m"),
                    "profondeur_m": num("profondeur_m"), "attributs": attrs})
    return out
