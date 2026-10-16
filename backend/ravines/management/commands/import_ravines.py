"""Importe une campagne d'inventaire de ravines.

Exemple :
    python manage.py import_ravines ravines_2026.gpkg --nom "Inventaire 2026 Kisenso" \
        --date 2026-09-30 --methode terrain --source "Équipe UNIKIN" --statut preliminaire \
        --champ-nom Noms --champ-longueur Long
"""
from django.core.management.base import BaseCommand, CommandError

from ravines.models import InventoryCampaign
from ravines.services import import_campaign, read_vector_file


class Command(BaseCommand):
    help = "Importe des polygones de ravines comme une nouvelle campagne datée"

    def add_arguments(self, p):
        p.add_argument("fichier")
        p.add_argument("--nom", required=True)
        p.add_argument("--date", help="AAAA-MM-JJ (omettre si inconnue)")
        p.add_argument("--methode", default="imagerie", choices=[c for c, _ in InventoryCampaign.Method.choices])
        p.add_argument("--source", required=True)
        p.add_argument("--statut", default="preliminaire",
                       choices=[c for c, _ in InventoryCampaign.Status.choices])
        p.add_argument("--tolerance", type=float, default=20.0, help="m, rattachement aux ravines existantes")
        p.add_argument("--champ-nom")
        p.add_argument("--champ-longueur")
        p.add_argument("--champ-largeur")
        p.add_argument("--champ-profondeur")
        p.add_argument("--profondeur-mesuree", action="store_true",
                       help="à cocher seulement si la profondeur a été mesurée sur le terrain")

    def handle(self, *a, **o):
        try:
            recs = read_vector_file(o["fichier"], {"nom": o["champ_nom"], "longueur_m": o["champ_longueur"],
                                                   "largeur_m": o["champ_largeur"],
                                                   "profondeur_m": o["champ_profondeur"]})
        except Exception as e:
            raise CommandError(str(e))
        for r in recs:
            r["profondeur_mesuree"] = o["profondeur_mesuree"] and r.get("profondeur_m") is not None
        camp, created = InventoryCampaign.objects.get_or_create(
            nom=o["nom"], defaults=dict(date_observation=o["date"], methode=o["methode"],
                                        source=o["source"], statut=o["statut"]))
        rep = import_campaign(recs, camp, o["tolerance"])
        self.stdout.write(self.style.SUCCESS(
            f"{rep.campagne} : {rep.lues} lues, {rep.importees} importées, "
            f"{rep.nouvelles_ravines} nouvelles ravines, {rep.rattachees} rattachées, "
            f"{len(rep.ignorees)} ignorées"))
        for i, why in rep.ignorees[:20]:
            self.stdout.write(f"  enregistrement {i} ignoré : {why}")
