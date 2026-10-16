# GeoRisKin — érosion et hydrologie de Kinshasa

Plateforme libre d'analyse de la topographie, des bassins versants et de l'érosion des sols à Kinshasa (RDC) :
MNT 30 m, réseau et bassins versants nommés, facteurs RUSLE (R, K, LS, C, P), carte de perte de sol avec
incertitude, carte web MapLibre et simulateur de scénarios (reboisement, urbanisation, haies, fascines, pluie).

> **Statut : prototype de recherche.** Les pertes de sol sont des estimations non validées (facteurs
> empiriques non calés à Kinshasa). RUSLE ne représente pas les ravines ; ce n'est pas une carte de risque.

Licence du code : **GNU AGPL-3.0** (voir `LICENSE`). Données : voir `DONNEES.md` (non incluses dans le dépôt).

Moteur scientifique Python (indépendant du web) + backend Django/GeoDjango/PostGIS.
Zone d'étude : toute la ville-province de Kinshasa (24 communes, 10 394 km²).

## Arborescence

```
georiskin/
├── engine/                     # moteur scientifique, sans Django
│   ├── raster_io.py            # géoréférencement DTED, mosaïque, reprojection, contrôle qualité
│   ├── terrain_metrics.py      # pente, exposition, ombrage, courbures, courbes de niveau
│   └── flow_analysis.py        # masque d'eau, Priority-Flood, D8, accumulation, Strahler, bassins
├── scripts/
│   ├── phase1_build_dem.py     # MNT + limites + ravines harmonisées (UTM 33S)
│   ├── phase2_topo_hydro.py    # rasters topographiques + réseau + bassins + courbes de niveau
│   └── phase2_validation_figures.py  # réseau calculé vs rivières digitalisées, figures
├── backend/                    # Django : config/, geodata/, hydrology/, ravines/
├── tests/                      # tests du moteur (pytest, rasters synthétiques)
├── data/raw | interim | processed
├── outputs/                    # rapports JSON et figures
├── Dockerfile, docker-compose.yml, requirements.txt
```

## Installation (Ubuntu / WSL)

```bash
sudo apt install gdal-bin libgdal-dev libgeos-dev libproj-dev postgresql postgis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo -u postgres psql -c "CREATE ROLE georiskin LOGIN PASSWORD 'georiskin';" \
  -c "CREATE DATABASE georiskin OWNER georiskin;"
sudo -u postgres psql -d georiskin -c "CREATE EXTENSION postgis;"
```

## Chaîne de calcul

```bash
python scripts/phase1_build_dem.py            # ≈ 30 s
python scripts/phase2_topo_hydro.py           # ≈ 4 min à 30 m, ≈ 5,8 Go de RAM au pic (8 Go conseillés)
python scripts/phase2_validation_figures.py
python scripts/nommer_cours_eau.py           # noms des cours d'eau depuis la carte fournie
python scripts/phase3_ls.py                   # facteur LS RUSLE (≈ 45 s)
python scripts/phase3_figures.py
python -m pytest -q tests                     # 23 tests
```

Paramètres de la phase 2 : `--stream-km2` (seuil du réseau, 1 km²), `--subbasin-km2` (2 km²),
`--contour-m` (10 m), `--water-min-km2` (0,5 km²).

## Données R, K, C (sur un ordinateur connecté à Internet)

```bash
python scripts/telecharger_donnees_rkc.py --soilgrids --worldcover   # sols 250 m + occupation du sol 10 m
python scripts/telecharger_donnees_rkc.py --chirps 2001 2020         # pluies journalières (volumineux)
```

## Backend Django

```bash
cd backend
python manage.py migrate
python manage.py load_georiskin --reset       # charge limites, bassins, réseau, ravines indicatives
python manage.py createsuperuser
python manage.py runserver                    # http://127.0.0.1:8000/api/v1/  et /admin/
python manage.py test                         # 7 tests (PostGIS requis)
```

### Ajouter une nouvelle campagne de ravines (mise à jour de l'inventaire)

```bash
python manage.py import_ravines ravines_2026.gpkg --nom "Inventaire 2026" --date 2026-09-30 \
   --methode terrain --source "Équipe X" --statut preliminaire \
   --champ-nom Noms --champ-longueur Long --champ-profondeur Prof --profondeur-mesuree
```

Chaque polygone est rattaché à une ravine existante s'il est à moins de `--tolerance` m (20 m par
défaut) de sa dernière observation, sinon une nouvelle ravine est créée. L'historique des surfaces
par campagne est servi par `GET /api/v1/ravines/{id}/`.

### API (lecture publique, écriture authentifiée ; GeoJSON en WGS84)

| Endpoint | Contenu |
| --- | --- |
| `/api/v1/datasets/` | catalogue des données |
| `/api/v1/unites-administratives/?niveau=commune` | province, communes, quartiers |
| `/api/v1/produits-topographiques/` | rasters dérivés (pente, aire drainée…) |
| `/api/v1/bassins/?niveau=bassin&simplifier=60` | bassins / sous-bassins du calcul actif |
| `/api/v1/bassins/au-point/?lon=15.33&lat=-4.41` | bassins contenant un point |
| `/api/v1/reseau/?ordre_strahler__gte=3` | réseau calculé |
| `/api/v1/campagnes/`, `/api/v1/ravines/`, `/api/v1/observations-ravines/` | inventaire versionné |

`?in_bbox=lon_min,lat_min,lon_max,lat_max` filtre par emprise ; `?simplifier=<m>` allège les géométries.

## Chaîne R, K, C et RUSLE (phase 3–4)

```bash
python scripts/occupation_sol.py              # WorldCover 10 m -> fractions 30 m
python scripts/facteur_k.py                   # SoilGrids 0-5 cm -> K (Williams)
python scripts/facteur_c.py                   # table parametres/table_c_worldcover.json -> C (bas/central/haut)
python scripts/facteur_r.py                   # CHIRPS mensuel (data/raw/chirps/) -> R (3 formules, 3 périodes)
python scripts/indicateur_ruissellement_urbain.py
python scripts/phase4_rusle.py                # ensemble de 18 hypothèses -> perte de sol médiane, P10, P90
```

Pluies CHIRPS : `scripts/utilisateur/chirps_kinshasa.py` (à lancer sur un poste connecté, produit un seul GeoTIFF mensuel).

## Carte web (MapLibre GL JS 4.7.1, servie par Django)

```bash
python scripts/generer_tuiles.py              # tuiles PNG z8–z13 de toutes les couches (≈ 15 min, ≈ 1,3 Go)
python scripts/generer_tuiles.py perte k      # seulement certaines couches
python scripts/generer_tuiles.py --relief3d   # tuiles d'élévation « terrarium » pour le relief 3D
python scripts/generer_tuiles.py --legendes   # seulement les légendes
cd backend && python manage.py load_georiskin --reset && python manage.py runserver
# -> http://127.0.0.1:8000/
```

- Symbologie, unités, sources et statut des couches : `parametres/couches.json` (catalogue unique).
- API : `/api/v1/couches/` (catalogue + légendes + URL des tuiles), `/api/v1/valeurs/?lon=&lat=` (valeurs au point).
- MapLibre est inclus localement (`carte/static/carte/vendor/`, licence BSD-3) : la carte fonctionne sans CDN.
  Seul le fond OpenStreetMap (désactivable) nécessite Internet.
- Production : servir `data/tuiles/` directement par Nginx (`location /tuiles/ { alias /chemin/data/tuiles/; expires 30d; }`)
  et mettre `GEORISKIN_SERVE_TILES=0`.

## Scénarios (phase 6)

Dans la carte : cliquer un bassin, un sous-bassin ou une commune → « Utiliser comme zone du scénario »,
choisir la pluie (1991–2020, 2011–2025, 1991–2025), un reboisement et/ou une urbanisation (part des classes
converties) et/ou une pratique (haies vives, bandes enherbées, terrasses/courbes de niveau, fascines), puis « Calculer ».

- API : `POST /api/v1/scenarios/` avec `bassin_id`, `unite_id` ou `zone_geojson` (WGS84) et `parametres` ;
  `GET /api/v1/scenarios/{id}/` ; `GET /api/v1/pratiques/` (table P avec sources).
- Calcul synchrone, zones ≤ 1000 km² (`GEORISKIN_SCENARIO_MAX_KM2`), 30 scénarios/heure par visiteur anonyme
  (`GEORISKIN_SCENARIOS_RATE`).
- Comparaison membre à membre : 18 hypothèses (3 R × 3 C × 2 LS), × 3 valeurs de P si une pratique est choisie.
- Valeurs de P : `parametres/table_p_pratiques.json` (fascines = hypothèse, aucune valeur publiée trouvée).
- Urbanisation : les cellules qui deviennent bâties sortent du domaine RUSLE ; la surface imperméable ajoutée
  est propagée vers l'aval (linéaire de réseau recevant ≥ 1 ha de plus).
- Résultats : `data/scenarios/<id>/` (PNG + GeoTIFF de différence).

## Limites connues

- MNT à 30 m : 4 tuiles SRTM DTED2 1" (OSFAC) + tuile Copernicus GLO-30 S04 E015 pour le nord de
  Maluku (autre capteur et géoïde EGM2008 ; biais de +0,4 m au raccord). Les deux sont des modèles
  de surface (bâti, végétation). Placer les tuiles dans data/raw/srtm_dted2/ (.DT2, .tif ou .hgt) ;
  sans elles, la chaîne se replie sur les vues réduites .ovr à 60 m.
- Le fleuve Congo est tracé comme le chemin D8 descendant depuis les biefs aplanis du SRTM
  (hypothèse, à remplacer par une couche hydrographique officielle).
- En plaine et en ville, D8 sur MNT ne représente pas les caniveaux, collecteurs ni le bâti.
- Les noms des bassins ne sont pas déduits automatiquement (champ `nom` à remplir dans l'admin).
- Docker : fichiers fournis mais non testés dans l'environnement de développement.
