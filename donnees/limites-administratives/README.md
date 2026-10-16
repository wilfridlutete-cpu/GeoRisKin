# Limites administratives de Kinshasa (province, communes, quartiers)

**Producteur des géométries : CENI** (Commission électorale nationale indépendante, RDC), champ `source`
des fichiers d'origine. Fichiers transmis par l'URF-GRN.

**Conditions de réutilisation :** la CENI n'a pas indiqué de licence dans les fichiers. Leur republication
a été décidée le 16/10/2026 par l'URF-GRN (Prof. Fils Makanzu Imwangana), qui les considère comme librement
réutilisables. Ces fichiers ne sont donc **pas** couverts par la licence AGPL du code ni par la CC BY 4.0
des données URF-GRN. Toute demande de la CENI (citation, modification, retrait) sera suivie.

Citation proposée : *Limites des quartiers et communes de Kinshasa, CENI ; harmonisation GeoRisKin (2026),
via URF-GRN.*

## Contenu

| Fichier | Couches / contenu | SCR |
| --- | --- | --- |
| `limites_kinshasa.gpkg` | `province` (1), `communes` (24), `quartiers` (367) | UTM 33S (EPSG:32733) |
| `*_kinshasa_wgs84.geojson` | mêmes couches, un fichier par niveau | WGS 84 (EPSG:4326) |

Champs des quartiers : `quartier_id`, `nom`, `commune`, `commune_id`, `territoire`, `source`, `superficie_km2`.

## Traitements (scripts/phase1_build_dem.py)
- Reprojection en UTM 33S ; communes = union des quartiers par commune ; province = union de toutes les
  communes, trous < 0,1 km² comblés et parties < 0,05 km² supprimées.
- Correction d'orthographe : « Kinsenso » → « Kisenso ».
- **Champs retirés avant publication :** noms des chefs de quartier (données personnelles), nombre d'électeurs,
  nombre de bureaux, statistiques zonales sans documentation, antennes et pools CENI.

## Limites
Limites électorales, pas nécessairement les limites légales officielles ; précision de position non documentée.
