# Wings Connect Test

Automatisierte Messung der In-Flight-WiFi-Qualität auf Eurowings-Flügen
(„Wings Connect“ von Anuvu). Jede Messrunde verknüpft Netzwerkwerte mit den
Live-Flugdaten der bordinternen API.

| Flug | Datum | Route | Bericht |
|------|-------|-------|---------|
| EWG39C / EW39C | 2026-03-31 | DUS → ACE | [logs/BERICHT_2026-03-31_EWG39C_DUS-ACE.md](logs/BERICHT_2026-03-31_EWG39C_DUS-ACE.md) |
| EW9441 / EWG3LK | 2026-10-24 | BCN → DUS | [logs/REPORT_2026-10-24_EWG3LK.html](logs/REPORT_2026-10-24_EWG3LK.html) |

Auf dem Hinflug EW9444 (2026-10-18, DUS → BCN) war Wings Connect nicht verfügbar, daher keine Messung.

## Schnellstart

Alle Befehle in **Git Bash** im Projektordner ausführen.

```bash
# Dauermessung für einen Flug (alle 2 Min., bis Strg+C)
bash test_connection.sh --flight EW9441

# Nach Absturz / versehentlichem Schließen: einfach denselben Befehl erneut
# → hängt an die Dateien des Tages an, Rundenzähler läuft weiter
bash test_connection.sh --flight EW9441

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
- [ ] Laptop vorbereiten: `.\prepare_laptop.ps1` in PowerShell (fordert Adminrechte per UAC an): kein Standby, Zuklappen ohne Schlaf, WLAN volle Leistung, Windows Update pausiert, Cloud-Sync gestoppt, Uhr synchronisiert. Nach dem Flug: `.\prepare_laptop.ps1 -Restore`
- [ ] Akku voll, Netzteil dabei (A320 der Eurowings haben meist USB-A, selten Steckdosen)
- [ ] Logs des Vortags gesichert / committet

### An Bord

1. Mit dem Bord-WLAN verbinden, Portal öffnen, Paket freischalten
2. WLAN als getaktet markieren, damit Windows im Hintergrund nichts nachlädt (als Administrator, `<SSID>` ersetzen):
   `netsh wlan set profileparameter name="<SSID>" cost=Fixed`
3. Messung starten: `bash test_connection.sh --flight EW9441`
4. **Nicht neu starten**, solange es läuft. Bei Problemen: Strg+C, denselben Befehl erneut → hängt an.
5. Laufen lassen bis das WLAN im Sinkflug abgeschaltet wird

### Danach

```bash
# Rohdaten sichern = committen und pushen (logs/ liegt komplett im Repo)
git add -A && git commit -m "Messdaten EW9441" && git push

# HTML-Bericht erzeugen (eine Datei, offline nutzbar) und im Browser öffnen
/c/Python313/python make_report.py --flight EW9441 --open

# Schnellblick: Höhe, Phase, Ping, Verlust, Download pro Runde
cut -d',' -f1,3,7,8,19,20,29 logs/wingsconnect_2026-10-24_EW9441.csv | column -t -s','
```

## HTML-Bericht

`make_report.py` liest die CSV-Dateien (altes Format von Flug 1 und neues Format), optional die `.jsonl`-Rohdaten, und schreibt einen eigenständigen Bericht nach `logs/REPORT_<Datum>_<Flug>.html` mit Kennzahlen, Zeitreihen (Ping, Verlust, DNS, TTFB, Bandbreite, Höhe, Speed), Flugspur, Ereignisliste und vollständiger Tabelle. Hell/Dunkel folgt dem System, Tooltips per Maus.

```bash
/c/Python313/python make_report.py --flight EW9441 --summary    # Kurzstatus im Terminal, kein HTML
/c/Python313/python make_report.py --flight EW9441              # alle logs/wingsconnect_*_EW9441.csv
/c/Python313/python make_report.py --flight EW9441 --date 2026-10-24 --open
/c/Python313/python make_report.py logs/wingsconnect_2026-03-31_*.csv --flight EWG39C --route "DUS → ACE" \
    -o logs/REPORT_2026-03-31_EWG39C_DUS-ACE.html                 # Flug 1 (altes Format, 10 Teildateien)
```

Hinweis zu Flug 1: Das alte Skript speicherte den Paketverlust als *Anzahl* verlorener Pakete (von 10), nicht in Prozent. Der Bericht rechnet das um (×10); die Werte im Markdown-Bericht vom 31.03. („0–6 %“) sind entsprechend 0–60 %.

## Netzwerk-Probe: Was lässt das Bord-WLAN zu?

`probe_network.py` prüft einmalig (ca. 2 Minuten), was im Netz erlaubt ist und wie sichtbar das eigene Gerät ist. Es testet nur eigene Verbindungen, das eigene Subnetz und das eigene Gerät, keine Portscans fremder Geräte.

```bash
/c/Python313/python probe_network.py --flight EW9441        # voll: mit Ping-Sweep im eigenen /24, 15 s Mithören
/c/Python313/python probe_network.py --flight EW9441 --quick
```

| Block | Was geprüft wird |
|-------|------------------|
| Umgebung | IP, Subnetzgröße, Gateway, DNS, Netzwerkprofil, öffentliche IP + Provider, IPv6 |
| Portal/Proxy/TLS | Connectivity-Checks, HTTP-Umleitung, Proxy-Header, Zertifikatsaussteller (TLS-Interception?) |
| DNS | System-Resolver, direkt 8.8.8.8/1.1.1.1 per UDP, TCP und DoT, DoH, NXDOMAIN-Hijack, Resolver-Identität |
| TCP-Egress | 29 Ports gegen portquiz.net (lauscht auf allen Ports; Antwort wird verifiziert) + echte Banner: FTP, SSH, Telnet, SMTP, IMAP, POP3; FTP-Login mit Listing |
| UDP | NTP (mit Uhrabweichung), STUN (öffentliche IP, NAT-Typ) |
| Isolation | Gateway-Ping, Ping-Sweep, ARP-Nachbarn, 15 s passives Mithören von mDNS/SSDP/LLMNR/NetBIOS, je eine mDNS-/SSDP-Anfrage |
| Eigenes Gerät | Firewall je Profil, Netzwerkerkennung, Datei-/Druckerfreigabe, RDP, NetBIOS/LLMNR, lauschende Ports mit Prozess |

Ausgabe: `logs/netprobe_<Datum>_<Uhrzeit>_<Flug>.txt` (lesbar) und `.json`. Sinnvoll zweimal: vor dem Portal-Login und danach.

**Sparsam einsetzen:** Die Egress-Testserver (portquiz.net, Ausweichserver letmeoutofyour.net) sperren die Quell-IP bei zu vielen Verbindungen. Am 18.10. war das nach 4 Läufen in 8 Minuten der Fall. Pro Flug ein bis zwei Läufe; ist kein Testserver erreichbar, meldet das Skript „Port-Matrix nicht prüfbar“, die echten Dienste in Abschnitt 4b laufen trotzdem.

**Gegenprobe für die Sichtbarkeit:** Ob ein Port wirklich von außen erreichbar ist, lässt sich vom Laptop selbst nicht testen (Verbindungen zur eigenen IP laufen über Loopback, die Firewall filtert sie nicht). Dafür von einem zweiten Gerät im selben WLAN mit einer Netzwerkscanner-App die IP des Laptops prüfen.

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
