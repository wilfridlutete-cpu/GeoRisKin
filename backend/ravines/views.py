from rest_framework import viewsets
from rest_framework_gis.filters import InBBoxFilter

from .models import InventoryCampaign, Ravine, RavineObservation
from .serializers import CampaignSerializer, ObservationSerializer, RavineSerializer


class CampaignViewSet(viewsets.ModelViewSet):
    queryset = InventoryCampaign.objects.all()
    serializer_class = CampaignSerializer


class RavineViewSet(viewsets.ModelViewSet):
    queryset = Ravine.objects.select_related("commune")
    serializer_class = RavineSerializer
    filterset_fields = ["commune"]


class ObservationViewSet(viewsets.ReadOnlyModelViewSet):
    """Observations ; `?campagne=<id>` ou `?ravine=<id>` ; écriture via import ou admin."""

    queryset = RavineObservation.objects.select_related("ravine", "campagne")
    serializer_class = ObservationSerializer
    filterset_fields = ["campagne", "ravine", "etat"]
    bbox_filter_field = "geom"
    filter_backends = viewsets.ReadOnlyModelViewSet.filter_backends + [InBBoxFilter]
