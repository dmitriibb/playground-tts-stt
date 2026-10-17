"""Forward WARNING/ERROR log records to the event bus, so they reach the UI error panel."""

from __future__ import annotations

import logging
import traceback

from common.events import EventPublisher

# Extra fields a log call can carry: logger.error("...", extra={"code": ..., "request_id": ...})
_CONTEXT_FIELDS = ("code", "request_id", "session_id", "model_id", "details")


class EventBusLogHandler(logging.Handler):
    def __init__(self, bus: EventPublisher, level: int = logging.WARNING):
        super().__init__(level)
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            source = record.name.split(".", 1)[0]
            if source not in ("stt", "tts", "gateway", "common"):
                source = "engine" if not source.startswith("uvicorn") else "gateway"
            data = {
                "level": record.levelname.lower(),
                "logger": record.name,
                "message": record.getMessage(),
            }
            for field in _CONTEXT_FIELDS:
                value = getattr(record, field, None)
                if value is not None:
                    data[field] = value
            if record.exc_info and record.exc_info[1] is not None:
                data["traceback"] = "".join(traceback.format_exception(*record.exc_info))
            self._bus.publish("log", source, data)
        except Exception:  # never let logging break the app
            self.handleError(record)


def setup_logging(bus: EventPublisher, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, EventBusLogHandler)
               for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(stream)
    for handler in list(root.handlers):
        if isinstance(handler, EventBusLogHandler):
            root.removeHandler(handler)
    root.addHandler(EventBusLogHandler(bus))
