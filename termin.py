#!/usr/bin/env python3
import os
import re
import time
import traceback
import subprocess
import base64
import wave
import struct
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

# =========================
# KONFIG
# =========================
START_URL = "https://tevis.ekom21.de/dar/select2?md=5"
ANLIEGEN_TEXT = "Erstzulassung (eines Gebrauchtfahrzeuges aus dem Ausland)"

HEADLESS = True         # Debug: False
DEBUG = True

CHECK_INTERVAL_SECONDS = 10  # alle 10 Sekunden prüfen

ENABLE_TOAST = True
ENABLE_BEEP = True
ENABLE_TELEGRAM = False
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Lege eine WAV-Datei neben termin.py:
CUSTOM_WAV = "alarm.wav"        # deine Datei (WAV)
FALLBACK_WAV = "alert_beep.wav" # wird erzeugt, falls CUSTOM_WAV fehlt


# =========================
# NOTIFY (Toast / Sound / Telegram)
# =========================
def _ps_encoded_command(ps_script: str) -> str:
    return base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

def toast(title: str, msg: str) -> None:
    """Toast OHNE Standard-Windows-Sound (Silent), damit nur dein WAV läuft."""
    if not ENABLE_TOAST:
        return
    try:
        title_s = (title or "").replace("'", "''")
        msg_s = (msg or "").replace("'", "''")
        ps_script = f"""
        Import-Module BurntToast -ErrorAction Stop
        New-BurntToastNotification -Silent -Text @('{title_s}', '{msg_s}')
        """
        encoded = _ps_encoded_command(ps_script)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=12
        )
    except Exception:
        print(f"[TOAST-FALLBACK] {title}: {msg}")

def _ensure_fallback_wav(path=FALLBACK_WAV, freq=880, ms=650, volume=0.95, sample_rate=44100):
    if os.path.exists(path):
        return
    n_samples = int(sample_rate * (ms / 1000.0))
    amp = int(32767 * max(0.0, min(1.0, volume)))
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            sample = int(amp * math.sin(2 * math.pi * freq * t))
            wf.writeframes(struct.pack("<h", sample))

def beep() -> None:
    if not ENABLE_BEEP:
        return
    try:
        import winsound
        if os.path.exists(CUSTOM_WAV):
            wav_path = os.path.abspath(CUSTOM_WAV)
        else:
            _ensure_fallback_wav()
            wav_path = os.path.abspath(FALLBACK_WAV)

        # synchron, damit es sicher hörbar ist
        winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_SYNC)
    except Exception as e:
        print(f"[BEEP-ERROR] {e}")

def telegram_send(text: str) -> None:
    if not ENABLE_TELEGRAM:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception:
        pass


# =========================
# FRAMES / BLOCKER
# =========================
def _frames(page):
    frs = [page.main_frame]
    try:
        frs.extend(list(page.frames))
    except Exception:
        pass
    seen, out = set(), []
    for f in frs:
        if id(f) not in seen:
            out.append(f)
            seen.add(id(f))
    return out

def click_cookie_accept(page) -> bool:
    clicked = False
    accept_words = ["Akzeptieren", "Alle akzeptieren", "Einverstanden", "Zustimmen", "OK"]
    for fr in _frames(page):
        for w in accept_words:
            try:
                b = fr.get_by_role("button", name=w).first
                if b.is_visible(timeout=150):
                    b.click(timeout=800, force=True)
                    clicked = True
            except Exception:
                pass
        try:
            b2 = fr.locator("button").filter(has_text=re.compile(r"akzept", re.I)).first
            if b2.is_visible(timeout=150):
                b2.click(timeout=800, force=True)
                clicked = True
        except Exception:
            pass
    return clicked

def click_ok_popup(page) -> bool:
    ok_words = ["OK", "Ok", "Ja", "Schließen", "Schliessen"]
    for fr in _frames(page):
        for w in ok_words:
            try:
                b = fr.get_by_role("button", name=w).first
                if b.is_visible(timeout=150):
                    b.click(timeout=800, force=True)
                    return True
            except Exception:
                pass
    return False

def clear_blockers(page, seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        did = False
        try:
            if click_cookie_accept(page):
                did = True
        except Exception:
            pass
        try:
            if click_ok_popup(page):
                did = True
        except Exception:
            pass
        if not did:
            return
        try:
            page.wait_for_timeout(200)
        except Exception:
            time.sleep(0.2)


# =========================
# Anliegen: Box [-][Zahl][+]
# =========================
def _extract_int(s: str):
    m = re.search(r"\b(\d+)\b", s or "")
    return int(m.group(1)) if m else None

def _read_counter_value(box):
    try:
        inp = box.locator("input").first
        if inp.count() > 0 and inp.is_visible(timeout=80):
            v = inp.input_value(timeout=200)
            x = _extract_int(v)
            if x is not None:
                return x
    except Exception:
        pass
    try:
        txt = box.inner_text(timeout=200)
        x = _extract_int(txt)
        if x is not None:
            return x
    except Exception:
        pass
    return None

def set_vehicle_count_to_one(page, anliegen_text: str, timeout_s: float = 45.0) -> None:
    end = time.monotonic() + timeout_s
    last_err = None

    while time.monotonic() < end:
        clear_blockers(page, seconds=2.0)
        try:
            tloc = page.get_by_text(anliegen_text, exact=False).first
            if tloc.count() == 0:
                page.wait_for_timeout(250)
                continue

            ancestors = tloc.locator("xpath=ancestor::*[self::div or self::li or self::tr]")
            row = None
            best_area = None

            for i in range(min(ancestors.count(), 20)):
                cand = ancestors.nth(i)
                try:
                    if cand.get_by_text(anliegen_text, exact=False).count() == 0:
                        continue
                except Exception:
                    continue

                try:
                    if cand.locator("button").count() < 2:
                        continue
                except Exception:
                    continue

                bb = None
                try:
                    bb = cand.bounding_box()
                except Exception:
                    bb = None
                if not bb or bb.get("height", 9999) > 450:
                    continue

                area = bb["width"] * bb["height"]
                if best_area is None or area < best_area:
                    row = cand
                    best_area = area

            if row is None:
                last_err = RuntimeError("Konnte die Anliegen-Zeile nicht eindeutig finden.")
                page.wait_for_timeout(300)
                continue

            try:
                row.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass

            tbb = tloc.bounding_box()
            if not tbb:
                last_err = RuntimeError("Konnte BoundingBox vom Anliegen-Text nicht lesen.")
                page.wait_for_timeout(300)
                continue
            tx_right = tbb["x"] + tbb["width"]

            box_candidates = row.locator("div, li, span")
            best_box = None
            best_x = None

            for i in range(min(box_candidates.count(), 250)):
                box = box_candidates.nth(i)
                try:
                    if not box.is_visible(timeout=50):
                        continue
                    if box.locator("button").count() < 2:
                        continue
                    val = _read_counter_value(box)
                    if val is None:
                        continue
                    bb = box.bounding_box()
                    if not bb:
                        continue
                    if bb["x"] < tx_right - 5:
                        continue
                    if best_x is None or bb["x"] > best_x:
                        best_box = box
                        best_x = bb["x"]
                except Exception:
                    continue

            if best_box is None:
                last_err = RuntimeError("Konnte keine Counter-Box finden.")
                page.wait_for_timeout(300)
                continue

            cur = _read_counter_value(best_box)
            if cur == 1:
                return

            # rechter Button = Plus
            btns = best_box.locator("button")
            right_btn = None
            right_x = None
            for i in range(min(btns.count(), 6)):
                b = btns.nth(i)
                try:
                    bb = b.bounding_box()
                    if not bb:
                        continue
                    if right_x is None or bb["x"] > right_x:
                        right_btn = b
                        right_x = bb["x"]
                except Exception:
                    continue

            if right_btn is None:
                last_err = RuntimeError("Plus-Button nicht gefunden.")
                page.wait_for_timeout(300)
                continue

            # 0 -> 1
            for _ in range(2):
                cur = _read_counter_value(best_box)
                if cur == 1:
                    return
                if cur is None:
                    raise RuntimeError("Counter-Wert ist None.")
                if cur > 1:
                    raise RuntimeError(f"Counter ist schon >1 (aktuell {cur}) – bitte manuell zurücksetzen.")
                try:
                    right_btn.click(timeout=1500, force=True)
                except Exception:
                    right_btn.evaluate("e => e.click()")
                page.wait_for_timeout(250)
                clear_blockers(page, seconds=2.0)

            cur = _read_counter_value(best_box)
            if cur == 1:
                return
            last_err = RuntimeError(f"Counter blieb bei {cur}.")

        except Exception as e:
            last_err = e

        page.wait_for_timeout(300)

    raise RuntimeError(f"Konnte Fahrzeugzahl nicht auf 1 setzen. Letzter Fehler: {last_err}")


# =========================
# WEITER: #WeiterButton
# =========================
def click_continue(page, timeout_s: float = 35.0) -> None:
    end = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < end:
        clear_blockers(page, seconds=2.0)

        btn = page.locator("#WeiterButton").first
        try:
            if btn.count() == 0:
                page.wait_for_timeout(250)
                continue

            aria = (btn.get_attribute("aria-disabled") or "").strip().lower()
            if aria == "true":
                page.wait_for_timeout(250)
                continue

            try:
                btn.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass

            try:
                btn.click(timeout=2000, force=True)
            except Exception as e:
                last_err = e
                btn.evaluate("e => e.click()")

            page.wait_for_timeout(250)
            clear_blockers(page, seconds=4.0)
            return

        except Exception as e:
            last_err = e
            page.wait_for_timeout(250)

    raise RuntimeError(f"Konnte #WeiterButton nicht klicken. Letzter Fehler: {last_err}")


# =========================
# Standortliste auslesen (alle Zulassungsstellen)
# =========================
LOC_PAT = re.compile(
    r"^(?P<loc>[^,]+?),\s*Termine\s+ab\s+(?P<date>\d{2}\.\d{2}\.\d{4}),\s*(?P<time>[01]\d|2[0-3]):(?P<min>[0-5]\d)\s*Uhr",
    re.IGNORECASE
)

def parse_location_header(text: str):
    """
    Erwartet z.B.:
    "Zulassungsstelle Ober-Ramstadt, Termine ab 05.01.2026, 13:15 Uhr"
    """
    if not text:
        return None
    m = LOC_PAT.search(text.strip())
    if not m:
        return None
    loc = m.group("loc").strip()
    d = m.group("date").strip()
    t = f"{m.group('time')}:{m.group('min')}"
    return loc, d, t

def read_all_locations(page, timeout_s: float = 30.0):
    """
    Liest alle h3.ui-accordion-header aus und gibt [(loc, dd.mm.yyyy, hh:mm), ...] zurück.
    """
    end = time.monotonic() + timeout_s
    last = []

    while time.monotonic() < end:
        clear_blockers(page, seconds=2.0)

        headers = page.locator("h3.ui-accordion-header")
        if headers.count() == 0:
            page.wait_for_timeout(250)
            continue

        out = []
        n = min(headers.count(), 50)
        for i in range(n):
            h = headers.nth(i)
            try:
                if not h.is_visible(timeout=80):
                    continue
            except Exception:
                continue

            title = ""
            try:
                title = h.get_attribute("title") or ""
            except Exception:
                title = ""

            # fallback: sichtbarer Text
            if not title.strip():
                try:
                    title = h.inner_text(timeout=120) or ""
                except Exception:
                    title = ""

            parsed = parse_location_header(title)
            if parsed:
                out.append(parsed)

        if out:
            return out
        last = out
        page.wait_for_timeout(250)

    return last


def filter_today_tomorrow(loc_list, today_dt: datetime):
    today = today_dt.date()
    tomorrow = (today_dt + timedelta(days=1)).date()
    res = []

    for loc, d_str, t_str in loc_list:
        try:
            d = datetime.strptime(d_str, "%d.%m.%Y").date()
        except Exception:
            continue
        if d == today or d == tomorrow:
            res.append((loc, d_str, t_str))
    return res


# =========================
# EIN DURCHLAUF
# =========================
def run_once():
    tz = ZoneInfo("Europe/Berlin")
    now = datetime.now(tz)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(locale="de-DE")
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())

        try:
            page.goto(START_URL, wait_until="domcontentloaded", timeout=45000)
            clear_blockers(page, seconds=6.0)

            set_vehicle_count_to_one(page, ANLIEGEN_TEXT)
            click_continue(page)  # danach kommt ggf. OK-Popup, wird von clear_blockers erledigt

            # jetzt sind wir auf der Standortseite (Accordion-Liste)
            page.wait_for_timeout(800)
            locs = read_all_locations(page, timeout_s=30.0)
            hits = filter_today_tomorrow(locs, now)

            if hits and DEBUG:
                try:
                    page.screenshot(path="found_debug.png", full_page=True)
                    with open("found_debug.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    print("Gefunden-Debug gespeichert: found_debug.png + found_debug.html")
                except Exception:
                    pass

            return hits, locs

        except Exception:
            if DEBUG:
                try:
                    page.screenshot(path="ladadi_debug.png", full_page=True)
                    with open("ladadi_debug.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    print("Fehler-Debug gespeichert: ladadi_debug.png + ladadi_debug.html")
                except Exception:
                    pass
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


# =========================
# LOOP
# =========================
def main_loop():
    tz = ZoneInfo("Europe/Berlin")
    print("LaDaDi Terminwatch (Windows) gestartet.")
    print("Anliegen:", ANLIEGEN_TEXT)
    print(f"Intervall: alle {CHECK_INTERVAL_SECONDS} Sekunden")
    print(f"Sound: {CUSTOM_WAV} (falls vorhanden)\n")

    # damit du nicht alle 10 Sekunden für dasselbe Ergebnis Alarm bekommst:
    # key = location, value = "dd.mm.yyyy hh:mm" zuletzt gemeldet
    last_alert = {}

    while True:
        t0 = time.monotonic()
        stamp = datetime.now(tz).isoformat(timespec="seconds")

        try:
            hits, locs = run_once()

            if hits:
                for loc, d_str, t_str in hits:
                    sig = f"{d_str} {t_str}"
                    if last_alert.get(loc) == sig:
                        print(f"[{stamp}] 🔁 (bereits gemeldet) {loc}: {sig}")
                        continue

                    msg = f"{loc}: Termin ab {d_str}, {t_str} Uhr (heute/morgen!)"
                    print(f"[{stamp}] ✅ {msg}")
                    toast("LaDaDi: Termin frei!", msg)
                    beep()
                    telegram_send(msg)
                    last_alert[loc] = sig
            else:
                # optional: kurze Übersicht in Konsole (kommentiere aus wenn zu laut)
                # print(f"[{stamp}] ❌ Kein Termin heute/morgen. ({len(locs)} Standorte gelesen)")
                print(f"[{stamp}] ❌ Kein Termin heute/morgen.")

        except Exception:
            print(f"[{stamp}] ERROR:\n{traceback.format_exc()}")

        elapsed = time.monotonic() - t0
        time.sleep(max(1, CHECK_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main_loop()
