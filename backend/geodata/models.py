"""Catalogue des données et découpage administratif.

Chaque jeu de données est tracé : source, licence, SCR, résolution, unités et
statut (observé, calculé, hypothèse, indicatif). Les rasters restent sur disque ;
seules leurs métadonnées et leur emprise sont en base.
"""
from django.conf import settings
from django.contrib.gis.db import models

SRID = settings.GEORISKIN_SRID


class Dataset(models.Model):
    class Kind(models.TextChoices):
        RASTER = "raster", "Raster"
        VECTOR = "vecteur", "Vecteur"
        TABLE = "tableau", "Tableau"
        DOCUMENT = "document", "Document"

    class Status(models.TextChoices):
        OBSERVED = "observe", "Observé / mesuré"
        DERIVED = "calcule", "Calculé"
        ASSUMPTION = "hypothese", "Hypothèse"
        INDICATIVE = "indicatif", "Indicatif (démonstration)"

    nom = models.CharField(max_length=200, unique=True)
    type = models.CharField(max_length=10, choices=Kind.choices)
    statut = models.CharField(max_length=10, choices=Status.choices)
    source = models.CharField(max_length=300)
    licence = models.CharField(max_length=200, blank=True)
    scr = models.CharField("SCR", max_length=50, blank=True)
    resolution_m = models.FloatField(null=True, blank=True)
    unites = models.CharField(max_length=50, blank=True)
    date_donnee = models.DateField(null=True, blank=True)
    fichier = models.CharField(max_length=500, blank=True, help_text="chemin relatif à GEORISKIN_DATA_DIR")
    description = models.TextField(blank=True)
    limites_connues = models.TextField(blank=True)
    emprise = models.PolygonField(srid=SRID, null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "jeu de données"

    def __str__(self):
        return self.nom


class AdministrativeUnit(models.Model):
    class Level(models.TextChoices):
        PROVINCE = "province", "Ville-province"
        COMMUNE = "commune", "Commune"
        QUARTIER = "quartier", "Quartier"

    niveau = models.CharField(max_length=10, choices=Level.choices)
    nom = models.CharField(max_length=120)
    code = models.CharField(max_length=40, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="enfants")
    superficie_km2 = models.FloatField()
    source = models.ForeignKey(Dataset, null=True, blank=True, on_delete=models.SET_NULL)
    statistiques = models.JSONField(default=dict, blank=True,
                                    help_text="indicateurs calculés (ex. LS moyen, p90) avec leur méthode")
    geom = models.MultiPolygonField(srid=SRID)

    class Meta:
        ordering = ["niveau", "nom"]
        constraints = [models.UniqueConstraint(fields=["niveau", "nom", "parent"], name="unite_unique")]
        verbose_name = "unité administrative"

    def __str__(self):
        return f"{self.get_niveau_display()} {self.nom}"


class TerrainProduct(models.Model):
    """Raster dérivé du MNT (pente, exposition, aire drainée…), avec ses paramètres."""

    nom = models.CharField(max_length=100)
    variable = models.CharField(max_length=50)
    unites = models.CharField(max_length=30)
    methode = models.CharField(max_length=200)
    fichier = models.CharField(max_length=500)
    resolution_m = models.FloatField()
    mnt_source = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="produits")
    parametres = models.JSONField(default=dict, blank=True)
    version_moteur = models.CharField(max_length=40)
    calcule_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["variable"]
        verbose_name = "produit topographique"

    def __str__(self):
        return f"{self.variable} ({self.resolution_m:g} m)"
