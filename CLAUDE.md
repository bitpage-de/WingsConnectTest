# Wings Connect Test

Projekt zum automatisierten Testen der In-Flight WiFi-Verbindungsqualität auf Eurowings-Flügen (Wings Connect by Anuvu/Lufthansa Group).

## Projekt-Struktur

- `test_connection.sh` — Hauptskript: misst Ping, DNS, HTTP-Latenz, Bandbreite (curl + optional iperf3) und protokolliert Flugdaten
- `make_report.py` — erzeugt aus den CSV/JSONL-Dateien einen eigenständigen HTML-Bericht (Python 3, keine Abhängigkeiten)
- `prepare_laptop.ps1` — Laptop für die Messung vorbereiten (kein Standby, Updates pausieren, Cloud-Sync stoppen); `-Restore` setzt zurück
- `README.md` — Befehle, Optionen, CSV-Spalten, Checkliste
- `logs/` — Messdaten (`.log` lesbar, `.csv` pro Runde, `.jsonl` rohe API-Antworten) und Berichte (`BERICHT_*.md`, `REPORT_*.html`). Liegt komplett im Git-Repo (Datensicherung).

## Verwendung

```bash
bash test_connection.sh --flight EW9444   # Dauermessung alle 2 Min.; Neustart am selben Tag hängt an
bash test_connection.sh --once            # Einmalige Messung (Funktionstest)
bash test_connection.sh --traceroute      # Nur Traceroute
/c/Python313/python make_report.py --flight EW9444 --open   # HTML-Bericht
```

## Git

Remote: https://github.com/bitpage-de/WingsConnectTest.git — nach jedem Commit direkt pushen (Datensicherung, keine Rückfrage nötig). Logs werden mit versioniert.

## Flüge

| Flug | Datum | Route | Dateien |
|------|-------|-------|---------|
| EWG39C (9H-EWG, A320) | 2026-03-31 | DUS → ACE | `logs/wingsconnect_2026-03-31_*` (10 Teildateien, altes CSV-Format), `BERICHT_2026-03-31_*.md`, `REPORT_2026-03-31_*.html` |
| EW9444 | 2026-10-18 | DUS → BCN | `logs/wingsconnect_2026-10-18_EW9444.*` |

## Bekannte Fallstricke

- **Zeitzonen:** `timestamp_local` ist Laptop-Zeit (MESZ/MEZ), `timestamp_utc` UTC. Die `eta` der API ist UTC. Der Markdown-Bericht von Flug 1 nennt die Laptop-Zeiten fälschlich „UTC“ (tatsächlich MESZ, also 2 h später).
- **Paketverlust in Flug-1-CSV:** Das alte Skript schrieb die *Anzahl* verlorener Pakete (von 10) in `ping_*_loss_pct`. „4“ bedeutet 40 %. `make_report.py` rechnet das um; seit Flug 2 steht der Prozentwert in der Spalte.
- **`internetAvailable: false`** in der API trotz funktionierender Verbindung — das Flag beschreibt den Portal-/Bezahlstatus, nicht den Satellitenlink.
- **Log-Ausgaben** von `ping`/`tracert` kommen in Codepage 850; das Skript wandelt `tracert` nach UTF-8.
- **Python-Konsole** unter Windows ist cp1252 — `make_report.py` stellt stdout auf UTF-8 um.
- **PowerShell 5.1** braucht UTF-8 **mit BOM** für Umlaute im Skript; `"$var:"` in Strings ist ein Scope-Fehler → `"${var}:"`.

## Wings Connect API (lokal im Flugzeug)

Die API ist nur im lokalen Netzwerk des Flugzeugs erreichbar (kein Internet nötig).

### Flugdaten-Endpunkt

```
GET https://www.wingsconnect.aero/map/api/flightData
```

Liefert JSON mit Echtzeit-Flugdaten:

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `altitude` | int | Flughöhe in Fuß |
| `groundSpeed` | int | Geschwindigkeit über Grund in Knoten |
| `heading` | float | Kurs in Grad |
| `temperature` | int | Außentemperatur in °C |
| `lat` / `lon` | float | Aktuelle GPS-Position |
| `flightPhase` | string | `CRUISE`, `CLIMB`, `DESCENT` etc. |
| `callSign` | string | Funkrufzeichen (z.B. `EWG39C`) |
| `aircraftRegistration` | string | Kennung (z.B. `9H-EWG`) |
| `aircraftType` | string | Flugzeugtyp (z.B. `A320`) |
| `internetAvailable` | bool | Portal-/Bezahlstatus (nicht der Link) |
| `internetUnavailableReason` | int | Grund bei Nicht-Verfügbarkeit (1 = vermutlich kein aktives Paket) |
| `eta` | string | Voraussichtliche Ankunft (HH:MM, UTC) |
| `distDest` | float | Entfernung zum Ziel in Nautischen Meilen |
| `orig` / `dest` | object | Start-/Zielflughafen mit `code`, `lat`, `lon`, `localTime` |
| `elapsedFlightTime` | string | Bisherige Flugzeit (HH:MM) |
| `weightOnWheels` | bool | Flugzeug am Boden? |
| `enginesOff` | bool | Triebwerke aus? |

Selbstsigniertes Zertifikat → `curl -k`. Keine Authentifizierung. Die komplette Antwort landet pro Runde in der `.jsonl`.

### Moving Map UI

```
https://www.wingsconnect.aero/map/?language=de&lang=de&origin={ORIG}&destination={DEST}&ac_type={TYPE}&ac_registration={REG}&duration={MIN}&flight_number={FN}&airline={AIRLINE}&uid={UID}&bcsdk_l=de
```

### Portal / Status-Seite

```
https://www.wingsconnect.aero/status
```

Angular-App (SPA), liefert HTML. Enthält keine direkt nutzbaren Datenpunkte — die relevanten Daten kommen über `/map/api/flightData`.

## Abhängigkeiten

- **bash** (Git Bash unter Windows)
- **curl** — für HTTP-Tests und API-Abrufe
- **ping** / **tracert** / **nslookup** — Windows-Bordmittel
- **Python 3** — JSON-Parsing und Bericht (auf diesem System: `/c/Python313/python`)
- **iperf3** (optional) — Bandbreitenmessung, Port 5201 ist im Flugzeug vermutlich gesperrt (`/c/ProgramData/chocolatey/bin/iperf3`)
- **Node.js** (nur für die Palette-Validierung der Charts, nicht zur Laufzeit; via Chocolatey)

## Typische Messwerte (Satellit, Reiseflughöhe, Flug 1)

- Ping-Latenz: 700–900 ms normal, 1100–1400 ms nach Satelliten-Handover
- DNS-Auflösung: 200–5000 ms (sehr variabel)
- HTTP TTFB: 2–7 s
- Paketverlust: 0–10 % normal, 30–60 % in der Handover-Phase, zwei komplette Timeouts
- Download 0,05–1,3 Mbit/s, Upload 0,07–0,7 Mbit/s (curl, ein TCP-Stream)
