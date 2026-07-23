# PKM Scanner als Handy-App

Aus der Angebotsseite ist eine installierbare App geworden. Sie liegt als
`app.html` im gleichen Ordner wie `scan.py` und lädt ihre Daten aus einer
neuen Datei `data.json`, die der Scanner bei jedem Durchlauf mitschreibt.

## Einrichten (einmalig)

1. `app.html` und die neue `scan.py` in den Scanner-Ordner kopieren (die alte
   `scan.py` vorher sichern, falls du zurück willst).
2. Server starten wie bisher: `python scan.py --serve`
   Beim ersten Start läuft automatisch ein Scan, danach steht `data.json` bereit.
3. Adresse aus dem schwarzen Fenster am Handy öffnen, z. B.
   `http://192.168.1.50:8765/app.html`

## Auf den Homescreen legen

- **Android (Chrome):** Menü ⋮ → „App installieren" bzw. „Zum Startbildschirm hinzufügen"
- **iPhone (Safari):** Teilen-Symbol → „Zum Home-Bildschirm"

Danach startet sie im Vollbild ohne Browserleiste, mit eigenem Icon. Der letzte
geladene Stand bleibt gespeichert, die App zeigt also auch ohne Verbindung noch
die letzten Preise.

## Von unterwegs

`Handy_Fernzugriff_starten.bat` funktioniert unverändert. Die Adresse, die
Cloudflare ausgibt, führt jetzt direkt zur App.

## Was die App kann

- **Angebote** und **Vorbestellungen** in getrennten Tabs
- Antippen einer Karte öffnet die Preisleiter: alle Shops untereinander,
  günstigster oben und gelb markiert, mit Balken für den Preisabstand
- Preisverlauf als Linie über der Leiste (kommt vom laufenden Server)
- Suche über Produkt und Shop, Filter nach Sprache, Kategorie und Mindestrabatt
- **Alarme**: Treffer zu den Begriffen aus `alerts.json`
- **Neu**: neue Angebote der letzten 48 Stunden, Preissenkungen, neue Artikel
- Nach unten ziehen startet einen neuen Scan (nur mit laufendem Server)

## Ohne PC, einmal täglich

Siehe `GitHub_einrichten.md`: GitHub Actions scannt morgens in der Cloud,
GitHub Pages liefert die App aus. Der Schalter dafür ist

    python scan.py --publish-dir docs

Er erzeugt einen fertigen, serverlosen Ordner (App, `data.json`,
`history.json` mit dem Preisverlauf, Manifest, Service Worker, Icons). Der
funktioniert auf jedem Webspace, nicht nur bei GitHub.

Die App erkennt selbst, woran sie hängt: läuft ein Scanner-Server, gibt es
Live-Suche und Verlauf vom Rechner; sonst kommt alles aus den veröffentlichten
Dateien.

## Was sich an scan.py geändert hat

- schreibt zusätzlich `data.json` (schlank, ca. ein Zehntel der HTML-Größe)
- `manifest.json` und der Service Worker zeigen jetzt auf `app.html`
- Aufruf von `http://…:8765/` landet direkt in der App
- neuer Schalter `--publish-dir` für den Betrieb ohne eigenen Rechner

`angebote.html` wird weiterhin erzeugt und bleibt am PC nutzbar.
