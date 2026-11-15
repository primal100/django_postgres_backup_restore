import logging

from django.conf import settings
from django.utils.module_loading import import_string


logger = logging.getLogger("backup_restore")


def send_backup_alarm(message):
    callback_path = getattr(settings, "BACKUP_ALARM_FUNCTION", None)
    if not callback_path:
        logger.warning("Backup alarm callback is not configured: %s", message)
        return
    try:
        callback = import_string(callback_path) if isinstance(callback_path, str) else callback_path
        callback(severity="Critical", text=message)
    except Exception:
        logger.exception("Unable to send backup alarm")
