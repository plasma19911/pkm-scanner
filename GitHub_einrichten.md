# Täglich scannen ohne PC – über GitHub

Der Ablauf: GitHub startet jeden Morgen einen Rechner in der Cloud, lässt dort
`scan.py` laufen, legt das Ergebnis in den Ordner `docs/` und schaltet ihn frei.
Deine Handy-App holt sich die Daten von dort. Dein eigener PC bleibt aus.

Du brauchst dafür kein Programmierwissen – nur ein kostenloses GitHub-Konto und
etwa zwanzig Minuten für die Einrichtung.

## 1. Repository anlegen

1. Auf [github.com](https://github.com) anmelden, oben rechts **+ → New repository**.
2. Name frei wählen, z. B. `pkm-scanner`.
3. **Public** wählen. Bei Private funktioniert GitHub Pages nur mit einem
   kostenpflichtigen Konto – dafür wären deine Daten dann privat. Öffentlich
   heißt: die Angebotsseite kann jeder aufrufen, der die Adresse kennt.
4. **Create repository**.

## 2. Dateien hochladen

Auf der Repository-Seite **Add file → Upload files** und diese Dateien aus
deinem Scanner-Ordner hineinziehen:

- `scan.py` (die neue Version)
- `app.html`
- `alerts.json`, `corrections.json`
- `price_history.json`, `offers_history.json` (damit der Verlauf weiterläuft –
  ohne sie fängt er in der Cloud bei null an)

Dann **Commit changes**.

## 3. Den täglichen Auftrag einrichten

Nochmal **Add file → Create new file**. In das Namensfeld genau das eintragen:

```
.github/workflows/scan-taeglich.yml
```

Den Inhalt von `scan-taeglich.yml` hineinkopieren, **Commit changes**.

Die Uhrzeit steht in der Zeile `- cron: "30 5 * * *"` – das ist 05:30 UTC, also
7:30 Uhr im Sommer. Die erste Zahl sind Minuten, die zweite Stunden (UTC).

## 4. Berechtigung erteilen

**Settings → Actions → General**, ganz unten bei *Workflow permissions*
**Read and write permissions** auswählen und speichern. Ohne das darf der
Auftrag die neuen Preise nicht zurückschreiben.

## 5. Ersten Lauf starten

Reiter **Actions → Täglicher Pokémon-Scan → Run workflow**. Der erste Durchlauf
dauert je nach Anzahl der Shops zehn bis dreißig Minuten. Danach gibt es im
Repository einen neuen Ordner `docs/`.

## 6. Seite freischalten

**Settings → Pages**, bei *Source* **Deploy from a branch** wählen, darunter
Branch `main` und Ordner `/docs`, dann **Save**.

Nach ein paar Minuten läuft die App unter:

```
https://DEINNAME.github.io/pkm-scanner/
```

Diese Adresse am Handy öffnen und über das Browsermenü auf den Homescreen
legen – fertig. Ab jetzt aktualisiert sie sich jeden Morgen von selbst.

---

## Was du wissen solltest

**Die Shops könnten blocken.** Shopify und Cloudflare erkennen Anfragen aus
Rechenzentren und sperren sie manchmal – aus dem heimischen WLAN passiert das
seltener. Es kann also sein, dass in der Cloud weniger Shops durchkommen als
bei dir zu Hause. Für den Fall gibt es eine Sicherung: findet ein Lauf weniger
als 50 Produkte, bleibt der zuletzt veröffentlichte Stand einfach stehen,
statt durch eine leere Seite ersetzt zu werden. Sieh nach ein paar Tagen im
Reiter *Actions* nach, wie stabil es läuft.

**Alarme ändern.** Ohne laufenden Server funktionieren die Buttons in der App
nicht. Neue Suchbegriffe trägst du direkt in `alerts.json` im Repository ein
(Datei anklicken → Stift-Symbol → speichern) – beim nächsten Lauf greifen sie.

**Beides geht gleichzeitig.** Zu Hause weiterhin `python scan.py --serve`
starten, wenn du sofort einen frischen Scan willst. Die App merkt selbst, ob
ein Server erreichbar ist: dann erscheinen Live-Suche und Preisverlauf vom
eigenen Rechner, sonst kommt alles aus der Cloud.

**Geplante Läufe schlafen ein.** Wenn im Repository 60 Tage lang niemand
angemeldet etwas tut, schaltet GitHub den Zeitplan ab und schickt eine Mail.
Ein Klick auf *Run workflow* weckt ihn wieder.

**Kosten.** Für öffentliche Repositories sind Actions und Pages kostenlos.
