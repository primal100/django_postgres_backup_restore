from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from cryptography.fernet import Fernet

from django_postgres_backup_restore.management.commands import _google_drive
from django_postgres_backup_restore.management.commands import _storage
from django_postgres_backup_restore.management.commands.list_backups import Command as ListBackupsCommand
from django_postgres_backup_restore.management.commands.backup import (
    Command as BackupCommand,
    _pg_dump_environment,
)


class BackupStorageTests(SimpleTestCase):
    def _write_encrypted_bytes(self, source_path, destination_path):
        Path(destination_path).write_bytes(b"encrypted backup")

    @override_settings(BACKUP_STORAGE_BACKEND="google_drive")
    @patch("django_postgres_backup_restore.management.commands._storage.google_upload")
    @patch("django_postgres_backup_restore.management.commands._storage.encrypt_text_file")
    def test_drive_remains_default_upload_backend(self, encrypt_file, upload):
        upload.return_value = "drive-file-id"
        encrypt_file.side_effect = self._write_encrypted_bytes
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "db_backup_20260601220004.pgsql"
            source.write_text("database dump", encoding="utf-8")
            result = _storage.upload_encrypted_backup(source)
        self.assertEqual(result, "drive-file-id")
        upload.assert_called_once()
        self.assertEqual(encrypt_file.call_args.args[0], source)

    @override_settings(
        BACKUP_STORAGE_BACKEND="google_cloud_storage",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    @patch("django_postgres_backup_restore.management.commands._storage.encrypt_text_file")
    def test_upload_encrypts_to_gcs_prefix_without_overwriting(self, encrypt_file, get_bucket):
        bucket = Mock()
        bucket.name = "db-backups"
        blob = bucket.blob.return_value
        get_bucket.return_value = bucket
        encrypt_file.side_effect = self._write_encrypted_bytes
        uploaded_bytes = []
        blob.upload_from_filename.side_effect = lambda filename, **kwargs: uploaded_bytes.append(
            Path(filename).read_bytes()
        )

        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "db_backup_20260601220004.pgsql"
            source.write_text("database dump", encoding="utf-8")
            result = _storage.upload_encrypted_backup(source)

        self.assertEqual(result, "Backups/db_backup_20260601220004.pgsql")
        bucket.blob.assert_called_once_with(result)
        self.assertEqual(uploaded_bytes, [b"encrypted backup"])
        self.assertEqual(blob.upload_from_filename.call_args.kwargs["if_generation_match"], 0)

    @override_settings(
        BACKUP_STORAGE_BACKEND="gcs",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    def test_lists_gcs_objects_with_metadata(self, get_bucket):
        created = datetime(2026, 6, 1, 22, 0, 4)
        blob = SimpleNamespace(
            name="Backups/db_backup_20260601220004.pgsql",
            size=321,
            time_created=created,
        )
        bucket = Mock()
        bucket.list_blobs.return_value = [blob]
        get_bucket.return_value = bucket

        files = _storage.list_backup_files()

        bucket.list_blobs.assert_called_once_with(prefix="Backups/")
        self.assertEqual(files[0]["name"], "db_backup_20260601220004.pgsql")
        self.assertEqual(files[0]["size"], 321)
        self.assertEqual(files[0]["created"], created)

    @override_settings(
        BACKUP_STORAGE_BACKEND="google_cloud_storage",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    def test_lists_gcs_objects_with_inclusive_date_bounds(self, get_bucket):
        bucket = Mock()
        bucket.list_blobs.return_value = []
        get_bucket.return_value = bucket

        _storage.list_backup_files(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31))

        bucket.list_blobs.assert_called_once_with(
            prefix="Backups/",
            start_offset="Backups/db_backup_20260501",
            end_offset="Backups/db_backup_20260601",
        )

    @override_settings(BACKUP_STORAGE_BACKEND="google_drive", GOOGLE_BACKUPS_DIR="drive-folder")
    @patch("django_postgres_backup_restore.management.commands._google_drive.google_authenticate")
    def test_drive_listing_queries_only_backup_filename_prefix(self, authenticate):
        service = Mock()
        authenticate.return_value = service
        service.files.return_value.list.return_value.execute.return_value = {"files": []}

        _google_drive.google_list_files()

        query = service.files.return_value.list.call_args.kwargs["q"]
        self.assertEqual(
            query,
            "'drive-folder' in parents and name contains 'db_backup_'",
        )

    @patch("django_postgres_backup_restore.management.commands.list_backups.list_backup_files")
    def test_list_backups_passes_date_range_to_storage(self, list_files):
        list_files.return_value = []
        command = ListBackupsCommand()

        command.handle(start_date="20260501", end_date="20260531")

        list_files.assert_called_once_with(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
        )

    @override_settings(
        BACKUP_STORAGE_BACKEND="google_cloud_storage",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    def test_deletes_matching_gcs_backup_names(self, get_bucket):
        match = Mock()
        match.name = "Backups/db_backup_20240101000000.pgsql"
        other = Mock()
        other.name = "Backups/db_backup_20240201000000.pgsql"
        bucket = Mock()
        bucket.list_blobs.return_value = [match, other]
        get_bucket.return_value = bucket

        self.assertEqual(list(_storage.delete_backup_files_matching_pattern("20240101")), [1])
        match.delete.assert_called_once_with()
        other.delete.assert_not_called()

    @override_settings(
        BACKUP_STORAGE_BACKEND="google_cloud_storage",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    def test_downloads_gcs_backup(self, get_bucket):
        bucket = Mock()
        bucket.blob.return_value.download_as_bytes.return_value = b"encrypted backup"
        get_bucket.return_value = bucket

        self.assertEqual(
            _storage.download_backup("Backups/db_backup_20260601220004.pgsql"),
            ("db_backup_20260601220004.pgsql", b"encrypted backup"),
        )

    @override_settings(
        BACKUP_STORAGE_BACKEND="google_cloud_storage",
        GOOGLE_CLOUD_STORAGE_BUCKET="db-backups",
        GOOGLE_CLOUD_STORAGE_PREFIX="Backups",
    )
    @patch("django_postgres_backup_restore.management.commands._storage._bucket")
    def test_rejects_gcs_restore_outside_configured_prefix(self, get_bucket):
        with self.assertRaisesRegex(ValueError, "inside the configured prefix"):
            _storage.download_backup("Elsewhere/db_backup_20260601220004.pgsql")
        get_bucket.assert_not_called()

    @override_settings(BACKUP_STORAGE_BACKEND="google_cloud_storage", GOOGLE_CLOUD_STORAGE_BUCKET="")
    def test_gcs_requires_a_bucket(self):
        with self.assertRaisesRegex(ValueError, "GOOGLE_CLOUD_STORAGE_BUCKET is required"):
            _storage._bucket()

    @override_settings(BACKUP_STORAGE_BACKEND="google_cloud_storage")
    @patch("django_postgres_backup_restore.management.commands.backup.list_backup_files")
    @patch("django_postgres_backup_restore.management.commands.backup.delete_backup_files_matching_pattern")
    def test_retention_preserves_pre_2024_and_cleans_old_month_duplicates(
        self, delete_backups, list_backups
    ):
        list_backups.return_value = [
            {"name": "db_backup_20200101000000.pgsql"},
            {"name": "db_backup_20230101000000.pgsql"},
            {"name": "db_backup_20240101000000.pgsql"},
            {"name": "db_backup_20240115000000.pgsql"},
            {"name": "db_backup_20260601000000.pgsql"},
        ]
        delete_backups.side_effect = lambda filename: iter([1])

        BackupCommand()._cleanup_old_remote_backups(datetime(2026, 1, 1))

        list_backups.assert_called_once_with()
        delete_backups.assert_called_once_with("db_backup_20240115000000.pgsql")

    @override_settings(
        BACKUP_DATABASE_ALIAS="default",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "app_db",
                "USER": "backup_user",
                "PASSWORD": "example-secret",
                "HOST": "db.example.test",
                "PORT": "5433",
                "OPTIONS": {"sslmode": "require"},
            }
        },
    )
    @patch.dict("os.environ", {"DATABASE_URL": ""})
    def test_pg_dump_uses_django_postgresql_database_settings(self):
        environment = _pg_dump_environment()
        self.assertEqual(environment["PGDATABASE"], "app_db")
        self.assertEqual(environment["PGUSER"], "backup_user")
        self.assertEqual(environment["PGPASSWORD"], "example-secret")
        self.assertEqual(environment["PGHOST"], "db.example.test")
        self.assertEqual(environment["PGPORT"], "5433")
        self.assertEqual(environment["PGSSLMODE"], "require")

    def test_encryption_round_trip(self):
        from django_postgres_backup_restore.management.commands._encryption import (
            decrypt_data,
            encrypt_text_file,
        )

        key = Fernet.generate_key()
        with override_settings(BACKUP_ENCRYPTION_KEY=key), TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "plain.pgsql"
            encrypted = Path(temp_dir) / "encrypted.pgsql"
            decrypted = Path(temp_dir) / "restored.pgsql"
            source.write_bytes(b"plain postgres dump\x00\x01")
            encrypt_text_file(source, encrypted)
            self.assertNotEqual(source.read_bytes(), encrypted.read_bytes())
            decrypt_data(encrypted.read_bytes(), decrypted)
            self.assertEqual(decrypted.read_bytes(), source.read_bytes())
