# Darmstadt-Dieburg-KFZ-Zulassung-Termin-Checker
Python Script um freie Termine bei der KFZ Zulassungsstelle im Raum Darmstadt Dieburg zu ergattern (weil die mir auf den Sack gehen mit deren Scheiße)
README – LaDaDi Terminwatch (Windows 11)

Dieses Script prüft regelmäßig die TEVIS-Seite und benachrichtigt dich, wenn bei einer Zulassungsstelle ein Termin ab „heute“ oder „morgen“ verfügbar ist (laut „Termine ab …“ in der Standortliste).

1) Python aus dem Microsoft Store installieren

Microsoft Store öffnen

Nach Python suchen (z.B. „Python 3.12“)

Installieren

Terminal/PowerShell neu öffnen

✅ Test (kopieren & einfügen):

python --version

2) Script-Ordner anlegen

✅ Ordner erstellen (kopieren & einfügen):

mkdir C:\Terminwatch
cd C:\Terminwatch


Lege termin.py in C:\Terminwatch

Optional: Lege eine WAV-Datei namens alarm.wav in denselben Ordner (dein Alarmton)

3) Abhängigkeiten installieren

✅ Install (kopieren & einfügen):

python -m pip install --upgrade pip
python -m pip install playwright requests
python -m playwright install chromium


✅ Optional: Windows-Toast (kopieren & einfügen):

python -m pip install BurntToast


Wenn PowerShell meckert „Skripts deaktiviert“:

✅ Fix (kopieren & einfügen):

Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

4) Script starten

✅ Start (kopieren & einfügen):

cd C:\Terminwatch
python termin.py

Einstellungen im Script (einfach ändern)

Öffne termin.py und suche ganz oben den Bereich KONFIG.

✅ Anliegen ändern

🔧 Diese Zeile ändern:

ANLIEGEN_TEXT = "Erstzulassung (eines Gebrauchtfahrzeuges aus dem Ausland)"


➡️ Ersetze den Text exakt so, wie er auf der Webseite steht.

✅ Intervall ändern (wie oft geprüft wird)

🔧 Diese Zeile ändern:

CHECK_INTERVAL_SECONDS = 10


Beispiele:

10 = sehr schnell (kann Captcha/Rate-Limit triggern)

30 = guter Kompromiss

60 = sehr „serverfreundlich“

✅ Browser sichtbar machen (Debug)

🔧 Diese Zeile ändern:

HEADLESS = True


Wenn du “zugucken” willst:

HEADLESS = False

✅ Eigene Sounddatei abspielen (WAV)

Lege eine Datei alarm.wav neben termin.py.

🔧 Diese Zeile ändern (falls anderer Dateiname):

CUSTOM_WAV = "alarm.wav"

✅ Benachrichtigungen an/aus

🔧 Diese Schalter:

ENABLE_TOAST = True
ENABLE_BEEP = True
ENABLE_TELEGRAM = False

Wenn es Probleme gibt
❌ Captcha / viele Fehler

➡️ Stelle das Intervall höher:

CHECK_INTERVAL_SECONDS = 30


oder

CHECK_INTERVAL_SECONDS = 60

❌ Kein Ton

Prüfe Windows „Nicht stören“

Lautstärkemixer / Systemsounds

nutze eine lautere alarm.wav

Fair Use

Bitte fair nutzen:

nicht zu aggressiv pollen

keine Garantie, Seite kann sich ändern

Nutzung auf eigene Verantwortung
