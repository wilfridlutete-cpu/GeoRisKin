from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from config.geo import wgs84_geometry_field

from .models import InventoryCampaign, Ravine, RavineObservation


class CampaignSerializer(serializers.ModelSerializer):
    n_observations = serializers.IntegerField(source="observations.count", read_only=True)

    class Meta:
        model = InventoryCampaign
        fields = "__all__"


class ObservationSerializer(GeoFeatureModelSerializer):
    geometrie, get_geometrie = wgs84_geometry_field()
    ravine_code = serializers.CharField(source="ravine.code", read_only=True)
    campagne_nom = serializers.CharField(source="campagne.nom", read_only=True)
    date_observation = serializers.DateField(source="campagne.date_observation", read_only=True)
    statut_donnee = serializers.CharField(source="campagne.statut", read_only=True)

    class Meta:
        model = RavineObservation
        geo_field = "geometrie"
        fields = ["id", "ravine", "ravine_code", "campagne", "campagne_nom", "date_observation", "statut_donnee",
                  "surface_m2", "longueur_m", "largeur_m", "profondeur_m", "profondeur_mesuree", "etat"]


class RavineSerializer(serializers.ModelSerializer):
    commune = serializers.CharField(source="commune.nom", default=None, read_only=True)
    evolution = serializers.SerializerMethodField()

    class Meta:
        model = Ravine
        fields = ["id", "code", "nom", "commune", "notes", "evolution"]

    def get_evolution(self, obj):
        """Surface par campagne, de la plus ancienne à la plus récente (sans date : en dernier)."""
        obs = obj.observations.select_related("campagne").order_by("campagne__date_observation")
        return [{"campagne": o.campagne.nom, "date": o.campagne.date_observation,
                 "surface_m2": round(o.surface_m2, 1), "statut": o.campagne.statut} for o in obs]
