# Wings Connect Verbindungsbericht

**Flug:** EWG39C (Eurowings) | **Route:** DUS - ACE | **Flugzeug:** A320 (9H-EWG)
**Datum:** 2026-03-31 | **Messzeitraum:** 14:44 - 16:01 UTC (~77 Min.)
**Flugphasen:** CRUISE + Beginn DESCENT | **Flughoehe:** 23.788 - 35.476 ft
**Provider:** Wings Connect by Anuvu (Satellit, Ku-Band)

---

## Zusammenfassung

Die Wings Connect Verbindung auf dem Flug DUS-ACE liefert eine **funktionale, aber langsame und instabile Satellitenverbindung**. Die Verbindung ist nutzbar fuer E-Mail, Messaging und einfaches Browsing. Streaming oder Videocalls sind nicht moeglich.

### Bewertung: 4/10

| Kategorie | Wert | Bewertung |
|-----------|------|-----------|
| Ping-Latenz | 683-1382 ms | Schlecht (Satellit-typisch) |
| Paketverlust | 0-6%, zwei Totalausfaelle | Maessig |
| DNS-Aufloesung | 204-5048 ms | Schlecht, extrem variabel |
| HTTP TTFB | 2.1-6.9 s | Schlecht |
| Download | 0.05-1.31 Mbit/s | Sehr schlecht |
| Upload | 0.07-0.72 Mbit/s | Schlecht |
| Verfuegbarkeit | ~91% (2 Ausfaelle in 22 Runden) | Maessig |

---

## Detailergebnisse

### 1. Latenz (Ping)

Gemessen gegen 8.8.8.8 (Google DNS) und 1.1.1.1 (Cloudflare DNS), je 10 Pakete pro Runde.

| Phase | Zeitraum | Ping avg | Verlust | Anmerkung |
|-------|----------|----------|---------|-----------|
| Stabil (Suedspanien) | 14:46-14:55 | 748-795 ms | 0-1% | Normaler Ku-Band-Betrieb |
| **Ausfall #1 (Handover)** | **15:00** | **Timeout** | **100%** | Satellitenwechsel bei Gibraltar |
| Degradiert (Atlantik) | 15:04-15:22 | 1105-1382 ms | 0-6% | Neuer Satellit, schlechterer Pfad |
| Erholung | 15:25-15:42 | 683-837 ms | 0-1% | Stabilisierung |
| Stabil (Kanaren-Naehe) | 15:49-15:51 | 704-845 ms | 0-1% | Guter Betrieb |
| **Ausfall #2** | **15:54** | **Timeout (8.8.8.8)** | **4%** | Erneute kurze Stoerung |
| Sinkflug | 15:57-16:01 | 787-852 ms | 0-1% | Stabil trotz Hoehenabnahme |

**Beobachtung:** Um 15:00 UTC (Position: 36.2N, 7.1W = Gibraltar) gab es einen **kompletten Verbindungsabbruch** -- wahrscheinlich ein Satelliten-Handover. Danach war die Latenz fuer ~25 Minuten um 60-75% erhoeht (1100-1380ms statt 750-800ms). Um 15:54 UTC (30.5N, 12.4W) gab es eine zweite, kuerzere Stoerung. Waehrend des Sinkflugs (35.200 -> 23.800 ft) blieb die Verbindung stabil.

### 2. DNS-Aufloesung

| Metrik | Wert |
|--------|------|
| Minimum | 204 ms |
| Maximum | 5048 ms |
| Median | ~1300 ms |
| Typisch | 200-2300 ms |

DNS ist **extrem variabel** -- die Streuung betraegt Faktor 25. Moeglicherweise werden DNS-Anfragen nicht lokal gecacht, sondern jedes Mal ueber den Satelliten-Link geschickt. In der Luftfahrt-IFC ist dies ein bekanntes Problem, da geostation aere Satelliten allein durch die physische Distanz (2 x 36.000 km) mindestens ~480ms Latenz einfuehren.

### 3. HTTP-Latenz

Gemessen als Time-to-First-Byte (TTFB) und Gesamtladezeit gegen google.com und cloudflare.com.

**Google (22 Messungen):**
| Metrik | Wert |
|--------|------|
| TTFB (best) | 2.15 s |
| TTFB (worst) | 6.68 s |
| TTFB (avg) | ~3.0 s |

**Cloudflare (22 Messungen):**
| Metrik | Wert |
|--------|------|
| TTFB (best) | 2.48 s |
| TTFB (worst) | 6.90 s |
| Total (avg) | ~10.5 s |

Cloudflare laedt insgesamt deutlich langsamer als Google (10-15s vs 3-5s Gesamtzeit), obwohl die TTFB aehnlich ist. Dies deutet auf TCP-Window-Probleme ueber den High-Latency-Link hin: Groessere Seiten erfordern mehr Round-Trips, und jeder Round-Trip kostet ~700-1400ms.

### 4. Bandbreite (9 Messungen mit curl)

| # | Zeit | Hoehe (ft) | Download | Upload | Position |
|---|------|------------|----------|--------|----------|
| 1 | 15:31 | 35.436 | 0.14 Mbit/s | 0.72 Mbit/s | 33.0N, 10.2W |
| 2 | 15:35 | 35.424 | 0.25 Mbit/s | 0.44 Mbit/s | 32.6N, 10.6W |
| 3 | 15:38 | 35.204 | 1.31 Mbit/s | 0.62 Mbit/s | 32.2N, 10.9W |
| 4 | 15:42 | 35.245 | 0.62 Mbit/s | 0.51 Mbit/s | 31.8N, 11.2W |
| 5 | 15:51 | 35.203 | 1.14 Mbit/s | 0.33 Mbit/s | 30.9N, 12.0W |
| 6 | 15:53 | 35.221 | 0.41 Mbit/s | 0.07 Mbit/s | 30.7N, 12.2W |
| 7 | 15:56 | 35.207 | 0.05 Mbit/s | 0.14 Mbit/s | 30.5N, 12.4W |
| 8 | 15:58 | 27.441 | 0.31 Mbit/s | 0.38 Mbit/s | 30.1N, 12.7W |
| 9 | 16:00 | 23.788 | 1.16 Mbit/s | 0.14 Mbit/s | 29.9N, 12.8W |

| Metrik | Download | Upload |
|--------|----------|--------|
| Minimum | 0.05 Mbit/s | 0.07 Mbit/s |
| Maximum | 1.31 Mbit/s | 0.72 Mbit/s |
| Durchschnitt | **0.60 Mbit/s** | **0.37 Mbit/s** |

Die Bandbreite ist **extrem niedrig und variabel** (Faktor 26 beim Download). In Messung 7 brach der Download auf 0.05 Mbit/s ein -- fast unbrauchbar. Upload ist ueberraschenderweise oft aehnlich schnell wie Download; bei Satellitenverbindungen ist das normalerweise stark asymmetrisch. Dies deutet auf eine ueberlastete Download-Kapazitaet (Shared Bandwidth mit anderen Passagieren) hin.

### 5. Flugdaten waehrend der Messung

| Zeitpunkt | Position | Hoehe | Speed | Temp. | Distanz Ziel |
|-----------|----------|-------|-------|-------|--------------|
| 14:46 | 37.5N, 6.0W (Sevilla) | 35.463 ft | 476 kts | -56 C | 738 nm |
| 15:00 | 36.2N, 7.1W (Gibraltar) | 35.428 ft | 481 kts | -55 C | 629 nm |
| 15:14 | 34.6N, 8.7W (Atlantik) | 35.411 ft | 476 kts | -55 C | 486 nm |
| 15:31 | 33.0N, 10.2W (Atlantik) | 35.436 ft | 470 kts | -55 C | 343 nm |
| 15:49 | 30.9N, 12.0W (Kanaren) | 35.203 ft | 458 kts | -55 C | 167 nm |
| 15:57 | 30.1N, 12.7W (Sinkflug) | **27.441 ft** | 447 kts | -36 C | 98 nm |
| 15:59 | 29.9N, 12.8W (Sinkflug) | **23.788 ft** | 420 kts | -26 C | 82 nm |

Der Sinkflug begann um ~15:55 UTC. Trotz Hoehenabnahme von 35.200 auf 23.800 ft blieb die Satellitenverbindung stabil -- die Antenne auf dem Flugzeugdach hatte weiterhin Sichtverbindung zum geostationaeren Satelliten.

Die API meldete ab Runde 2 durchgehend `internetAvailable: false` / `internetUnavailableReason: 1`, obwohl die Verbindung weiterhin funktionierte.

---

## Erkenntnisse

### Satelliten-Handover (~15:00 UTC, ueber Gibraltar)

Der gravierendste Vorfall war ein kompletter Verbindungsabbruch bei ~36.2N, 7.1W. Dies ist konsistent mit einem Satellitenwechsel: Anuvu nutzt fuer Wings Connect geostationaere Ku-Band-Satelliten mit Kapazitaet von **SES** (u.a. SES-15) und **Eutelsat** [1]. Jeder Satellit hat einen begrenzten Footprint (Spot-Beams), und bei der Ueberquerung einer Beam-Grenze muss das Flugzeug-Terminal auf einen neuen Beam oder Satelliten umschalten. Die Region Gibraltar/Suedwestspanien liegt am Rand der europaeischen Ku-Band-Coverage, wo typischerweise ein Wechsel auf eine atlantische Coverage-Zone stattfindet. Anuvu's System fuehrt nach Moeglichkeit "make-before-break"-Handovers durch, aber Unterbrechungen von 30-120 Sekunden sind auf Routen, die von europaeischer zu atlantischer Coverage wechseln, dokumentiert [2]. Die Erholung in unserem Test dauerte ~25 Minuten -- deutlich laenger als die typische Handover-Unterbrechung, was auf ein Routing-Problem nach dem Wechsel hindeutet.

### Zweite Stoerung (~15:54 UTC, 30.5N)

Eine zweite, kuerzere Stoerung trat auf, als sich das Flugzeug den Kanaren naeherte. Ping-Timeout auf 8.8.8.8, Download brach auf 0.05 Mbit/s ein. Moeglicherweise ein weiterer Beam-Wechsel innerhalb desselben Satelliten, oder voruebergehende Ueberlastung des Transponders.

### `internetAvailable: false` trotz funktionierender Konnektivitaet

Die Wings Connect API meldet ab Runde 2 konstant, dass Internet nicht verfuegbar sei (`internetUnavailableReason: 1`). Trotzdem funktionieren Ping, DNS und HTTP. Dies deutet darauf hin, dass das Flag den **Portal-/Bezahlzugang** beschreibt (ob der Nutzer eine aktive Session/ein Paket gebucht hat), nicht die technische Konnektivitaet des Satelliten-Links. Reason-Code 1 koennte bedeuten: "kein aktives Internetpaket gekauft".

### Extrem variable DNS-Performance

DNS-Zeiten streuen um Faktor 25 (204-5048ms). Bei geostationaerer Satellitenverbindung betraegt die minimale Round-Trip-Time physikbedingt ~480ms (2 x 36.000 km / Lichtgeschwindigkeit). Eine DNS-Aufloesung erfordert mindestens einen Round-Trip, oft mehrere (Rekursion). Die schnellsten Werte (~200ms) deuten auf lokales Caching hin, die langsamen (~5s) auf Cache-Misses mit mehreren Satelliten-Round-Trips. Ein dedizierter DNS-Resolver im Flugzeug-Gateway mit aggressivem Caching wuerde die User Experience deutlich verbessern.

### Verbindung im Sinkflug

Entgegen der Erwartung blieb die Verbindung waehrend des Sinkflugs (35.200 -> 23.800 ft) stabil. Die Ku-Band-Antenne auf dem Flugzeugdach behaelt die Sichtverbindung zum Satelliten auch in niedrigeren Hoehen bei, solange keine Abschattung durch Fluglage oder Terrain auftritt.

---

## Methodik und Werkzeugwahl

### Warum curl statt iperf3 fuer die Bandbreitenmessung?

**iperf3** waere das praezisere Werkzeug gewesen: Es misst TCP/UDP-Throughput direkt auf der Transportschicht, ohne HTTP-Overhead, und erlaubt parallele Streams fuer eine bessere Saettigung des Links. Allerdings:

1. **Nicht installiert:** iperf3 war auf dem Testsystem nicht vorhanden.
2. **Installation gescheitert:** `choco install iperf3` schlug fehl (keine Admin-Rechte). Der manuelle Download von GitHub scheiterte am Satelliten-Link (TLS-Revocation-Check konnte Revocation-Server nicht erreichen, danach DNS-Ausfall fuer github.com).
3. **Port-Blockierung wahrscheinlich:** Viele In-Flight-WiFi-Systeme blockieren Port 5201 (iperf3-Standard) auf Firewall-Ebene. Nur HTTP/HTTPS (Port 80/443) wird zuverlaessig durchgelassen.

**curl als Alternative** nutzt genau den Pfad, den auch echte Nutzer verwenden (HTTPS/Port 443), und misst damit die *effektiv nutzbare* Bandbreite inkl. TLS-Overhead. Als Testserver dient `speed.cloudflare.com/__down` (Download) und `speed.cloudflare.com/__up` (Upload) -- Cloudflare's offizieller Speed-Test-Endpunkt, der ueberall erreichbar ist und zuverlaessige Ergebnisse liefert.

**Einschraenkung:** curl nutzt standardmaessig einen einzelnen TCP-Stream. Bei hoher Latenz (700-1400ms RTT) limitiert das TCP-Window die Bandbreite. Die realen Werte koennten mit Multistream-Tests (wie iperf3 mit `-P 4`) hoeher ausfallen.

### Weitere Werkzeuge

| Werkzeug | Zweck | Warum gewaehlt |
|----------|-------|----------------|
| `ping` (Windows) | Latenz + Paketverlust | Universell verfuegbar, ICMP auf Layer 3 |
| `nslookup` | DNS-Latenz | Zeitmessung der Namensaufloesung |
| `curl -w` | HTTP-Timing (TTFB, Connect, Total) | Detaillierte Aufschluesselung der HTTP-Phasen |
| `curl` Speed-Test | Bandbreite | Einzige Option nach iperf3-Ausfall |
| `tracert` | Netzwerkpfad | Zeigt Satelliten-Hops und Routing |

### Wings Connect FlightData API

Die API unter `https://www.wingsconnect.aero/map/api/flightData` ist **nur lokal im Flugzeug-Netzwerk erreichbar**. Sie liefert Echtzeit-Flugdaten als JSON (Hoehe, Position, Speed, Flugphase, etc.) und wird von der Moving-Map-Webanwendung des Portals genutzt.

**Wichtige Eigenschaften:**
- **Nicht oeffentlich:** Der Hostname `wingsconnect.aero` ist im Flugzeug-WLAN ein lokaler Captive-Portal-Host. Von ausserhalb ist die API nicht erreichbar (404 oder Timeout).
- **Kein API-Key noetig:** Die API ist unauthentifiziert -- jeder im WLAN kann sie abfragen (kein Token, kein Cookie erforderlich).
- **HTTPS mit selbstsigniertem Zertifikat:** Daher wurde `curl -k` (skip certificate verification) verwendet.
- **Update-Rate:** Die Daten werden alle ~1-2 Sekunden aktualisiert (GPS-basiert).
- **Datenquelle:** Die Daten stammen aus dem ARINC-System des Flugzeugs (Avionik-Datenbus), das GPS-Position, Hoehe, Geschwindigkeit und weitere Parameter an das IFC-System weitergibt. Das Feld `arincAvailable: true` in der API-Antwort bestaetigt dies.
- **Onboard-Server:** Linux-basierte Appliance, die Captive Portal, Content Cache und Moving-Map-Applikation (Angular SPA unter `/status`, REST-API unter `/map/api/flightData`) betreibt [3].
- **`internetAvailable`-Flag:** Gibt den Status des bezahlten Internetzugangs an (nicht die technische Konnektivitaet). `internetUnavailableReason: 1` bedeutet vermutlich "kein aktives Paket/keine Session".

---

## Fazit

Wings Connect auf der A320 (9H-EWG) bietet eine **funktionale Basisverbindung** ueber geostationaeren Ku-Band-Satellit. Die Verbindung reicht fuer:
- E-Mail und Messaging
- Einfaches Webbrowsing (mit Geduld, 3-10s pro Seite)
- Textbasierte Dienste (inkl. Claude Code ueber Satellit!)

**Nicht geeignet fuer:**
- Video-Streaming (0.6 Mbit/s avg reicht nicht fuer SD-Video, das min. 1.5 Mbit/s braucht)
- Videocalls (Latenz 700-1400ms + Jitter macht Echtzeitkommunikation unmoeglich)
- Grosse Downloads (ein 100 MB Update wuerde ~22 Minuten dauern)
- Echtzeitanwendungen / Online-Gaming

### Einordnung im Markt

Die gemessene Leistung entspricht dem typischen Niveau von **Ku-Band Satelliten-IFC der aelteren Generation**. Anuvu (ehemals Global Eagle Entertainment) betreibt eines der aeltesten IFC-Systeme in der europaeischen Luftfahrt. Die pro Flugzeug verfuegbare Kapazitaet liegt laut Branchenquellen bei 30-50 Mbit/s Ku-Band-HTS, geteilt auf alle Passagiere -- bei 180 Sitzen erklaert das die niedrigen Einzelnutzer-Werte [1][3]. Im Vergleich:

| Anbieter | Technologie | Typischer Download | Latenz |
|----------|-------------|-------------------|--------|
| **Wings Connect (Anuvu)** | **Ku-Band GEO** | **0.5-1.5 Mbit/s** | **700-1400 ms** |
| Inmarsat GX (Lufthansa) | Ka-Band GEO | 5-15 Mbit/s | 600-800 ms |
| Viasat (United) | Ka-Band GEO | 10-30 Mbit/s | 500-700 ms |
| Starlink Aviation | LEO-Konstellation | 50-200 Mbit/s | 30-80 ms |

Die naechste Generation (Ka-Band / LEO-Satellit wie Starlink Aviation) wuerde um Faktor 10-100 bessere Werte liefern. Mehrere Airlines (JSX, Hawaiian, zipair) setzen bereits auf Starlink fuer ihr IFC.

---

---

## Quellen

1. Anuvu Aviation Connectivity: https://www.anuvu.com/connectivity/aviation/ -- Satelliten-Partner (SES, Eutelsat), Ku-Band-Technologie
2. Runway Girl Network / Anuvu: https://runwaygirlnetwork.com/tag/anuvu/ -- Handover-Berichte, Coverage-Diskussion
3. Runway Girl Network (2022): https://runwaygirlnetwork.com/2022/01/anuvu-plots-a-new-course-for-inflight-connectivity/ -- Technologie-Stack, Onboard-Server-Architektur
4. ThinKom Solutions (Antennen-Partner): https://www.thinkom.com/aviation
5. Eurowings WiFi-Info: https://www.eurowings.com/en/information/onboard/wifi.html

---

*Bericht erstellt: 2026-03-31 15:49-16:01 UTC an Bord EWG39C*
*Messwerkzeug: test_connection.sh (Bash) | 22 Messrunden ueber 77 Minuten*
*Rohdaten: logs/wingsconnect_2026-03-31_*.csv*
