# Wings Connect Test

Misst die In-Flight-WiFi-Qualität auf Eurowings-Flügen (Wings Connect by Anuvu, Ku-Band-Satellit) und verknüpft jede Messrunde mit den Live-Flugdaten der Bord-API.

## Aktueller Stand (2026-10-24)

- **Beide Messflüge sind ausgewertet, kein weiterer Flug geplant.** Laptop am 24.10. per `-Restore` zurückgesetzt.
- Flug 2: **EW9441 BCN → DUS, 24.10.2026**, A321ceo D-AIDT (Callsign EWG3LK): `logs/REPORT_2026-10-24_EWG3LK.html`, 23 Runden bis Taxi-In. Auf dem Hinflug EW9444 (18.10., DUS → BCN) war **kein Wings Connect verfügbar** — keine Messung.
- Flug 1 (EWG39C DUS → ACE, 31.03.) ist ausgewertet: `logs/BERICHT_2026-03-31_*.md` (mit Erratum) und `logs/REPORT_2026-03-31_*.html`.

## Dateien

- `test_connection.sh` — Messskript (Ping, DNS, HTTP, curl-Bandbreite, optional iperf3, Flugdaten)
- `make_report.py` — HTML-Bericht und `--summary` (Textstatus), Python 3 ohne Abhängigkeiten
- `probe_session.py` — Sidecar (Flug 2): redigierter Sitzungs-/Tarifstatus des Anuvu-Portals alle 5 Min → `logs/session_*.jsonl`; nur Feld-Whitelist, niemals Zugangsdaten loggen
- `probe_network.py` — einmalige Netzwerk-Probe: erlaubte Ports/Protokolle, DNS/Proxy/TLS, Client-Isolation, Sichtbarkeit des eigenen Geräts → `logs/netprobe_*.txt/.json`
- `prepare_laptop.ps1` — Laptop vorbereiten / `-Restore`
- `README.md` — Befehle, Optionen, CSV-Spalten, Checkliste · `docs/wingsconnect-api.md` — Bord-API
- `logs/` — `.log` (lesbar), `.csv` (eine Zeile pro Runde), `.jsonl` (rohe API-Antworten), `BERICHT_*.md`, `REPORT_*.html`; versioniert. Netprobe-Ausgaben und Funktionstest-Dateien (`*_test.*`) bleiben lokal.

## Befehle

```bash
bash test_connection.sh --flight EW9441                        # Dauermessung alle 2 Min.
bash test_connection.sh --once                                 # Funktionstest (Dateien *_test.*)
/c/Python313/python make_report.py --flight EW9441 --summary   # Status in ~20 Zeilen
/c/Python313/python make_report.py --flight EW9441 --open      # HTML-Bericht
```

## Regeln

- **Git:** Remote `origin` = https://github.com/bitpage-de/WingsConnectTest.git. Nach jedem Commit sofort pushen, ohne Rückfrage (Datensicherung). Logs werden versioniert.
- **Tokensparend arbeiten:** `.log`, `.jsonl` und `.html` in `logs/` nicht lesen (bis >100 KB). Stand über `make_report.py --summary` holen, einzelne Spalten per `cut -d',' -f… datei.csv`. An Bord läuft diese Session über ~0,5 Mbit/s Satellit mit 700+ ms Latenz: kurze Kontexte, wenige Tool-Aufrufe, Dinge bündeln.
- **Python** ist `/c/Python313/python` (in Git Bash nicht als `python`). **PowerShell 5.1:** Skripte als UTF-8 mit BOM; `"${var}:"` statt `"$var:"`.

## Fallstricke in den Daten

- **Zeiten:** `timestamp_local` = Laptop-Zeit (MESZ/MEZ), `timestamp_utc` = UTC, API-`eta` = UTC. Der Markdown-Bericht von Flug 1 nennt Laptop-Zeiten fälschlich „UTC“ (tatsächlich +2 h).
- **Paketverlust in Flug-1-CSV** ist die *Anzahl* verlorener Pakete von 10 („4“ = 40 %). `make_report.py` rechnet das um; seit Flug 2 steht der Prozentwert drin.
- `internetAvailable: false` trotz funktionierendem Link = Portal-/Bezahlstatus.
- Flug-1-Daten liegen in 10 Teildateien (Skript-Neustarts); `make_report.py` führt sie zusammen.
- `probe_network.py` nicht wiederholt laufen lassen: portquiz.net/letmeoutofyour.net sperren die IP nach wenigen Läufen. Zum Testen einzelner Abschnitte das Modul importieren und `EGRESS_PORTS` kürzen.
- Netprobe-Ausgaben enthalten Firewall-Regeln, lauschende Ports und IPs des Laptops und werden **nicht** versioniert (`.gitignore`). Sie bleiben lokal.
- Flug 2, Runden ca. 11:59–12:03 lokal: parallel liefen größere Downloads über den Satelliten-Link (~3 MB); Bandbreite/Latenz dieser Runden ggf. gedrückt.

## Erfahrungswerte Flug 1 (Reiseflughöhe, Satellit)

Ping 700–900 ms normal, 1100–1400 ms nach Satelliten-Handover (Gibraltar, ~13:00 UTC) · DNS 200–5000 ms · HTTP TTFB 2–7 s · Verlust 0–10 % normal, 30–60 % im Handover, 2 komplette Timeouts · Download 0,05–1,3 Mbit/s, Upload 0,07–0,7 Mbit/s (curl, 1 TCP-Stream) · iperf3-Port 5201 vermutlich gesperrt.
