import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.gis.geos import Polygon
from django.test import TestCase, override_settings


def zone_wgs84(km=1.0):
    """Carré dans une zone non bâtie de Mont-Ngafula (défini en UTM 33S, envoyé en WGS84)."""
    x, y = 535500, 9499500
    p = Polygon.from_bbox((x, y, x + km * 1000, y + km * 1000))
    p.srid = 32733
    return json.loads(p.transform(4326, clone=True).geojson)


class ScenarioAPITests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def post(self, params, km=1.0):
        with override_settings(GEORISKIN_SCENARIOS_DIR=Path(self.tmp)):
            return self.client.post("/api/v1/scenarios/", {"zone_geojson": zone_wgs84(km), "parametres": params},
                                    content_type="application/json")

    def test_sans_modification_refuse(self):
        self.assertEqual(self.post({}).status_code, 400)

    def test_parametres_invalides(self):
        self.assertEqual(self.post({"reboisement": {"part": 2, "classes": [30]}}).status_code, 400)
        self.assertEqual(self.post({"pratique": {"id": "inconnue"}}).status_code, 400)
        self.assertEqual(self.post({"periode_pluie": "1900-1950"}).status_code, 400)

    def test_zone_trop_grande(self):
        self.assertEqual(self.post({"periode_pluie": "2011-2025"}, km=40).status_code, 400)

    def test_reboisement_complet(self):
        r = self.post({"reboisement": {"part": 1.0, "classes": [30, 60, 40, 20]}})
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d["statut"], "termine", d.get("erreur"))
        res = d["resultats"]
        self.assertLessEqual(res["variation_pct"]["mediane"], 0)
        self.assertEqual(res["membres"], 18)
        self.assertIn("difference", res["images"])

    def test_pratique_haies(self):
        d = self.post({"pratique": {"id": "haies_vives", "cible": "tout"}}).json()
        self.assertEqual(d["statut"], "termine", d.get("erreur"))
        self.assertEqual(d["resultats"]["membres"], 54)
        self.assertLess(d["resultats"]["variation_pct"]["mediane"], 0)

    def test_pluie_recente_augmente(self):
        d = self.post({"periode_pluie": "2011-2025"}).json()
        self.assertGreater(d["resultats"]["variation_pct"]["mediane"], 0)
