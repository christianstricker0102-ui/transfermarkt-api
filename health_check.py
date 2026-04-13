#!/usr/bin/env python3
"""
TM API Health-Check mit Telegram-Alert.
Ruft /health auf, schickt Telegram-Nachricht wenn Cookies abgelaufen.

Usage: python3 health_check.py
Cron:  0 */6 * * * cd ~/Dev/transfermarkt-api && python3 health_check.py
"""

import os
import sys
import requests

API_URL = os.getenv("TM_API_URL", "http://localhost:8000")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Fallback: Secrets aus backend.env laden
SECRETS_FILE = os.path.expanduser("~/.haspel-secrets/backend.env")
if not BOT_TOKEN and os.path.exists(SECRETS_FILE):
    with open(SECRETS_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                BOT_TOKEN = line.split("=", 1)[1]
            elif line.startswith("TELEGRAM_CHAT_ID="):
                CHAT_ID = line.split("=", 1)[1]


def send_telegram(message: str):
    """Nachricht an Christian via Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[WARN] Telegram nicht konfiguriert. Nachricht: {message}")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)


def check():
    try:
        resp = requests.get(f"{API_URL}/health", timeout=15)
        data = resp.json()
    except requests.ConnectionError:
        send_telegram(
            "⚠️ <b>TM API nicht erreichbar</b>\n"
            "Server laeuft nicht auf Port 8000.\n"
            "→ Backend neustarten!"
        )
        sys.exit(1)
    except Exception as e:
        send_telegram(f"⚠️ <b>TM Health-Check Fehler</b>\n{e}")
        sys.exit(1)

    status = data.get("status")
    age = data.get("cookies", {}).get("age_hours")

    if status == "captcha_required":
        send_telegram(
            "🔒 <b>TM Cookies abgelaufen!</b>\n"
            f"Alter: {age}h\n"
            f"Detail: {data.get('detail', '-')}\n\n"
            "→ <code>cd ~/Dev/transfermarkt-api && python3 solve_captcha.py</code>"
        )
        sys.exit(1)

    # Warnung wenn Cookies aelter als 72h (Erfahrungswert)
    if age and age > 72:
        send_telegram(
            f"⏳ <b>TM Cookies werden alt</b> ({age}h)\n"
            "Noch OK, aber bald CAPTCHA faellig.\n"
            "→ <code>cd ~/Dev/transfermarkt-api && python3 solve_captcha.py</code>"
        )
        sys.exit(0)

    print(f"[OK] TM API healthy — Cookies {age}h alt")


if __name__ == "__main__":
    check()
