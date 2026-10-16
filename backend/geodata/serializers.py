from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from config.geo import wgs84_geometry_field

from .models import AdministrativeUnit, Dataset, TerrainProduct


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dataset
        exclude = ["emprise"]


class AdministrativeUnitSerializer(GeoFeatureModelSerializer):
    geometrie, get_geometrie = wgs84_geometry_field()
    class Meta:
        model = AdministrativeUnit
        geo_field = "geometrie"
        fields = ["id", "niveau", "nom", "code", "parent", "superficie_km2", "statistiques"]


class TerrainProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = TerrainProduct
        fields = "__all__"
