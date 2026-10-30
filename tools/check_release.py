"""Prüft vor dem Build, ob Version, Setup und Hilfe vollständig zusammenpassen.

1. Programm-, Setup- und „Neu in Version“-Eintrag haben dieselbe Version.
2. Jeder Bereich der Seitenleiste hat einen eigenen Hilfe-Abschnitt (F1 / „?“ springt dorthin).
3. Jeder Schalter in den Einstellungen ist in der Hilfe erklärt.
4. Jede Funktion aus FEATURES (unten) kommt in der Hilfe vor – neue Funktionen hier eintragen!
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
read = lambda p: open(os.path.join(ROOT, p), encoding="utf-8-sig").read()  # noqa: E731

# Funktionen, die in der Hilfe beschrieben sein müssen (Begriff, wie er in der Hilfe steht)
FEATURES = [
    "Bildschirm aufnehmen", "Ton vom PC", "Mein Mikrofon", "Ein Fenster / Programm", "Einverständnis", "kleine Leiste",
    "install.sh", "MPRIS",
    "Überblenden", "Lautstärke angleichen", "Mini-Player", "Aufräumen", "Doppelte Titel", "Leere Ordner", "Nach Updates suchen",
    "Speicherort beim Installieren",
    "Tesla", "Grundton",
    "Eigene Farben",
    "Hereinziehen",
    "Senderlogo",
    "Songtext bei Alles am PC", "Zeile anklicken, die gerade gesungen wird",
    "Lichter aus",
    "Analysieren", "Live-Auftritt", "Original nehmen", "Aufteilen", "Als Album taggen", "Live mitschneiden",
    "CD lesen", "Veröffentlichung", "Prüflesen", "Auswerfen", "CD-Abbild öffnen", "Test-CD erzeugen",
    "Eingänge", "Systemsound", "Start bei Signal", "In Titel teilen", "Stopp nach Stille", "Knackser",
    "Aufnahme verwerfen", "Automatisch erkennen", "VIDEO_TS", "Mit SongGrabber umwandeln",
    "Tags bearbeiten", "Online ergänzen", "Kürzen", "Löschen", "Übertragen", "Autoradio-sicher",
    "Playlists erstellen", "Zufallsmix", "Neu einlesen", "Als Nächstes abspielen",
    "Lichtshow", "Synthwave", "Farbwelt", "Equalizer", "Schlaf-Timer", "Vollbild", "Wiederholen", "Zufall",
    "Warteschlange", "Songtext", "Medientasten", "Als Musik-Player anbieten", "Tempo",
    "Abonnieren", "Mit Windows starten", "Fertige entfernen", "Lautheit angleichen", "Ordnerstruktur",
    "Fehlerbericht", "Tastenkürzel", "Kommandozeile", "Portabel", "Übergabe-Ordner",
    "Abspielen ohne Download", "Online suchen", "Link abspielen", "Alles am PC", "Radio", "Favoriten", "Zuletzt gehört",
    "LIVE", "Mitschneiden", "Podcasts", "Feed-Adresse", "Meine Podcasts", "Weiter", "Zurück",
]


def main():
    html, js = read("ui/index.html"), read("ui/app.js")
    version = re.search(r'VERSION = "([\d.]+)"', read("agcore/paths.py")).group(1)
    setup = re.search(r'#define AppVersion "([\d.]+)"', read("installer/SongGrabber.iss")).group(1)
    changes = re.search(r'const CHANGES = \[\s*\["([\d.]+)"', js).group(1)
    problems = []
    if setup != version:
        problems.append(f"Setup-Version {setup} ≠ Programmversion {version}")
    if changes != version:
        problems.append(f"Hilfe „Neu in Version“ steht auf {changes}, Programm ist {version} – CHANGES in ui/app.js ergänzen")

    help_html = html[html.index('id="helpBody"'):]
    help_html = help_html[:help_html.index("</section>")]
    help_text = re.sub(r"<[^>]+>", " ", help_html).replace("&amp;", "&")
    articles = set(re.findall(r'<article id="([\w-]+)"', help_html))

    # 2. Bereiche
    pages = sorted(set(re.findall(r'class="nav-item[^"]*" data-page="(\w+)"', html)) - {"help"})
    mapping = dict(re.findall(r'(\w+): "(h-[\w-]+)"', re.search(r"const HELP_FOR = \{([^}]*)\}", js).group(1)))
    for p in pages:
        if p not in mapping:
            problems.append(f"Bereich „{p}“ hat keinen Hilfe-Abschnitt in HELP_FOR (ui/app.js)")
        elif mapping[p] not in articles:
            problems.append(f"Hilfe-Abschnitt „{mapping[p]}“ für Bereich „{p}“ fehlt in ui/index.html")

    # 3. Einstellungen
    help_keys = set(" ".join(re.findall(r'data-help-key="([^"]+)"', help_html)).split())
    for key in sorted(set(re.findall(r'data-key="(\w+)"', html))):
        if key not in help_keys:
            problems.append(f"Einstellung „{key}“ ist in der Hilfe (Einstellungen) nicht erklärt")

    # 4. Funktionen
    for f in FEATURES:
        if f.lower() not in help_text.lower():
            problems.append(f"Funktion „{f}“ kommt in der Hilfe nicht vor")

    if problems:
        print("WARNUNG – bitte vor dem Verkauf beheben:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print(f"Version {version}: Programm, Setup und Hilfe passen zusammen · {len(pages)} Bereiche, "
          f"{len(help_keys)} Einstellungen, {len(FEATURES)} Funktionen in der Hilfe geprüft.")


if __name__ == "__main__":
    main()
