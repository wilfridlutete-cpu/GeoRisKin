from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from rest_framework import serializers

from geodata.models import AdministrativeUnit
from hydrology.models import Watershed

from .models import Scenario
from .service import ZONE_MAX_KM2, valider


class ScenarioSerializer(serializers.ModelSerializer):
    bassin_id = serializers.IntegerField(write_only=True, required=False)
    unite_id = serializers.IntegerField(write_only=True, required=False)
    zone_geojson = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = Scenario
        fields = ["id", "nom", "parametres", "zone_libelle", "statut", "resultats", "erreur", "version_moteur",
                  "duree_s", "cree_le", "bassin_id", "unite_id", "zone_geojson"]
        read_only_fields = ["zone_libelle", "statut", "resultats", "erreur", "version_moteur", "duree_s", "cree_le"]

    def validate(self, attrs):
        try:
            attrs["parametres"] = valider(attrs.get("parametres") or {})
        except ValueError as e:
            raise serializers.ValidationError({"parametres": str(e)})
        srid = settings.GEORISKIN_SRID
        if attrs.get("bassin_id"):
            w = Watershed.objects.filter(pk=attrs["bassin_id"]).first()
            if not w:
                raise serializers.ValidationError({"bassin_id": "bassin inconnu"})
            geom, lib = w.geom, f"{'Bassin' if w.niveau == 'bassin' else 'Sous-bassin'} {w.code}{' – ' + w.nom if w.nom else ''}"
        elif attrs.get("unite_id"):
            u = AdministrativeUnit.objects.filter(pk=attrs["unite_id"]).first()
            if not u:
                raise serializers.ValidationError({"unite_id": "unité inconnue"})
            geom, lib = u.geom, f"{u.get_niveau_display() if hasattr(u, 'get_niveau_display') else u.niveau} {u.nom}"
        elif attrs.get("zone_geojson"):
            import json
            g = GEOSGeometry(json.dumps(attrs["zone_geojson"]), srid=4326)
            if g.geom_type not in ("Polygon", "MultiPolygon"):
                raise serializers.ValidationError({"zone_geojson": "polygone attendu"})
            geom, lib = g.transform(srid, clone=True), "zone dessinée"
        else:
            raise serializers.ValidationError("indiquez bassin_id, unite_id ou zone_geojson")
        if geom.geom_type == "Polygon":
            geom = MultiPolygon(geom, srid=geom.srid)
        if geom.area / 1e6 > ZONE_MAX_KM2:
            raise serializers.ValidationError(f"zone trop grande ({geom.area / 1e6:.0f} km² > {ZONE_MAX_KM2:.0f} km²) : "
                                              "choisissez un bassin, un sous-bassin ou une commune plus petite")
        attrs["zone"], attrs["zone_libelle"] = geom, lib
        for k in ("bassin_id", "unite_id", "zone_geojson"):
            attrs.pop(k, None)
        return attrs
