# Wings Connect Test

Automatisierte Messung der In-Flight-WiFi-Qualität auf Eurowings-Flügen
(„Wings Connect“ von Anuvu). Jede Messrunde verknüpft Netzwerkwerte mit den
Live-Flugdaten der bordinternen API.

| Flug | Datum | Route | Bericht |
|------|-------|-------|---------|
| EWG39C / EW39C | 2026-03-31 | DUS → ACE | [logs/BERICHT_2026-03-31_EWG39C_DUS-ACE.md](logs/BERICHT_2026-03-31_EWG39C_DUS-ACE.md) |
| EW9444 | 2026-10-18 | DUS → BCN | folgt |

## Schnellstart

Alle Befehle in **Git Bash** im Projektordner ausführen.

```bash
# Dauermessung für einen Flug (alle 2 Min., bis Strg+C)
bash test_connection.sh --flight EW9444

# Nach Absturz / versehentlichem Schließen: einfach denselben Befehl erneut
# → hängt an die Dateien des Tages an, Rundenzähler läuft weiter
bash test_connection.sh --flight EW9444

# Funktionstest zu Hause (eine Runde, landet in *_test.*)
bash test_connection.sh --once

# Nur Traceroute
bash test_connection.sh --traceroute

# Hilfe
bash test_connection.sh --help
```

### Optionen

| Option | Bedeutung |
|--------|-----------|
| `--flight ID`, `-f ID` | Flugnummer für die Dateinamen, Standard `test` |
| `--once`, `-1` | Nur eine Messrunde |
| `--traceroute`, `-t` | Nur Traceroute |
| `--interval N`, `-i N` | Pause zwischen Runden in Sekunden, Standard 120 |
| `--no-iperf` | iperf3 überspringen, Bandbreite nur per curl |

Umgebungsvariablen: `INTERVAL`, `PING_COUNT` (10), `IPERF_DURATION` (5 s je Richtung), `PYTHON`.

## Was gemessen wird

Pro Runde, in dieser Reihenfolge:

1. **Flugdaten** – `https://www.wingsconnect.aero/map/api/flightData` (nur im Bord-WLAN): Callsign, Kennzeichen, Typ, Phase, Höhe, Speed, Kurs, Position, Distanz, ETA, `internetAvailable`
2. **Ping** – 10 Pakete zu 8.8.8.8 und 1.1.1.1: Mittelwert und Paketverlust in %
3. **DNS** – Dauer von `nslookup google.com` / `cloudflare.com`
4. **HTTP** – curl gegen google.com / cloudflare.com: Time-to-First-Byte und Gesamtzeit
5. **Bandbreite curl** – 5 MB Download und 512 KB Upload gegen speed.cloudflare.com (HTTPS/443, vergleichbar mit Flug 1)
6. **Bandbreite iperf3** – optional, 5 s je Richtung gegen öffentliche Server (Port 5201). Ist der Port gesperrt, wird nur jede 5. Runde erneut probiert.

Vor der ersten Runde läuft einmalig ein Traceroute zu 8.8.8.8.

## Ausgabedateien

`logs/wingsconnect_<Datum>_<Flug>.*` – drei Dateien pro Tag und Flug:

| Datei | Inhalt |
|-------|--------|
| `.log` | Menschenlesbares Protokoll (ohne Farbcodes) |
| `.csv` | Eine Zeile pro Runde, siehe Spalten unten |
| `.jsonl` | Rohe API-Antwort pro Runde mit Zeitstempel (alle Felder, auch die nicht in der CSV) |

**CSV-Spalten:** `timestamp_local, timestamp_utc, round, callsign, registration, aircraft_type, flight_phase, altitude_ft, ground_speed_kts, heading_deg, temperature_c, lat, lon, dist_dest_nm, eta, elapsed_flight_time, internet_available, internet_unavailable_reason, ping_8888_avg_ms, ping_8888_loss_pct, ping_1111_avg_ms, ping_1111_loss_pct, dns_google_ms, dns_cloudflare_ms, http_google_ttfb_s, http_google_total_s, http_cloudflare_ttfb_s, http_cloudflare_total_s, curl_dl_mbps, curl_ul_mbps, iperf_dl_mbps, iperf_ul_mbps, iperf_server`

Fehlwerte: `N/A` (nicht gemessen), `timeout` / `error` (Messung fehlgeschlagen).

> **Zeitzonen:** `timestamp_local` ist die Laptop-Zeit (MESZ = UTC+2 im Sommer, MEZ = UTC+1 im Winter). `timestamp_utc` ist UTC. Die `eta` aus der API ist nach den Daten von Flug 1 ebenfalls UTC.

## Checkliste

### Vor dem Flug (zu Hause / am Flughafen)

- [ ] `bash test_connection.sh --once` läuft fehlerfrei durch („Flugdaten nicht verfügbar“ ist außerhalb des Flugzeugs normal)
- [ ] Laptop vorbereiten: `prepare_laptop.ps1` als Administrator (kein Standby, kein Zuklappen-Schlaf, Updates pausiert, Cloud-Sync gestoppt) – Details im Skript
- [ ] Akku voll, Netzteil dabei (A320 der Eurowings haben meist USB-A, selten Steckdosen)
- [ ] Logs des Vortags gesichert / committet

### An Bord

1. Mit dem Bord-WLAN verbinden, Portal öffnen, Paket freischalten
2. WLAN als getaktet markieren, damit Windows im Hintergrund nichts nachlädt (als Administrator, `<SSID>` ersetzen):
   `netsh wlan set profileparameter name="<SSID>" cost=Fixed`
3. Messung starten: `bash test_connection.sh --flight EW9444`
4. **Nicht neu starten**, solange es läuft. Bei Problemen: Strg+C, denselben Befehl erneut → hängt an.
5. Laufen lassen bis das WLAN im Sinkflug abgeschaltet wird

### Danach

```bash
# Rohdaten sichern (werden von .gitignore ausgenommen) – z.B. in einen Ordner kopieren
cp logs/wingsconnect_2026-10-18_EW9444.* <Sicherungsort>/

# Schnellblick: Höhe, Phase, Ping, Verlust, Download pro Runde
cut -d',' -f1,3,7,8,19,20,29 logs/wingsconnect_2026-10-18_EW9444.csv | column -t -s','
```

## Abhängigkeiten

| Werkzeug | Zweck | Auf diesem Laptop |
|----------|-------|-------------------|
| Git Bash | Shell | ja |
| curl | HTTP-Tests, API, Bandbreite | `/mingw64/bin/curl` |
| ping, tracert, nslookup | Windows-Bordmittel | ja |
| Python 3 | JSON-Parsing | `/c/Python313/python` |
| iperf3 | Bandbreite (optional) | 3.20 via Chocolatey |
| iconv, timeout | Codepage-Konvertierung, Zeitlimit | Git Bash Bordmittel |

## Erfahrungswerte aus Flug 1 (Satellit, Reiseflughöhe)

- Ping: 700–900 ms normal, 1100–1400 ms nach Satelliten-Handover
- DNS: 200–5000 ms, extrem variabel
- HTTP TTFB: 2–7 s
- Download 0,05–1,3 Mbit/s, Upload 0,07–0,7 Mbit/s (curl, ein TCP-Stream)
- Kompletter Ausfall beim Beam-/Satellitenwechsel (Flug 1: über Gibraltar), danach ~25 Min. erhöhte Latenz
- `internetAvailable: false` in der API trotz funktionierendem Link → Flag beschreibt den Portal-/Bezahlstatus
