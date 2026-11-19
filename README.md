# django-postgres-backup-restore

Django management commands for encrypted PostgreSQL backups. The app can keep a
local copy and upload encrypted dumps to Google Drive or Google Cloud Storage.
It also lists, prunes, downloads, and decrypts those backups for manual restore.

The commands are `backup`, `list_backups`, `delete_backups`, and `restore`.

## Install

The package is hosted in the private Artifact Registry virtual repository
**python-virtual**. Use an account with Artifact Registry Reader access and
authenticate with Application Default Credentials before installing:

~~~powershell
gcloud auth application-default login
python -m pip install "keyrings.google-artifactregistry-auth>=1.1"
python -m pip install --index-url "https://us-central1-python.pkg.dev/<PROJECT_ID>/python-virtual/simple/" django-postgres-backup-restore
~~~

For Google Cloud Storage, install the GCS extra from the same repository:

~~~powershell
python -m pip install --index-url "https://us-central1-python.pkg.dev/<PROJECT_ID>/python-virtual/simple/" "django-postgres-backup-restore[gcs]"
~~~

On a service or build agent, use a service account through
**GOOGLE_APPLICATION_CREDENTIALS** instead of running the interactive gcloud
login command. Do not put credentials in the repository.

Add the app to **INSTALLED_APPS**:

~~~python
INSTALLED_APPS = [
    # ...
    "django_postgres_backup_restore",
]
~~~

The pg_dump executable from a PostgreSQL client installation must be on the
server's PATH.

## Settings

Set these in the Django process environment or your deployment configuration.
The package does not load `.env` files automatically.

| Setting | Default | Purpose |
| --- | --- | --- |
| `BACKUP_STORAGE_BACKEND` | `google_drive` | `google_drive` or `google_cloud_storage` (`drive` and `gcs` aliases are accepted). |
| `BACKUPS_DIR` | `<BASE_DIR>/backups` | Local backup and decrypted restore directory. |
| `BACKUP_ENCRYPTION_KEY` | required | Persistent Fernet key used before upload and when restoring. |
| `STORE_LOCAL_BACKUPS` | `true` | Keep a local copy of newly generated dumps. |
| `BACKUP_DATABASE_ALIAS` | `default` | Django `DATABASES` alias to pass to `pg_dump`. |
| `BACKUP_DATABASE_URL` | unset | Optional PostgreSQL connection URL; `DATABASE_URL` is also recognized. If unset, connection values come from the selected Django database. |
| `BACKUPS_RETENTION_MONTHS` | `2` | Recent-backup retention window. Older backups from 2024 onward are reduced to one per month; backups before 2024 are left untouched. |
| `DISK_USAGE_WARNING_THRESHOLD` | `90` | Disk usage percentage that triggers a backup alarm. |
| `BACKUP_ALARM_FUNCTION` | unset | Optional dotted Python path for a callback accepting `severity="Critical"` and `text=...`. |

### Encryption key

Generate the key once and keep it in a secrets manager or protected environment
file. Losing it means encrypted backups cannot be decrypted.

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For example:

```ini
BACKUP_ENCRYPTION_KEY=replace-with-the-generated-key
```

### Google Drive

| Setting | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_CLIENT_SECRET_FILE` | ADC default | Optional service-account credentials JSON file. If unset, Application Default Credentials (such as an attached Compute Engine service account) are used. |
| `GOOGLE_BACKUPS_DIR` | required | Drive folder ID where backup files are stored. |

The service account (either from `GOOGLE_CLIENT_SECRET_FILE` or the attached ADC service account) needs access to the selected Drive folder, and the Google Drive API must be enabled in the GCP project.

### Google Cloud Storage

| Setting | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_CLOUD_STORAGE_BUCKET` | required | Bucket for backup objects. |
| `GOOGLE_CLOUD_STORAGE_PREFIX` | `Backups` | Object name prefix. |
| `GOOGLE_CLOUD_PROJECT` | detected | Optional project ID override. |
| `GOOGLE_APPLICATION_CREDENTIALS` | ADC default | Optional credential configuration file. On Google Cloud, prefer an attached service account. |

The workload identity or service account needs permission to list, create, read,
and delete backup objects in the bucket/prefix.

### Alarm callback

Configure a project-owned function if backup failures should call an existing
alarm service. For example:

```ini
BACKUP_ALARM_FUNCTION=myproject.notifications.send_alarm
```

The callback is called with `severity="Critical"` and a `text` argument that
includes the error when available. Failures are also written to the Python log.

## Commands

Create a database dump, optionally keep a local copy, then encrypt and upload it:

```powershell
python manage.py backup
```

Upload and encrypt an existing plain PostgreSQL dump:

```powershell
python manage.py backup C:\backups\manual.pgsql
```

List remote backups from inclusive dates (`YYYYMMDD`):

```powershell
python manage.py list_backups 20260501 20260730
```

Delete remote backups matching a filename or substring:

```powershell
python manage.py delete_backups db_backup_202401
```

List downloadable backups and their provider-specific identifiers:

```powershell
python manage.py restore --list
```

Download and decrypt a backup. The command saves the plaintext dump under
`BACKUPS_DIR`; run the appropriate PostgreSQL restore command yourself:

```powershell
python manage.py restore <drive-file-id-or-gcs-object-name>
psql --dbname <database> --file <decrypted-dump.pgsql>
```

The local cleanup keeps all files from the most recent retention window. For
older months from 2024 onward it retains one backup per month. Files dated
before 2024 are preserved. Remote cleanup follows the same year and monthly
retention rules.

## Development

```powershell
python -m pip install -e ".[gcs,test]"
python -m pytest
```

The unit tests mock Google APIs and do not require cloud credentials or a live
bucket.

## Publish to Artifact Registry

Maintainers need the Google Cloud CLI, Artifact Registry Writer access to the
**private-python** repository, and Application Default Credentials. On a
workstation, authenticate with:

~~~powershell
gcloud auth application-default login
~~~

For service account credentials, set **GOOGLE_APPLICATION_CREDENTIALS** to the
credential file path in the publishing environment.

Run the publishing script from PowerShell. It creates and activates **.venv**
when needed, installs the build, Twine, and Artifact Registry keyring tools,
checks the keyring backend and both built artifacts, then uploads to the
**private-python** repository:

~~~powershell
.\publish.ps1 -ProjectId "<PROJECT_ID>"
~~~

You can omit **-ProjectId** when **GCP_PROJECT_ID** is set. Otherwise the script
tries to resolve project number **910889088117** with gcloud and stops with an
error if it cannot determine the project ID. The script does not use .pypirc
or store credentials in this repository.
