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
# Stats-URL hat eigenen Anti-Bot-Challenge (HTTP 202 + Interstitial).
# Ohne diesen zweiten Browser-Besuch schlaegt /players/{id}/stats im API-Server fehl.
STATS_URL = "https://www.transfermarkt.com/-/leistungsdatendetails/spieler/28003"


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
            try:
                title = page.title()
            except Exception:
                # Navigation/Redirect nach CAPTCHA — Context destroyed = vermutlich geloest
                time.sleep(2)
                try:
                    title = page.title()
                except Exception:
                    print(f"\n✅ CAPTCHA geloest (Redirect erkannt) nach {(i+1)*2}s!")
                    break
            if "Human" not in title and "Verification" not in title and "Just a moment" not in title:
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

        # Verifikation 1: Profil-Seite laden
        print("\n🔍 Teste Zugriff auf Spieler-Profil...")
        page.goto(TEST_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        if "Messi" in page.content():
            print("✅ Profile-Zugriff funktioniert.")
        else:
            print("⚠️  Profil geladen, aber Messi nicht gefunden. Cookies koennten unvollstaendig sein.")

        # Verifikation 2: Stats-Seite laden (zweiter Challenge-Typ — eigene Cookies noetig)
        print("\n🔍 Teste Zugriff auf Stats-Endpoint (zweiter Challenge-Typ)...")
        page.goto(STATS_URL, wait_until="domcontentloaded", timeout=30000)
        stats_ok = False
        for i in range(30):
            time.sleep(2)
            try:
                content = page.content()
                title = page.title()
            except Exception:
                continue
            # Stats-Seite hat "items"-Tabelle und "Leistungsdaten" im Titel.
            # Challenge-HTML hat keins von beidem.
            if ('class="items"' in content or "leistungsdaten" in title.lower()):
                print(f"✅ Stats-Zugriff nach {(i+1)*2}s!")
                stats_ok = True
                break
        if not stats_ok:
            print("⚠️  Stats-Challenge nicht passiert — evtl. manuell CAPTCHA im Fenster loesen.")

        # Cookies erneut speichern (nun inkl. Stats-Challenge-Cookies)
        cookies = ctx.cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"\n💾 {len(cookies)} Cookies final gespeichert (Profile + Stats)")
        if stats_ok:
            print("✅ API kann jetzt gestartet werden.")
        else:
            print("⚠️  API startbar, aber Stats-Endpoint evtl. noch blockiert.")

        browser.close()
        return stats_ok


if __name__ == "__main__":
    solve()
