import logging
from pathlib import Path, PurePosixPath
import tempfile

from django.conf import settings

from ._encryption import encrypt_text_file
from ._google_drive import (
    delete_files_matching_pattern as delete_drive_files_matching_pattern,
    google_drive_storage_quota,
    google_list_files,
    google_upload,
)


logger = logging.getLogger("backup_restore")


def backend():
    selected = getattr(settings, "BACKUP_STORAGE_BACKEND", "google_drive").strip().lower()
    selected = {"drive": "google_drive", "gcs": "google_cloud_storage"}.get(selected, selected)
    if selected not in {"google_drive", "google_cloud_storage"}:
        raise ValueError("BACKUP_STORAGE_BACKEND must be google_drive or google_cloud_storage")
    return selected


def _bucket():
    bucket_name = getattr(settings, "GOOGLE_CLOUD_STORAGE_BUCKET", "")
    if not bucket_name:
        raise ValueError(
            "GOOGLE_CLOUD_STORAGE_BUCKET is required when "
            "BACKUP_STORAGE_BACKEND=google_cloud_storage"
        )
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError(
            "Install django-postgres-backup-restore[gcs] to use Google Cloud Storage"
        ) from exc
    client = storage.Client(project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None))
    return client.bucket(bucket_name)


def _prefix():
    return getattr(settings, "GOOGLE_CLOUD_STORAGE_PREFIX", "Backups").strip("/")


def _object_name(filename):
    prefix = _prefix()
    return f"{prefix}/{filename}" if prefix else filename


def list_backup_files():
    if backend() == "google_drive":
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "size": item.get("size", 0),
                "created": item.get("createdTime"),
            }
            for item in google_list_files()
        ]

    bucket = _bucket()
    prefix = _prefix()
    if prefix:
        prefix += "/"
    return [
        {
            "id": blob.name,
            "name": PurePosixPath(blob.name).name,
            "display": blob.name,
            "size": blob.size or 0,
            "created": blob.time_created,
        }
        for blob in bucket.list_blobs(prefix=prefix)
        if blob.name and not blob.name.endswith("/")
    ]


def upload_encrypted_backup(source_path):
    source_path = Path(source_path)
    with tempfile.TemporaryDirectory() as temp_dir:
        encrypted_path = Path(temp_dir) / source_path.name
        encrypt_text_file(source_path, encrypted_path)
        if backend() == "google_drive":
            return google_upload(encrypted_path)

        bucket = _bucket()
        object_name = _object_name(encrypted_path.name)
        bucket.blob(object_name).upload_from_filename(
            str(encrypted_path),
            content_type="application/octet-stream",
            if_generation_match=0,
        )
        logger.info("Encrypted backup uploaded to gs://%s/%s", bucket.name, object_name)
        return object_name


def download_backup(identifier):
    if backend() == "google_drive":
        from ._google_drive import google_download

        return google_download(identifier)

    prefix = _prefix()
    if prefix and not identifier.startswith(f"{prefix}/"):
        raise ValueError(f"GCS backup identifier must be inside the configured prefix {prefix!r}")
    blob = _bucket().blob(identifier)
    return PurePosixPath(identifier).name, blob.download_as_bytes()


def delete_backup_files_matching_pattern(pattern):
    if backend() == "google_drive":
        yield from delete_drive_files_matching_pattern(pattern)
        return

    bucket = _bucket()
    prefix = _prefix()
    if prefix:
        prefix += "/"
    deleted = 0
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name and pattern in PurePosixPath(blob.name).name:
            logger.info("Deleting Google Cloud Storage backup gs://%s/%s", bucket.name, blob.name)
            blob.delete()
            deleted += 1
            yield deleted


def storage_usage(files=None):
    files = list_backup_files() if files is None else files
    used = sum(int(item.get("size", 0) or 0) for item in files)
    result = {
        "backend": backend(),
        "used": used,
        "account_used": None,
        "limit": None,
        "files": len(files),
        "location": None,
    }
    if result["backend"] == "google_drive":
        try:
            quota = google_drive_storage_quota()
            result["account_used"] = int(quota.get("usageInDrive", quota.get("usage", used)) or 0)
            result["limit"] = int(quota["limit"]) if quota.get("limit") else None
        except Exception as exc:
            result["quota_error"] = str(exc)
        result["location"] = "Google Drive backup folder"
    else:
        result["location"] = f"gs://{settings.GOOGLE_CLOUD_STORAGE_BUCKET}/{_prefix()}".rstrip("/")
    return result
