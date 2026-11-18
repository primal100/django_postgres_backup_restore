from datetime import datetime
from pathlib import PurePosixPath
import re

from django.core.management.base import BaseCommand, CommandError

from ._storage import list_backup_files


BACKUP_NAME_RE = re.compile(r"^db_backup_(\d{14})\.pgsql(?:\.enc)?$")


class Command(BaseCommand):
    help = "List remote PostgreSQL backups between two dates (YYYYMMDD, inclusive)"

    def add_arguments(self, parser):
        parser.add_argument("start_date", help="First backup date, YYYYMMDD")
        parser.add_argument("end_date", help="Last backup date, YYYYMMDD")

    def handle(self, *args, **options):
        try:
            if not re.fullmatch(r"\d{8}", options["start_date"]):
                raise ValueError("invalid start date")
            if not re.fullmatch(r"\d{8}", options["end_date"]):
                raise ValueError("invalid end date")
            start_date = datetime.strptime(options["start_date"], "%Y%m%d").date()
            end_date = datetime.strptime(options["end_date"], "%Y%m%d").date()
        except ValueError as exc:
            raise CommandError("Dates must be valid calendar dates in YYYYMMDD format.") from exc
        if start_date > end_date:
            raise CommandError("The start date must be on or before the end date.")

        matches = []
        for item in list_backup_files(start_date=start_date, end_date=end_date):
            filename = PurePosixPath(item["name"]).name
            match = BACKUP_NAME_RE.fullmatch(filename)
            if not match:
                continue
            try:
                timestamp = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            if start_date <= timestamp.date() <= end_date:
                matches.append((timestamp, item))

        for _, item in sorted(matches, key=lambda row: row[0]):
            filename = PurePosixPath(item["name"]).name
            label = item.get("display") or f"Backups/{filename}"
            if item.get("id") and item["id"] != item["name"]:
                label += f" ({item['id']})"
            self.stdout.write(label)
        if not matches:
            self.stdout.write("No backups found in that date range.")
