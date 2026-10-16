from django.conf import settings
from django.contrib.gis.geos import Point
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework_gis.filters import InBBoxFilter

from .models import StreamSegment, Watershed
from .serializers import StreamSegmentSerializer, WatershedSerializer


class WatershedViewSet(viewsets.ReadOnlyModelViewSet):
    """Bassins du calcul actif. `?niveau=bassin|sous_bassin`, `?in_bbox=xmin,ymin,xmax,ymax` (WGS84)."""

    serializer_class = WatershedSerializer
    filterset_fields = ["niveau", "parent", "code", "nom"]
    bbox_filter_field = "geom"
    filter_backends = viewsets.ReadOnlyModelViewSet.filter_backends + [InBBoxFilter]

    def get_queryset(self):
        return Watershed.objects.filter(run__actif=True)

    @action(detail=False, url_path="au-point")
    def at_point(self, request):
        """Bassin et sous-bassin contenant un point : `?lon=15.33&lat=-4.41`."""
        try:
            pt = Point(float(request.query_params["lon"]), float(request.query_params["lat"]), srid=4326)
        except (KeyError, ValueError):
            raise ValidationError("paramètres lon et lat requis (degrés WGS84)")
        pt.transform(settings.GEORISKIN_SRID)
        qs = self.get_queryset().filter(geom__contains=pt)
        return Response(WatershedSerializer(qs, many=True).data)


class StreamSegmentViewSet(viewsets.ReadOnlyModelViewSet):
    """Réseau calculé. `?ordre_strahler__gte=3` pour alléger l'affichage."""

    serializer_class = StreamSegmentSerializer
    filterset_fields = {"ordre_strahler": ["exact", "gte"], "bassin": ["exact"], "nom": ["exact", "icontains"]}
    bbox_filter_field = "geom"
    filter_backends = viewsets.ReadOnlyModelViewSet.filter_backends + [InBBoxFilter]

    def get_queryset(self):
        return StreamSegment.objects.filter(run__actif=True)
