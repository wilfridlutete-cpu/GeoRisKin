"""Inventaire des ravines, versionné par campagne d'observation.

Une ravine (Ravine) est un objet durable. Chaque campagne (InventoryCampaign :
une date, une méthode, une source) produit une observation (RavineObservation)
avec sa géométrie et ses dimensions. On peut ainsi ajouter de nouvelles
campagnes au fil du temps et suivre l'évolution de chaque ravine.

Les dimensions sont distinguées selon qu'elles sont mesurées ou estimées
(ex. profondeur déduite d'un ratio profondeur/largeur).
"""
from django.conf import settings
from django.contrib.gis.db import models

from geodata.models import AdministrativeUnit

SRID = settings.GEORISKIN_SRID


class InventoryCampaign(models.Model):
    class Method(models.TextChoices):
        IMAGERY = "imagerie", "Digitalisation sur imagerie"
        FIELD = "terrain", "Relevé de terrain (GPS/topographie)"
        DRONE = "drone", "Drone (photogrammétrie/LiDAR)"
        OTHER = "autre", "Autre"

    class Status(models.TextChoices):
        INDICATIVE = "indicatif", "Indicatif (démonstration)"
        PRELIMINARY = "preliminaire", "Préliminaire"
        VALIDATED = "valide", "Validé"

    nom = models.CharField(max_length=200, unique=True)
    date_observation = models.DateField(null=True, blank=True,
                                        help_text="date de l'imagerie ou du terrain ; vide si inconnue")
    methode = models.CharField(max_length=10, choices=Method.choices)
    source = models.CharField(max_length=300, help_text="auteur, fichier ou imagerie d'origine")
    statut = models.CharField(max_length=15, choices=Status.choices, default=Status.PRELIMINARY)
    description = models.TextField(blank=True)
    importe_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_observation"]
        verbose_name = "campagne d'inventaire"

    def __str__(self):
        return f"{self.nom} ({self.date_observation})"


class Ravine(models.Model):
    code = models.CharField(max_length=30, unique=True)
    nom = models.CharField(max_length=150, blank=True)
    commune = models.ForeignKey(AdministrativeUnit, null=True, blank=True, on_delete=models.SET_NULL,
                                limit_choices_to={"niveau": "commune"})
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.nom}".strip()

    def derniere_observation(self):
        return self.observations.order_by("-campagne__date_observation").first()


class RavineObservation(models.Model):
    class State(models.TextChoices):
        ACTIVE = "actif", "Active"
        STABLE = "stable", "Stable"
        TREATED = "amenage", "Aménagée / stabilisée"
        UNKNOWN = "inconnu", "Inconnu"

    ravine = models.ForeignKey(Ravine, on_delete=models.CASCADE, related_name="observations")
    campagne = models.ForeignKey(InventoryCampaign, on_delete=models.CASCADE, related_name="observations")
    geom = models.MultiPolygonField(srid=SRID)
    surface_m2 = models.FloatField(help_text="calculée à partir de la géométrie")
    longueur_m = models.FloatField(null=True, blank=True)
    largeur_m = models.FloatField(null=True, blank=True)
    profondeur_m = models.FloatField(null=True, blank=True)
    profondeur_mesuree = models.BooleanField(default=False,
                                             help_text="faux si estimée (ratio, hypothèse)")
    etat = models.CharField(max_length=10, choices=State.choices, default=State.UNKNOWN)
    attributs_origine = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["ravine", "campagne__date_observation"]
        constraints = [models.UniqueConstraint(fields=["ravine", "campagne"], name="une_obs_par_campagne")]
        verbose_name = "observation de ravine"

    def save(self, *args, **kwargs):
        self.surface_m2 = self.geom.area  # SRID métrique (UTM 33S)
        super().save(*args, **kwargs)
