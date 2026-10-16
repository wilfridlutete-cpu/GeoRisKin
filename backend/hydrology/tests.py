from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase
from rest_framework.test import APIClient

from geodata.models import Dataset
from hydrology.models import HydroRun, Watershed


class WatershedApiTests(TestCase):
    def setUp(self):
        mnt = Dataset.objects.create(nom="mnt", type="raster", statut="observe", source="test")
        run = HydroRun.objects.create(mnt=mnt, parametres={}, version_moteur="t")
        old = HydroRun.objects.create(mnt=mnt, parametres={}, version_moteur="t", actif=False)
        p = Polygon.from_bbox((530000, 9500000, 540000, 9510000))
        p.srid = 32733
        for r, code in ((run, "BV0001"), (old, "BV0001")):
            Watershed.objects.create(run=r, niveau="bassin", code=code, superficie_km2=100,
                                     exutoire=Point(535000, 9500000, srid=32733), geom=MultiPolygon(p, srid=32733))

    def test_point_query_returns_only_active_run(self):
        pt = Point(535000, 9505000, srid=32733).transform(4326, clone=True)
        r = APIClient().get(f"/api/v1/bassins/au-point/?lon={pt.x}&lat={pt.y}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["features"]), 1)

    def test_point_query_requires_coordinates(self):
        self.assertEqual(APIClient().get("/api/v1/bassins/au-point/").status_code, 400)
