from django.core.management.base import BaseCommand

from ._storage import delete_backup_files_matching_pattern


class Command(BaseCommand):
    help = "Delete remote PostgreSQL backups whose filenames contain the supplied text"

    def add_arguments(self, parser):
        parser.add_argument("filename_pattern", help="Backup filename or substring to match")

    def handle(self, *args, **options):
        total = 0
        for total in delete_backup_files_matching_pattern(options["filename_pattern"]):
            self.stdout.write(f"{total} backup(s) deleted")
        if total == 0:
            self.stdout.write("No matching backups found.")
