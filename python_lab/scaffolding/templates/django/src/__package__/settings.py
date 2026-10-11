"""Local development settings; no database, keys or external services."""

SECRET_KEY = "local-development-only-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
ROOT_URLCONF = "__package__.main"
INSTALLED_APPS = []
MIDDLEWARE = []
