# Données de GeoRisKin

Le dépôt contient **le code, les paramètres et la documentation**, pas les données. Les données sont
soit volumineuses (rasters, tuiles), soit soumises à l'accord de leurs auteurs. Placez-les dans `data/`
(ou `GEORISKIN_DATA_DIR`) selon l'arborescence attendue par les scripts.

## Données ouvertes (téléchargeables par chacun)

| Donnée | Source | Licence | Où la placer |
| --- | --- | --- | --- |
| MNT SRTM 1" (DTED2) | NASA/NGA, tuiles fournies par OSFAC | domaine public | `data/raw/srtm_dted2/` |
| MNT Copernicus GLO-30, tuile S04 E015 | ESA / Copernicus | licence Copernicus DEM (attribution) | `data/raw/srtm_dted2/` |
| Occupation du sol WorldCover 2021 v200 (tuile S06E015) | ESA | CC BY 4.0 | `data/raw/worldcover/` |
| SoilGrids 2.0, sable/limon/argile/carbone 0–5 cm | ISRIC | CC BY 4.0 | `data/raw/soilgrids/` |
| Pluie CHIRPS 2.0 mensuelle | UCSB Climate Hazards Center | domaine public | `data/raw/chirps/` (via `scripts/utilisateur/chirps_kinshasa.py`) |
| Carte géologique Léopoldville S.5/15 (1963) | Service géologique / MRAC | à vérifier | `data/raw/geologie/` |

Scripts d'aide : `scripts/telecharger_donnees_rkc.py`, `scripts/utilisateur/chirps_kinshasa.py`.

## Données URF-GRN publiées dans ce dépôt (CC BY 4.0)

- `donnees/urf-grn/` : inventaire indicatif des ravines (Kisenso, Lemba), producteur **URF-GRN**, licence
  CC BY 4.0 (accord du professeur Fils Makanzu Imwangana, 16/10/2026). Voir `donnees/urf-grn/README.md`.
- Chargement dans l'application : `python manage.py import_ravines donnees/urf-grn/ravines_kinshasa_inventaire_indicatif.gpkg ...`

## Limites administratives publiées (source CENI)

- `donnees/limites-administratives/` : province, 24 communes, 367 quartiers (géométries CENI, transmises par
  l'URF-GRN, republication décidée par le Prof. Fils Makanzu le 16/10/2026). Noms des chefs de quartier et
  données électorales retirés. Voir `donnees/limites-administratives/README.md` pour les conditions.

## Données non publiées

- Carte des cours d'eau utilisée pour nommer le réseau, mémoires et cartes scannées.

## Produits dérivés

Les rasters calculés (pente, LS, K, C, R, pertes de sol) et les tuiles de la carte se régénèrent avec les
scripts (voir README). Ils pourront être publiés séparément (archive versionnée avec DOI, par ex. Zenodo),
avec les attributions des sources ci-dessus.
