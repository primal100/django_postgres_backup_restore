import logging
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings


logger = logging.getLogger("backup_restore")


def _fernet():
    key = getattr(settings, "BACKUP_ENCRYPTION_KEY", None)
    if isinstance(key, str):
        key = key.encode("ascii")
    if not key:
        raise ValueError(
            "BACKUP_ENCRYPTION_KEY must be configured with a persistent Fernet key"
        )
    return Fernet(key)


def encrypt_text_file(from_path, to_path):
    from_path = Path(from_path)
    to_path = Path(to_path)
    logger.debug("Encrypting database backup %s", from_path)
    to_path.write_bytes(_fernet().encrypt(from_path.read_bytes()))


def decrypt_data(data, file_path):
    file_path = Path(file_path)
    logger.info("Decrypting database backup to %s", file_path)
    file_path.write_bytes(_fernet().decrypt(data))
