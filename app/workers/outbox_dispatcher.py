from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from app.config import get_settings
from app.db import init_db
from app.queue.celery_app import celery_app
from app.services.outbox_dispatcher import outbox_dispatcher
from app.services.processing_repository import processing_repository

logger = logging.getLogger("intake.outbox")
stopping = False


def _stop(*_: object) -> None:
    global stopping
    stopping = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = get_settings()
    init_db()
    ready_file = Path("/tmp/outbox-dispatcher-ready")
    ready_file.write_text("ready", encoding="utf-8")
    logger.info("Outbox dispatcher started")
    while not stopping:
        try:
            recovered = processing_repository.recover_stale_runs()
            published = outbox_dispatcher.dispatch_once(celery_app.send_task)
            if recovered or published:
                logger.info("Outbox cycle recovered=%s published=%s", recovered, published)
        except Exception:
            logger.exception("Outbox cycle failed")
        time.sleep(settings.outbox_poll_seconds)
    ready_file.unlink(missing_ok=True)
    logger.info("Outbox dispatcher stopped")


if __name__ == "__main__":
    main()
