from django.conf import settings
from django.contrib.gis.db import models


class Scenario(models.Model):
    STATUTS = [("en_cours", "en cours"), ("termine", "terminé"), ("echec", "échec")]
    nom = models.CharField(max_length=200, blank=True, default="Scénario")
    parametres = models.JSONField(help_text="interventions, période de pluie, zone (référence)")
    zone = models.MultiPolygonField(srid=settings.GEORISKIN_SRID)
    zone_libelle = models.CharField(max_length=200, blank=True)
    statut = models.CharField(max_length=10, choices=STATUTS, default="en_cours")
    resultats = models.JSONField(default=dict, blank=True)
    erreur = models.TextField(blank=True)
    version_moteur = models.CharField(max_length=40, blank=True)
    duree_s = models.FloatField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.nom} ({self.zone_libelle})"
