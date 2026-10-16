from django.test import TestCase


class CarteTests(TestCase):
    def test_page_carte(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "maplibre-gl.js")
        self.assertContains(r, "estimations non validées")

    def test_catalogue_couches(self):
        d = self.client.get("/api/v1/couches/").json()
        ids = {c["id"] for c in d["couches"]}
        self.assertIn("perte", ids)
        perte = next(c for c in d["couches"] if c["id"] == "perte")
        self.assertEqual(perte["unite"], "t/ha/an")
        self.assertIn("NON VALID", perte["statut"].upper())
        self.assertTrue(perte["tuiles"].endswith("/perte/{z}/{x}/{y}.png"))

    def test_valeurs_parametres(self):
        self.assertEqual(self.client.get("/api/v1/valeurs/").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/valeurs/?lon=500&lat=0").status_code, 400)

    def test_valeurs_point_kinshasa(self):
        d = self.client.get("/api/v1/valeurs/?lon=15.3165&lat=-4.6257").json()
        v = {x["id"]: x["valeur"] for x in d["valeurs"]}
        self.assertIsNotNone(v["altitude"])
        self.assertIn("perte", v)

    def test_valeurs_hors_emprise_none(self):
        d = self.client.get("/api/v1/valeurs/?lon=10&lat=0").json()
        self.assertTrue(all(x["valeur"] is None for x in d["valeurs"]))
