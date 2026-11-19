import io
import logging
import os

from django.conf import settings
import google.auth
from google.auth import impersonated_credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build


from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


logger = logging.getLogger("backup_restore")


DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def google_authenticate():
    credentials_file = getattr(settings, "GOOGLE_CLIENT_SECRET_FILE", "")

    if not credentials_file:
        logger.debug("Authenticating to Google Drive using Application Default Credentials (ADC)")
        source_credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        service_account_email = getattr(source_credentials, "service_account_email", None)
        if not service_account_email or service_account_email == "default":
            # Resolve actual email from metadata server if needed
            import urllib.request
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                service_account_email = resp.read().decode().strip()

        credentials = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=service_account_email,
            target_scopes=DRIVE_SCOPES,
            lifetime=3600,
        )
    else:
        if not os.path.isfile(credentials_file):
            raise FileNotFoundError(
                f"GOOGLE_CLIENT_SECRET_FILE not found at: {credentials_file}"
            )
        logger.debug("Authenticating to Google Drive using credentials file %s", credentials_file)
        credentials = service_account.Credentials.from_service_account_file(
            credentials_file,
            scopes=DRIVE_SCOPES,
        )

    return build("drive", "v3", credentials=credentials)


def google_list_files(name_prefix="db_backup_"):
    service = google_authenticate()
    files = []
    page_token = None
    escaped_name_prefix = name_prefix.replace("\\", "\\\\").replace("'", "\'")
    while True:
        result = service.files().list(
            q=(
                f"'{settings.GOOGLE_BACKUPS_DIR}' in parents and "
                f"name contains '{escaped_name_prefix}'"
            ),
            pageSize=1000,
            pageToken=page_token,
            fields="nextPageToken, files(id, name, size, createdTime)",
        ).execute()
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return files


def google_drive_storage_quota():
    service = google_authenticate()
    result = service.about().get(fields="storageQuota").execute()
    return result.get("storageQuota", {})


def google_upload(file_path):
    service = google_authenticate()
    metadata = {"name": file_path.name, "parents": [settings.GOOGLE_BACKUPS_DIR]}
    media = MediaFileUpload(str(file_path), mimetype="application/octet-stream")
    result = service.files().create(body=metadata, media_body=media, fields="id").execute()
    file_id = result.get("id")
    logger.info("Encrypted backup uploaded to Google Drive (file ID %s)", file_id)
    return file_id


def google_download(file_id):
    service = google_authenticate()
    metadata = service.files().get(fileId=file_id).execute()
    filename = metadata["name"]
    request = service.files().get_media(fileId=file_id)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        logger.debug("Google Drive download progress: %s", status.progress())
    return filename, output.getvalue()


def delete_files_matching_pattern(pattern):
    service = google_authenticate()
    query = f"name contains '{pattern}' and '{settings.GOOGLE_BACKUPS_DIR}' in parents"
    deleted = 0
    while True:
        results = service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id, name)",
        ).execute()
        items = results.get("files", [])
        if not items:
            break
        for item in items:
            logger.info("Deleting Google Drive backup %s (ID %s)", item["name"], item["id"])
            service.files().delete(fileId=item["id"]).execute()
            deleted += 1
            yield deleted
