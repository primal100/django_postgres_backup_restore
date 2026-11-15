from django.apps import AppConfig


class DjangoPostgresBackupRestoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_postgres_backup_restore"
    verbose_name = "PostgreSQL backup and restore"
