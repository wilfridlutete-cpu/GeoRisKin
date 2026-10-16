from django.contrib.gis import admin

from .models import AdministrativeUnit, Dataset, TerrainProduct


@admin.register(Dataset)
class DatasetAdmin(admin.GISModelAdmin):
    list_display = ["nom", "type", "statut", "resolution_m", "licence"]
    list_filter = ["type", "statut"]
    search_fields = ["nom", "source"]


@admin.register(AdministrativeUnit)
class AdministrativeUnitAdmin(admin.GISModelAdmin):
    list_display = ["nom", "niveau", "parent", "superficie_km2"]
    list_filter = ["niveau"]
    search_fields = ["nom"]


@admin.register(TerrainProduct)
class TerrainProductAdmin(admin.ModelAdmin):
    list_display = ["variable", "unites", "resolution_m", "version_moteur", "calcule_le"]
