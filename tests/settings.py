from pathlib import Path

SECRET_KEY = "test-only-key"
BASE_DIR = Path(__file__).resolve().parent
INSTALLED_APPS = ["django_postgres_backup_restore"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "test_db",
        "USER": "test_user",
        "PASSWORD": "test_password",
        "HOST": "db.example.test",
        "PORT": "5432",
    }
}
BACKUP_STORAGE_BACKEND = "google_drive"
GOOGLE_CLIENT_SECRET_FILE = "unused-in-unit-tests.json"
GOOGLE_BACKUPS_DIR = "drive-folder-id"
GOOGLE_CLOUD_STORAGE_BUCKET = "gcs-test-bucket"
GOOGLE_CLOUD_STORAGE_PREFIX = "Backups"
BACKUPS_DIR = BASE_DIR / "backups"
BACKUP_ENCRYPTION_KEY = b"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
STORE_LOCAL_BACKUPS = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
