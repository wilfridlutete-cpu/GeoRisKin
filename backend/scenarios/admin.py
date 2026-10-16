from django.contrib.gis import admin

from .models import Scenario


@admin.register(Scenario)
class ScenarioAdmin(admin.GISModelAdmin):
    list_display = ("nom", "zone_libelle", "statut", "cree_le", "duree_s")
    list_filter = ("statut",)
