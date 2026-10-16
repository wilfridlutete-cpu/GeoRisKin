from rest_framework import viewsets
from rest_framework_gis.filters import InBBoxFilter

from .models import AdministrativeUnit, Dataset, TerrainProduct
from .serializers import AdministrativeUnitSerializer, DatasetSerializer, TerrainProductSerializer


class DatasetViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dataset.objects.all()
    serializer_class = DatasetSerializer
    filterset_fields = ["type", "statut"]


class AdministrativeUnitViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AdministrativeUnit.objects.all()
    serializer_class = AdministrativeUnitSerializer
    filterset_fields = ["niveau", "parent", "nom"]
    bbox_filter_field = "geom"
    filter_backends = viewsets.ReadOnlyModelViewSet.filter_backends + [InBBoxFilter]


class TerrainProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TerrainProduct.objects.all()
    serializer_class = TerrainProductSerializer
