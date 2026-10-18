# Wings Connect Bord-API

Nur im lokalen WLAN des Flugzeugs erreichbar (kein Internetpaket nötig). Selbstsigniertes Zertifikat → `curl -k`. Keine Authentifizierung. Update-Rate ~1–2 s (ARINC-Daten aus der Avionik, `arincAvailable: true`).

## Flugdaten

```
GET https://www.wingsconnect.aero/map/api/flightData
```

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `altitude` | int | Flughöhe in Fuß |
| `groundSpeed` | int | Geschwindigkeit über Grund in Knoten |
| `heading` | float | Kurs in Grad |
| `temperature` | int | Außentemperatur in °C |
| `lat` / `lon` | float | Aktuelle GPS-Position (Flug 1, Runde 1: kurz die Zielkoordinaten geliefert) |
| `flightPhase` | string | `CRUISE`, `CLIMB`, `DESCENT` etc. |
| `callSign` | string | Funkrufzeichen (z.B. `EWG39C`) |
| `aircraftRegistration` | string | Kennung (z.B. `9H-EWG`) |
| `aircraftType` | string | Flugzeugtyp (z.B. `A320`) |
| `internetAvailable` | bool | Portal-/Bezahlstatus, **nicht** der Satellitenlink |
| `internetUnavailableReason` | int | 1 = vermutlich kein aktives Paket |
| `eta` | string | Voraussichtliche Ankunft HH:MM, **UTC** |
| `distDest` | float | Entfernung zum Ziel in Nautischen Meilen |
| `orig` / `dest` | object | Start-/Zielflughafen mit `code`, `lat`, `lon`, `localTime` |
| `elapsedFlightTime` | string | Bisherige Flugzeit (HH:MM) |
| `weightOnWheels` | bool | Flugzeug am Boden? |
| `enginesOff` | bool | Triebwerke aus? |

Die komplette Antwort landet pro Messrunde in `logs/wingsconnect_<Datum>_<Flug>.jsonl` (`{"ts_local","ts_utc","round","flight":{…}}`).

## Moving Map UI

```
https://www.wingsconnect.aero/map/?language=de&lang=de&origin={ORIG}&destination={DEST}&ac_type={TYPE}&ac_registration={REG}&duration={MIN}&flight_number={FN}&airline={AIRLINE}&uid={UID}&bcsdk_l=de
```

## Portal / Status-Seite

```
https://www.wingsconnect.aero/status
```

Angular-SPA, liefert nur HTML; keine direkt nutzbaren Datenpunkte.

## Netz (Flug 1, Traceroute)

Private Hops 10.23.x / 172.17.x / 10.255.x (Bordnetz), dann ~5 stumme Hops (Satellit), ab Hop 10 ~800–1200 ms (172.30.x, 10.240.x, 100.66.x = Anuvu-Gateway), Ausstieg ins Internet über 80.157.x (Telekom) nach Frankfurt.
