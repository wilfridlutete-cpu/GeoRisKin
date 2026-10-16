"""Configuration Django de GeoRisKin.

Toutes les valeurs sensibles ou propres à l'installation viennent de variables
d'environnement (voir .env.example). Base de données : PostgreSQL + PostGIS.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent  # contient engine/, data/, scripts/

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-uniquement-a-changer")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework_gis",
    "django_filters",
    "geodata",
    "hydrology",
    "ravines",
    "carte",
    "scenarios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("POSTGRES_DB", "georiskin"),
        "USER": os.environ.get("POSTGRES_USER", "georiskin"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "georiskin"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

if os.environ.get("GDAL_LIBRARY_PATH"):
    GDAL_LIBRARY_PATH = os.environ["GDAL_LIBRARY_PATH"]
if os.environ.get("GEOS_LIBRARY_PATH"):
    GEOS_LIBRARY_PATH = os.environ["GEOS_LIBRARY_PATH"]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Données géographiques du projet (rasters sur disque, métadonnées en base)
GEORISKIN_DATA_DIR = Path(os.environ.get("GEORISKIN_DATA_DIR", PROJECT_ROOT / "data"))
GEORISKIN_SRID = 32733  # WGS 84 / UTM 33S, SCR de calcul de tout le projet

REST_FRAMEWORK = {
    # Consultation publique sans compte ; écriture réservée aux comptes authentifiés.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 200,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "scenarios": os.environ.get("GEORISKIN_SCENARIOS_RATE", "30/hour")},
}

# Tuiles raster de la carte web (générées par scripts/generer_tuiles.py).
# En production, les servir directement par Nginx et laisser GEORISKIN_SERVE_TILES=0.
GEORISKIN_TILES_DIR = Path(os.environ.get("GEORISKIN_TILES_DIR", GEORISKIN_DATA_DIR / "tuiles"))
GEORISKIN_TILES_URL = os.environ.get("GEORISKIN_TILES_URL", "/tuiles/")
GEORISKIN_SERVE_TILES = os.environ.get("GEORISKIN_SERVE_TILES", "1" if DEBUG else "0") == "1"
GEORISKIN_SCENARIOS_DIR = Path(os.environ.get("GEORISKIN_SCENARIOS_DIR", GEORISKIN_DATA_DIR / "scenarios"))
GEORISKIN_SCENARIOS_URL = os.environ.get("GEORISKIN_SCENARIOS_URL", "/scenarios-fichiers/")
GEORISKIN_SCENARIO_MAX_KM2 = float(os.environ.get("GEORISKIN_SCENARIO_MAX_KM2", "1000"))
