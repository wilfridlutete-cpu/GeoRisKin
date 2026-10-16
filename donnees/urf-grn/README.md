# Inventaire indicatif des ravines de Kinshasa (URF-GRN)

**Producteur : URF-GRN** · **Licence : [CC BY 4.0](LICENCE_CC-BY-4.0.txt)** (publication autorisée par le
professeur Fils Makanzu Imwangana le 16/10/2026).

Citation : *URF-GRN (2026). Inventaire indicatif des ravines de Kinshasa (Kisenso, Lemba). Licence CC BY 4.0.
Diffusé dans le dépôt GeoRisKin.*

## Contenu

| Fichier | Format | SCR |
| --- | --- | --- |
| `ravines_kinshasa_inventaire_indicatif.gpkg` (couche `ravines`) | GeoPackage | UTM 33S (EPSG:32733) |
| `ravines_kinshasa_inventaire_indicatif.geojson` | GeoJSON | WGS 84 (EPSG:4326) |

74 polygones de ravines : Kisenso (54), Lemba (20). Année renseignée pour 17 polygones (2010 : 16 ; 2004 : 1).

| Champ | Description |
| --- | --- |
| `nom` | nom de la ravine quand il est renseigné |
| `commune` | commune contenant la ravine (calculé) |
| `annee` | année de la cartographie, si connue |
| `longueur_m_attr`, `surface_m2_attr` | longueur et surface saisies dans les fichiers d'origine |
| `aire_calc_m2` | surface recalculée en UTM 33S |
| `statut_donnee` | `indicatif` : données de démonstration, non exhaustives |
| `fichier_origine` | fichier source (`erosions.shp`, `Export_Output_*.shp`) |

## Traitements appliqués (GeoRisKin, `scripts/phase1_build_dem.py`)
Fusion de `erosions.shp` et des `Export_Output_*.shp`, reprojection en UTM 33S, recalcul des surfaces,
rattachement à la commune. Aucune géométrie n'a été redessinée.

## Limites
Inventaire **indicatif et partiel** (deux communes), sans garantie d'exhaustivité ni de précision de position.
Il ne doit pas être utilisé comme carte des ravines de Kinshasa ni comme carte de risque.
