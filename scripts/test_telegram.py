"""Verify Telegram admin alerts wiring.

Run AFTER setting TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID in .env:
    python scripts/test_telegram.py

Sends a one-line test message + a sample of each alert format so you can
see exactly what booking/reschedule/cancel notifications will look like.

If TELEGRAM_BOT_TOKEN is empty, prints the missing-config warning and
exits 0 (the agent treats no-config as a silent no-op, identical here).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make src/ importable when invoked from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import notify
from src.config import settings


async def main() -> int:
    print("Telegram admin alerts — wiring test\n")
    print(f"TELEGRAM_BOT_TOKEN set:       {bool(settings.telegram_bot_token)}")
    print(f"TELEGRAM_ADMIN_CHAT_ID set:   {bool(settings.telegram_admin_chat_id)}")

    if not (settings.telegram_bot_token and settings.telegram_admin_chat_id):
        print("\nMissing config. Add both to .env then re-run:")
        print("  TELEGRAM_BOT_TOKEN=<token from @BotFather>")
        print("  TELEGRAM_ADMIN_CHAT_ID=<numeric id from @userinfobot>")
        return 0

    print("\n[1/4] Sending wiring-OK ping...")
    r = await notify.test_ping()
    print(f"  -> {r}")
    if not r.get("ok"):
        return 1

    # Show samples of each real alert format so the admin sees what they
    # will actually get during live calls. Each is fire-and-forget; we
    # await briefly so the script doesn't exit before HTTP completes.
    print("\n[2/4] Sample BOOKING alert...")
    notify.notify_booking(
        date="2026-06-03", time_str="10:00",
        name="Test Caller", phone="+919398000000",
        reason="skin consultation",
        party_size=1, service_type="dermatology",
        notes="prefer Dr. Anjali", source="manual", room="test-room",
    )
    await asyncio.sleep(0.7)

    print("[3/4] Sample RESCHEDULE alert...")
    notify.notify_reschedule(
        old_date="2026-06-03", old_time="10:00",
        new_date="2026-06-05", new_time="14:30",
        name="Test Caller", phone="+919398000000",
        reason="skin consultation",
    )
    await asyncio.sleep(0.7)

    print("[4/4] Sample CANCEL alert...")
    notify.notify_cancel(
        date="2026-06-05", time_str="14:30",
        name="Test Caller", phone="+919398000000",
        reason="skin consultation",
        appt_id="test-cancel-id",
    )
    await asyncio.sleep(0.7)

    print("\nAll 4 messages sent. Check your Telegram chat — you should see:")
    print("  ✅ wiring confirmation")
    print("  🆕 New Appointment Booked (sample)")
    print("  🔄 Appointment Rescheduled (sample)")
    print("  ❌ Appointment Cancelled (sample)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
