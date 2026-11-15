from collections import defaultdict
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit

import psutil
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ._alarms import send_backup_alarm
from ._storage import delete_backup_files_matching_pattern, list_backup_files, upload_encrypted_backup


logger = logging.getLogger("backup_restore")


def _backup_dir():
    configured = getattr(settings, "BACKUPS_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "backups"


def _pg_dump_environment():
    env = os.environ.copy()
    database_url = (
        getattr(settings, "BACKUP_DATABASE_URL", None)
        or os.environ.get("DATABASE_URL")
        or getattr(settings, "DATABASE_URL", None)
    )
    if database_url:
        parsed = urlsplit(database_url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError("BACKUP_DATABASE_URL must be a PostgreSQL connection URL")
        env["PGHOST"] = parsed.hostname or ""
        if parsed.port:
            env["PGPORT"] = str(parsed.port)
        if parsed.username:
            env["PGUSER"] = unquote(parsed.username)
        if parsed.password:
            env["PGPASSWORD"] = unquote(parsed.password)
        if parsed.path.strip("/"):
            env["PGDATABASE"] = unquote(parsed.path.strip("/"))
        for name, value in parse_qsl(parsed.query, keep_blank_values=True):
            env[f"PG{name.upper()}"] = value
        return env

    alias = getattr(settings, "BACKUP_DATABASE_ALIAS", "default")
    database = settings.DATABASES.get(alias)
    if not database:
        raise ValueError(f"No Django database is configured for alias {alias!r}")
    if "postgresql" not in database.get("ENGINE", ""):
        raise ValueError(f"Database alias {alias!r} is not configured for PostgreSQL")

    values = {
        "PGDATABASE": database.get("NAME"),
        "PGHOST": database.get("HOST"),
        "PGPORT": database.get("PORT"),
        "PGUSER": database.get("USER"),
        "PGPASSWORD": database.get("PASSWORD"),
    }
    for name, value in values.items():
        if value not in (None, ""):
            env[name] = str(value)
    for name, value in database.get("OPTIONS", {}).items():
        env[f"PG{name.upper()}"] = str(value)
    return env


def _parse_backup_timestamp(filename):
    match = re.fullmatch(r"db_backup_(\d{14})\.pgsql(?:\.enc)?", filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Create an encrypted PostgreSQL backup and upload it to configured cloud storage"

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", type=str, help="Upload an existing PostgreSQL dump")

    @staticmethod
    def make_db_backup(file_path):
        subprocess.run(["pg_dump", "--file", str(file_path)], check=True, env=_pg_dump_environment())

    @staticmethod
    def get_filename():
        return f"db_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.pgsql"

    def handle(self, *args, **options):
        source_path = Path(options["file"]) if options["file"] else None
        errors = []

        if source_path is None:
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    staged_path = Path(temp_dir) / self.get_filename()
                    self.make_db_backup(staged_path)
                    if getattr(settings, "STORE_LOCAL_BACKUPS", True):
                        self._save_local_backup(staged_path, errors)
                    else:
                        logger.info("Local backup storage is disabled; skipping %s", staged_path.name)
                    self._upload_backup(staged_path, errors)
            except Exception as exc:
                logger.exception("PostgreSQL backup dump failed")
                send_backup_alarm(f"Database backup dump failed: {exc}")
                errors.append(f"database dump: {exc}")
        else:
            self._upload_backup(source_path, errors)

        try:
            self.cleanup_old_backups()
        except Exception:
            logger.exception("Backup cleanup failed")
        try:
            self.check_disk_usage()
        except Exception:
            logger.exception("Unable to check backup disk usage")

        if errors:
            raise CommandError("Backup completed with failures: " + "; ".join(errors))

    def _save_local_backup(self, source_path, errors):
        destination = _backup_dir() / source_path.name
        try:
            destination.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(source_path, destination)
            logger.info("Local PostgreSQL backup saved to %s", destination)
        except Exception as exc:
            logger.exception("Local PostgreSQL backup failed: %s", destination)
            send_backup_alarm(f"Local database backup failed: {exc}")
            errors.append(f"local backup: {exc}")

    def _upload_backup(self, source_path, errors):
        try:
            upload_encrypted_backup(source_path)
        except Exception as exc:
            provider = "Google Cloud Storage" if getattr(
                settings, "BACKUP_STORAGE_BACKEND", "google_drive"
            ).lower() in {"google_cloud_storage", "gcs"} else "Google Drive"
            logger.exception("%s backup failed for %s", provider, source_path)
            send_backup_alarm(f"{provider} backup failed: {exc}")
            errors.append(f"{provider} backup: {exc}")

    def cleanup_old_backups(self):
        retention_months = getattr(settings, "BACKUPS_RETENTION_MONTHS", 2)
        cutoff = datetime.now() - relativedelta(months=retention_months)
        backup_dir = _backup_dir()
        files = sorted(backup_dir.glob("db_backup_*.pgsql*")) if backup_dir.exists() else []
        monthly_keep = defaultdict(lambda: None)

        for path in files:
            timestamp = _parse_backup_timestamp(path.name)
            if timestamp is None:
                logger.warning("Skipping backup with unexpected filename format: %s", path.name)
                continue
            if timestamp.year < 2024:
                continue
            month_key = (timestamp.year, timestamp.month)
            if timestamp >= cutoff:
                if monthly_keep[month_key] is None:
                    monthly_keep[month_key] = path
            elif monthly_keep[month_key] is None:
                monthly_keep[month_key] = path
            else:
                logger.info("Deleting old local backup: %s", path)
                path.unlink()

        self._cleanup_old_remote_backups(cutoff)

    def _cleanup_old_remote_backups(self, cutoff):
        remote_backups = []
        for item in list_backup_files():
            filename = Path(item["name"]).name
            timestamp = _parse_backup_timestamp(filename)
            if timestamp is None:
                logger.warning("Skipping remote backup with unexpected filename format: %s", filename)
                continue
            remote_backups.append((timestamp, filename))

        monthly_keep = set()
        for timestamp, filename in sorted(remote_backups):
            if timestamp.year < 2024 or timestamp >= cutoff:
                continue
            month_key = (timestamp.year, timestamp.month)
            if month_key not in monthly_keep:
                monthly_keep.add(month_key)
                continue
            deleted = 0
            for deleted_count in delete_backup_files_matching_pattern(filename):
                deleted = deleted_count
            logger.info("Deleted %d remote backups matching %s", deleted, filename)

    def check_disk_usage(self):
        path = _backup_dir()
        while not path.exists() and path != path.parent:
            path = path.parent
        usage = psutil.disk_usage(str(path))
        threshold = getattr(settings, "DISK_USAGE_WARNING_THRESHOLD", 90)
        logger.info("Disk usage of %s is %s%%", path, usage.percent)
        if usage.percent >= threshold:
            message = f"The disk containing backups is {usage.percent}% full."
            logger.warning("Disk usage above %d%%: %s%%", threshold, usage.percent)
            send_backup_alarm(message)
