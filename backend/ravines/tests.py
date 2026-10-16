"""Tests de l'inventaire versionné et de l'API (PostGIS requis)."""
from datetime import date

from django.contrib.auth.models import User
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase
from rest_framework.test import APIClient

from geodata.models import AdministrativeUnit
from ravines.models import InventoryCampaign, Ravine, RavineObservation
from ravines.services import import_campaign

SRID = 32733


def square(x, y, side):
    p = Polygon.from_bbox((x, y, x + side, y + side))
    p.srid = SRID
    return p


class InventoryTests(TestCase):
    def setUp(self):
        self.commune = AdministrativeUnit.objects.create(
            niveau="commune", nom="Kisenso", superficie_km2=1,
            geom=MultiPolygon(square(530000, 9500000, 10000), srid=SRID))
        self.c1 = InventoryCampaign.objects.create(nom="2015", date_observation=date(2015, 6, 1),
                                                   methode="imagerie", source="test")
        self.c2 = InventoryCampaign.objects.create(nom="2026", date_observation=date(2026, 9, 1),
                                                   methode="terrain", source="test")

    def test_surface_computed_in_metres(self):
        import_campaign([{"geom": square(531000, 9501000, 20)}], self.c1)
        obs = RavineObservation.objects.get()
        self.assertAlmostEqual(obs.surface_m2, 400.0, places=3)
        self.assertEqual(obs.ravine.commune, self.commune)
        self.assertTrue(obs.ravine.code.startswith("RAV-KIS-"))

    def test_second_campaign_links_to_existing_ravine(self):
        import_campaign([{"geom": square(531000, 9501000, 20)},
                         {"geom": square(535000, 9505000, 20)}], self.c1)
        # la ravine s'est agrandie (40 m) et une nouvelle apparaît loin
        rep = import_campaign([{"geom": square(531000, 9501000, 40)},
                               {"geom": square(538000, 9508000, 20)}], self.c2)
        self.assertEqual(rep.rattachees, 1)
        self.assertEqual(rep.nouvelles_ravines, 1)
        self.assertEqual(Ravine.objects.count(), 3)
        r = Ravine.objects.filter(observations__campagne=self.c1).filter(observations__campagne=self.c2).get()
        surfaces = [o.surface_m2 for o in r.observations.order_by("campagne__date_observation")]
        self.assertEqual([round(s) for s in surfaces], [400, 1600])

    def test_wgs84_input_is_reprojected(self):
        p = Polygon.from_bbox((15.33, -4.42, 15.3302, -4.4198))
        p.srid = 4326
        import_campaign([{"geom": p}], self.c1)
        obs = RavineObservation.objects.get()
        self.assertEqual(obs.geom.srid, SRID)
        self.assertTrue(400 < obs.surface_m2 < 600)  # ≈ 22 m × 22 m

    def test_non_polygon_is_reported_not_imported(self):
        from django.contrib.gis.geos import Point
        rep = import_campaign([{"geom": Point(531000, 9501000, srid=SRID)}], self.c1)
        self.assertEqual(rep.importees, 0)
        self.assertEqual(len(rep.ignorees), 1)

    def test_api_public_read_auth_write(self):
        import_campaign([{"geom": square(531000, 9501000, 20)}], self.c1)
        c = APIClient()
        r = c.get("/api/v1/observations-ravines/")
        self.assertEqual(r.status_code, 200)
        f = r.json()["results"]["features"][0]
        lon, lat = f["geometry"]["coordinates"][0][0][0]
        self.assertTrue(14 < lon < 17 and -6 < lat < -4)  # GeoJSON en WGS84
        self.assertEqual(c.post("/api/v1/campagnes/", {"nom": "x"}).status_code, 403)
        c.force_authenticate(User.objects.create_user("u"))
        r = c.post("/api/v1/campagnes/", {"nom": "x", "methode": "terrain", "source": "s"})
        self.assertEqual(r.status_code, 201)
