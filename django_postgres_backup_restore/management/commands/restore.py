from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ._encryption import decrypt_data
from ._storage import download_backup, list_backup_files


class Command(BaseCommand):
    help = "Download a PostgreSQL backup from configured remote storage and decrypt it"

    def add_arguments(self, parser):
        parser.add_argument("file_id", nargs="?", help="Drive file ID or GCS object name")
        parser.add_argument("--list", action="store_true", help="List available remote backups")

    def handle(self, *args, **options):
        if options["list"]:
            for item in list_backup_files():
                self.stdout.write(f"{item['id']} {item['name']}")
            return
        if not options["file_id"]:
            raise CommandError("Provide a backup identifier or use --list")

        backup_dir = Path(getattr(settings, "BACKUPS_DIR", Path(settings.BASE_DIR) / "backups"))
        backup_dir.mkdir(exist_ok=True, parents=True)
        filename, encrypted_data = download_backup(options["file_id"])
        filename = Path(filename).name
        destination = backup_dir / filename
        decrypt_data(encrypted_data, destination)
        self.stdout.write(f"Decrypted backup saved to {destination}")
        self.stdout.write("Restore it manually with psql or your PostgreSQL restore procedure.")
