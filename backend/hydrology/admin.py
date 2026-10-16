from django.contrib.gis import admin

from .models import HydroRun, StreamSegment, Watershed


@admin.register(HydroRun)
class HydroRunAdmin(admin.ModelAdmin):
    list_display = ["id", "mnt", "version_moteur", "actif", "calcule_le"]


@admin.register(Watershed)
class WatershedAdmin(admin.GISModelAdmin):
    list_display = ["code", "nom", "niveau", "superficie_km2", "exutoire_type"]
    list_filter = ["niveau", "exutoire_type", "run"]
    list_editable = ["nom"]
    search_fields = ["code", "nom"]


@admin.register(StreamSegment)
class StreamSegmentAdmin(admin.GISModelAdmin):
    list_display = ["id_troncon", "nom", "ordre_strahler", "aire_drainee_km2"]
    list_filter = ["ordre_strahler"]
    list_editable = ["nom"]
    search_fields = ["nom"]
