from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from config.geo import wgs84_geometry_field

from .models import StreamSegment, Watershed


class WatershedSerializer(GeoFeatureModelSerializer):
    exutoire_lonlat = serializers.SerializerMethodField()

    def get_exutoire_lonlat(self, obj):
        p = obj.exutoire.transform(4326, clone=True)
        return [round(p.x, 6), round(p.y, 6)]

    geometrie, get_geometrie = wgs84_geometry_field()
    class Meta:
        model = Watershed
        geo_field = "geometrie"
        fields = ["id", "run", "niveau", "code", "nom", "nom_source", "parent", "superficie_km2", "exutoire_lonlat",
                  "exutoire_type", "part_dans_province_pct", "statistiques"]


class StreamSegmentSerializer(GeoFeatureModelSerializer):
    geometrie, get_geometrie = wgs84_geometry_field()
    class Meta:
        model = StreamSegment
        geo_field = "geometrie"
        fields = ["id", "id_troncon", "nom", "ordre_strahler", "aire_drainee_km2", "bassin"]
