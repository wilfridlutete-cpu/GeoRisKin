from django.contrib.gis import admin

from .models import InventoryCampaign, Ravine, RavineObservation


class ObservationInline(admin.TabularInline):
    model = RavineObservation
    fields = ["campagne", "surface_m2", "longueur_m", "profondeur_m", "profondeur_mesuree", "etat"]
    readonly_fields = ["surface_m2"]
    extra = 0


@admin.register(InventoryCampaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["nom", "date_observation", "methode", "statut"]
    list_filter = ["methode", "statut"]


@admin.register(Ravine)
class RavineAdmin(admin.ModelAdmin):
    list_display = ["code", "nom", "commune"]
    search_fields = ["code", "nom"]
    inlines = [ObservationInline]


@admin.register(RavineObservation)
class ObservationAdmin(admin.GISModelAdmin):
    list_display = ["ravine", "campagne", "surface_m2", "etat"]
    list_filter = ["campagne", "etat"]
    readonly_fields = ["surface_m2"]
