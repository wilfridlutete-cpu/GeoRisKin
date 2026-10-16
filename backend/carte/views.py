import json

from django.conf import settings
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalogue import couches, valeurs_au_point

PUBLIC_KEYS = ("id", "titre", "groupe", "type", "palette", "echelle", "min", "max", "unite", "statut",
               "source", "opacite", "visible", "classes", "requete")


def index(request):
    return render(request, "carte/index.html", {"tuiles_url": settings.GEORISKIN_TILES_URL})


class CouchesView(APIView):
    """Catalogue des couches raster : symbologie, unités, statut, source et modèle d'URL des tuiles."""

    def get(self, request):
        base = request.build_absolute_uri(settings.GEORISKIN_TILES_URL)
        data = []
        for c in couches():
            d = {k: c[k] for k in PUBLIC_KEYS if k in c}
            d["tuiles"] = f"{base}{c['id']}/{{z}}/{{x}}/{{y}}.png"
            leg = settings.GEORISKIN_TILES_DIR / c["id"] / "legende.json"
            d["legende"] = json.loads(leg.read_text(encoding="utf-8")) if leg.exists() else []
            data.append(d)
        relief = settings.GEORISKIN_TILES_DIR / "mnt_terrarium"
        return Response({"couches": data,
                         "relief3d": f"{base}mnt_terrarium/{{z}}/{{x}}/{{y}}.png" if relief.exists() else None})


class ValeursView(APIView):
    """Valeurs de toutes les couches au point ?lon=&lat= (WGS84)."""

    def get(self, request):
        try:
            lon = float(request.query_params["lon"])
            lat = float(request.query_params["lat"])
        except (KeyError, ValueError):
            return Response({"erreur": "paramètres lon et lat (degrés WGS84) requis"}, status=400)
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return Response({"erreur": "coordonnées hors limites"}, status=400)
        return Response({"lon": lon, "lat": lat, "valeurs": valeurs_au_point(lon, lat)})


class PratiquesView(APIView):
    """Table des pratiques de conservation (facteur P) avec valeurs, statut et sources."""

    def get(self, request):
        p = settings.PROJECT_ROOT / "parametres" / "table_p_pratiques.json"
        return Response(json.loads(p.read_text(encoding="utf-8")))
