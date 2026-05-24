import json
import logging
from datetime import datetime


class JsonLogFormatter(logging.Formatter):
    """Writes structured JSON lines for troubleshooting and traceability."""

    EXTRA_ATTRS = (
        "event",
        "action",
        "entity",
        "entity_id",
        "ref_id",
        "status",
        "profile",
        "db_path",
        "details",
        "path",
        "result",
        "repair_key",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in self.EXTRA_ATTRS:
            value = getattr(record, attr, None)
            if value in (None, "", [], {}, ()):
                continue
            payload[attr] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


__all__ = ["JsonLogFormatter"]
