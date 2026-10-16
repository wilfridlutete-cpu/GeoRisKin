"""Résultats hydrologiques : un calcul (HydroRun) reproductible et ses objets."""
from django.conf import settings
from django.contrib.gis.db import models

from geodata.models import Dataset

SRID = settings.GEORISKIN_SRID


class HydroRun(models.Model):
    """Un calcul complet : MNT d'entrée, paramètres, version du moteur, rapport."""

    mnt = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    parametres = models.JSONField()
    version_moteur = models.CharField(max_length=40)
    rapport = models.JSONField(default=dict, blank=True)
    actif = models.BooleanField(default=True, help_text="calcul servi par l'API")
    calcule_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Calcul hydrologique #{self.pk} ({self.mnt})"


class Watershed(models.Model):
    class Level(models.TextChoices):
        BASIN = "bassin", "Bassin versant (exutoire final)"
        SUBBASIN = "sous_bassin", "Sous-bassin (tronçon de réseau)"

    run = models.ForeignKey(HydroRun, on_delete=models.CASCADE, related_name="bassins")
    niveau = models.CharField(max_length=12, choices=Level.choices)
    code = models.CharField(max_length=20)
    nom = models.CharField(max_length=120, blank=True,
                           help_text="nom du cours d'eau ; proposé automatiquement à partir de la carte "
                                     "des cours d'eau fournie, à vérifier")
    nom_source = models.CharField(max_length=200, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="sous_bassins")
    superficie_km2 = models.FloatField()
    exutoire = models.PointField(srid=SRID)
    exutoire_type = models.CharField(max_length=60, blank=True)
    part_dans_province_pct = models.FloatField(null=True, blank=True)
    statistiques = models.JSONField(default=dict, blank=True,
                                    help_text="indicateurs calculés (ex. LS moyen, p90) avec leur méthode")
    geom = models.MultiPolygonField(srid=SRID)

    class Meta:
        ordering = ["run", "niveau", "-superficie_km2"]
        constraints = [models.UniqueConstraint(fields=["run", "niveau", "code"], name="bassin_unique")]
        verbose_name = "bassin versant"

    def __str__(self):
        return f"{self.code} {self.nom}".strip()


class StreamSegment(models.Model):
    run = models.ForeignKey(HydroRun, on_delete=models.CASCADE, related_name="troncons")
    id_troncon = models.BigIntegerField()
    nom = models.CharField(max_length=120, blank=True)
    ordre_strahler = models.PositiveSmallIntegerField()
    aire_drainee_km2 = models.FloatField()
    bassin = models.ForeignKey(Watershed, null=True, blank=True, on_delete=models.SET_NULL)
    geom = models.MultiLineStringField(srid=SRID)

    class Meta:
        verbose_name = "tronçon du réseau calculé"
