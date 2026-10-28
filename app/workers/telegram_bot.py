"""The telegram-bot container: one loop that reads link commands (long polling, outbound only) and sends the
reminders that are due (FR-NTF-01..05, ADR-0057). It is the only process holding the bot token.

    python -m app.workers.telegram_bot                       the loop (what the container runs)
    python -m app.workers.telegram_bot test                  a test line to every linked group, topic and person
    python -m app.workers.telegram_bot preview --at "2026-10-14 17:30"   print what that moment would send, send nothing
    python -m app.workers.telegram_bot send --at "2026-10-14 17:30"      send that moment's reminders now (logged as usual)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.db import init_db
from app.modules.notify import linking
from app.modules.notify.reminders import build_messages, send_due, send_test
from app.modules.notify.telegram import TelegramClient, TelegramError
from app.modules.planning.overview import LOCAL_TZ

logger = logging.getLogger("telegram-bot")
OFFSET_KEY = "update_offset"
TICK_SECONDS = 60


def handle_updates(client: TelegramClient) -> int:
    offset = linking.get_state(OFFSET_KEY)
    updates = client.get_updates(int(offset) if offset else None, timeout=25)
    handled = 0
    for update in updates:
        update_id = int(update.get("update_id") or 0)
        try:
            reply = linking.handle_update(update)
            if reply:
                client.send_message(reply[0], reply[1], thread_id=reply[2])
                handled += 1
        except TelegramError as exc:
            logger.warning("reply failed: %s", exc)
        except Exception:  # noqa: BLE001 - one bad update must not stop the loop; the offset still moves on
            logger.exception("update %s not handled", update_id)
        linking.set_state(OFFSET_KEY, str(update_id + 1))
    return handled


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN is empty; the bot sleeps")
        while True:
            time.sleep(3600)
    init_db()
    client = TelegramClient()
    try:
        me = client.get_me()
        linking.set_state("bot_username", str(me.get("username") or ""))
        linking.set_state("bot_seen_at", datetime.now(timezone.utc).isoformat())
        logger.info("bot @%s ready", me.get("username"))
    except TelegramError as exc:
        logger.error("getMe failed: %s", exc)
    last_tick = 0.0
    while True:
        try:
            handle_updates(client)
        except TelegramError as exc:
            logger.warning("getUpdates failed: %s", exc)
            time.sleep(10)
        except Exception:  # noqa: BLE001
            logger.exception("polling failed")
            time.sleep(10)
        if time.monotonic() - last_tick >= TICK_SECONDS:
            last_tick = time.monotonic()
            try:
                result = send_due(datetime.now(LOCAL_TZ), client)
                if result["sent"] or result["failed"]:
                    logger.info("reminders: %s", result)
                linking.set_state("bot_seen_at", datetime.now(timezone.utc).isoformat())
            except Exception:  # noqa: BLE001
                logger.exception("reminders failed")


def _parse_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(LOCAL_TZ)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        sys.exit('--at phải có dạng "YYYY-MM-DD HH:MM" theo giờ Việt Nam, ví dụ "2026-10-14 17:30"')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="telegram-bot", description="Reminders over Telegram: the loop, or one of the checks.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("test", help="send a test line to every linked group, topic and person")
    for name, help_text in (("preview", "print what a moment would send; send nothing"), ("send", "send a moment's reminders now")):
        one = sub.add_parser(name, help=help_text)
        one.add_argument("--at", help='"YYYY-MM-DD HH:MM" in Vietnam time; default now')
    args = parser.parse_args(argv)
    if args.command is None:
        run()
        return
    logging.basicConfig(level=logging.WARNING)
    init_db()
    if args.command == "preview":
        at = _parse_at(args.at)
        messages = build_messages(at)
        print(f"Lúc {at:%Y-%m-%d %H:%M}: {len(messages)} tin sẽ gửi (chưa trừ tin đã gửi rồi).")
        for message in messages:
            where = f"chat {message.chat_id}" + (f" chủ đề {message.thread_id}" if message.thread_id else "")
            print(f"\n[{message.kind} {message.slot}] -> {where}\n{message.text}")
        return
    if not get_settings().telegram_bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN trống: chạy lệnh này trong container telegram-bot (docker compose run --rm --no-deps telegram-bot ...).")
    if args.command == "test":
        results = send_test()
        if not results:
            print("Chưa có nhóm, chủ đề hay người nào gắn Telegram.")
        for row in results:
            print(f"{row['status']:6} {row['target']}" + (f"  ({row['error']})" if row["error"] else ""))
        return
    if args.command == "send":
        at = _parse_at(args.at)
        print(f"Lúc {at:%Y-%m-%d %H:%M}: {send_due(at)}")


if __name__ == "__main__":
    main()
