# Wings Connect Test

Projekt zum automatisierten Testen der In-Flight WiFi-Verbindungsqualität auf Eurowings-Flügen (Wings Connect by Anuvu/Lufthansa Group).

## Projekt-Struktur

- `test_connection.sh` — Hauptskript: misst Ping, DNS, HTTP-Latenz, iperf3-Bandbreite und protokolliert Flugdaten
- `logs/` — Ausgabeverzeichnis für `.log` (menschenlesbar) und `.csv` (maschinenlesbar) Dateien

## Verwendung

```bash
bash test_connection.sh            # Dauermessung alle 2 Min.
bash test_connection.sh --once     # Einmalige Messung
bash test_connection.sh --traceroute  # Nur Traceroute
```

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
| `internetAvailable` | bool | Ob Internet-Zugang aktiv ist |
| `internetUnavailableReason` | int | Grund bei Nicht-Verfügbarkeit |
| `eta` | string | Voraussichtliche Ankunft (HH:MM lokal) |
| `distDest` | float | Entfernung zum Ziel in Nautischen Meilen |
| `orig` / `dest` | object | Start-/Zielflughafen mit `code`, `lat`, `lon`, `localTime` |
| `elapsedFlightTime` | string | Bisherige Flugzeit (HH:MM) |
| `weightOnWheels` | bool | Flugzeug am Boden? |
| `enginesOff` | bool | Triebwerke aus? |

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
- **ping** / **tracert** — Latenz- und Paketverlustmessung
- **Python 3** — JSON-Parsing (auf diesem System: `/c/Python313/python`)
- **iperf3** (optional) — Bandbreitenmessung gegen öffentliche Server

## Typische Messwerte (Satellit, Reiseflughöhe)

- Ping-Latenz: 700–900 ms (Satellitenverbindung)
- DNS-Auflösung: 200–2500 ms (sehr variabel)
- HTTP TTFB: 2–7 s
- Paketverlust: 0–1 %
