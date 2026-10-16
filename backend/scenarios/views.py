import traceback

from rest_framework import mixins, permissions, viewsets
from rest_framework.throttling import ScopedRateThrottle

from .models import Scenario
from .serializers import ScenarioSerializer
from .service import executer_scenario


class ScenarioViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin,
                      viewsets.GenericViewSet):
    """Création publique (limitée en débit) et consultation des scénarios. Calcul synchrone (zones ≤ 1000 km²)."""
    queryset = Scenario.objects.all()
    serializer_class = ScenarioSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = "scenarios"

    def get_throttles(self):
        if self.action == "create":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        sc = serializer.save(cree_par=user, nom=serializer.validated_data.get("nom") or "Scénario")
        try:
            executer_scenario(sc)
        except Exception as e:  # noqa: BLE001 – l'erreur est enregistrée et renvoyée
            sc.statut, sc.erreur = "echec", f"{e}\n{traceback.format_exc(limit=3)}"
            sc.save()
