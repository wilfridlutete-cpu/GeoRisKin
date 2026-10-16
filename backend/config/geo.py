"""Sortie GeoJSON en WGS84 (RFC 7946), avec simplification optionnelle.

Les géométries sont stockées en UTM 33S (calculs métriques) ; l'API les renvoie
en degrés WGS84. `?simplifier=<m>` simplifie en mètres avant reprojection
(topologie préservée), pour alléger l'affichage web.
"""
from rest_framework_gis.fields import GeometrySerializerMethodField


def wgs84_geometry_field():
    def get(self, obj):
        g = obj.geom
        req = self.context.get("request")
        tol = 0.0
        if req is not None:
            try:
                tol = max(0.0, float(req.query_params.get("simplifier", 0)))
            except ValueError:
                tol = 0.0
        if tol:
            g = g.simplify(tol, preserve_topology=True)
        return g.transform(4326, clone=True)
    return GeometrySerializerMethodField(), get
