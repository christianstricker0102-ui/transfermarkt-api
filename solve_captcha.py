#!/usr/bin/env python3
"""
TM Cookie-Bridge: Oeffnet Browser, du loest das CAPTCHA, Cookies werden gespeichert.
Die API nutzt dann diese Cookies fuer alle Requests.

Usage: python3 solve_captcha.py
"""

import json
import time
import os
from playwright.sync_api import sync_playwright

COOKIE_FILE = os.path.join(os.path.dirname(__file__), ".tm-cookies.json")
TM_URL = "https://www.transfermarkt.com/"
TEST_URL = "https://www.transfermarkt.com/-/profil/spieler/28003"  # Messi


def solve():
    print("🔓 TM Cookie-Bridge — Oeffne Browser...")
    print("   Bitte CAPTCHA im geoeffneten Fenster loesen.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            locale="de-DE",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(TM_URL, timeout=30000)

        # Warte bis CAPTCHA geloest (max 120s)
        print("⏳ Warte auf CAPTCHA-Loesung...")
        for i in range(60):
            time.sleep(2)
            title = page.title()
            if "Human" not in title and "Verification" not in title:
                print(f"\n✅ CAPTCHA geloest nach {(i+1)*2}s!")
                break
        else:
            print("\n❌ Timeout nach 120s. Bitte erneut versuchen.")
            browser.close()
            return False

        # Cookies speichern
        cookies = ctx.cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"💾 {len(cookies)} Cookies gespeichert in {COOKIE_FILE}")

        # Verifikation: Profil-Seite laden
        print("\n🔍 Teste Zugriff auf Spieler-Profil...")
        page.goto(TEST_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        if "Messi" in page.content():
            print("✅ Zugriff funktioniert! API kann jetzt gestartet werden.")
        else:
            print("⚠️  Profil geladen, aber Messi nicht gefunden. Cookies koennten unvollstaendig sein.")

        browser.close()
        return True


if __name__ == "__main__":
    solve()
