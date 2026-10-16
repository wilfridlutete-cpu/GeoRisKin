from django.conf import settings
from django.contrib import admin
from django.views.static import serve

from carte.views import CouchesView, PratiquesView, ValeursView, index
from scenarios.views import ScenarioViewSet
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from geodata.views import AdministrativeUnitViewSet, DatasetViewSet, TerrainProductViewSet
from hydrology.views import StreamSegmentViewSet, WatershedViewSet
from ravines.views import CampaignViewSet, ObservationViewSet, RavineViewSet

router = DefaultRouter()
router.register("datasets", DatasetViewSet)
router.register("unites-administratives", AdministrativeUnitViewSet)
router.register("produits-topographiques", TerrainProductViewSet)
router.register("bassins", WatershedViewSet, basename="bassin")
router.register("reseau", StreamSegmentViewSet, basename="reseau")
router.register("campagnes", CampaignViewSet)
router.register("ravines", RavineViewSet)
router.register("observations-ravines", ObservationViewSet)
router.register("scenarios", ScenarioViewSet)

urlpatterns = [
    path("", index, name="carte"),
    path("admin/", admin.site.urls),
    path("api/v1/couches/", CouchesView.as_view(), name="couches"),
    path("api/v1/valeurs/", ValeursView.as_view(), name="valeurs"),
    path("api/v1/pratiques/", PratiquesView.as_view(), name="pratiques"),
    path("api/v1/", include(router.urls)),
]
if settings.GEORISKIN_SERVE_TILES:
    urlpatterns.append(path(f"{settings.GEORISKIN_TILES_URL.strip('/')}/<path:path>", serve,
                            {"document_root": settings.GEORISKIN_TILES_DIR}))
    urlpatterns.append(path(f"{settings.GEORISKIN_SCENARIOS_URL.strip('/')}/<path:path>", serve,
                            {"document_root": settings.GEORISKIN_SCENARIOS_DIR}))
