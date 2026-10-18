#!/usr/bin/env bash
# ============================================================
# Wings Connect – Verbindungsqualität testen
# Misst: Latenz, Paketverlust, DNS, HTTP-Latenzen, Bandbreite
#        (curl, optional iperf3) plus Flugdaten via lokale API
#
# Dateien pro Tag und Flug: logs/wingsconnect_<Datum>_<Flug>.{log,csv,jsonl}
# Ein Neustart am selben Tag hängt an die vorhandenen Dateien an.
# ============================================================

# --- Konfiguration (per Umgebungsvariable überschreibbar) ---
INTERVAL="${INTERVAL:-120}"             # Sekunden Pause zwischen Messrunden
PING_COUNT="${PING_COUNT:-10}"          # Ping-Pakete pro Host
IPERF_DURATION="${IPERF_DURATION:-5}"   # Sekunden pro iperf3-Richtung
IPERF_PORT="${IPERF_PORT:-5201}"
LOG_DIR="./logs"
FLIGHT_ID="test"                        # --flight EW9444
USE_IPERF=1                             # --no-iperf
MODE="loop"                             # loop | once | traceroute

PING_HOSTS=(
  "8.8.8.8"           # Google DNS
  "1.1.1.1"           # Cloudflare DNS
)

HTTP_URLS=(
  "https://www.google.com"
  "https://www.cloudflare.com"
)

# Wings Connect lokale Flugdaten-API (nur im Flugzeug-WLAN erreichbar)
FLIGHT_API="https://www.wingsconnect.aero/map/api/flightData"

# Öffentliche iperf3-Server (Reihenfolge = Priorität)
IPERF_SERVERS=(
  "bouygues.iperf.fr"
  "paris.testdebit.info"
  "ping.online.net"
  "iperf.he.net"
)

# JSON-Parsing via Python (zuverlässig bei verschachteltem JSON)
PYTHON="${PYTHON:-/c/Python313/python}"
command -v "$PYTHON" &>/dev/null || PYTHON=python

# --- Farben (echte ESC-Bytes, damit der Strip im Logfile greift) ---
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

# --- Argumente ---
usage() {
  cat <<EOF
Verwendung: bash test_connection.sh [Optionen]
  --flight ID, -f ID    Flugnummer für die Dateinamen (z.B. EW9444), Standard: test
  --once, -1            Nur eine Messrunde
  --traceroute, -t      Nur Traceroute
  --interval N, -i N    Sekunden Pause zwischen Runden (Standard: ${INTERVAL})
  --no-iperf            iperf3-Test überspringen (Bandbreite nur per curl)
  --help, -h            Diese Hilfe

Dateien: logs/wingsconnect_<Datum>_<ID>.log / .csv / .jsonl
Ein Neustart am selben Tag mit derselben ID hängt an (Rundenzähler läuft weiter).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --flight | -f)     FLIGHT_ID="$2"; shift ;;
    --interval | -i)   INTERVAL="$2"; shift ;;
    --once | -1)       MODE="once" ;;
    --traceroute | -t) MODE="traceroute" ;;
    --no-iperf)        USE_IPERF=0 ;;
    --help | -h)       usage; exit 0 ;;
    *) echo "Unbekannte Option: $1"; echo; usage; exit 1 ;;
  esac
  shift
done

FLIGHT_ID=$(printf '%s' "$FLIGHT_ID" | tr -cd 'A-Za-z0-9_-')
[ -z "$FLIGHT_ID" ] && FLIGHT_ID="test"

BASE_NAME="$LOG_DIR/wingsconnect_$(date +%Y-%m-%d)_${FLIGHT_ID}"
LOG_FILE="$BASE_NAME.log"
CSV_FILE="$BASE_NAME.csv"
JSONL_FILE="$BASE_NAME.jsonl"

# --- Hilfsfunktionen ---
mkdir -p "$LOG_DIR"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  printf '%s\n' "$msg"
  # ANSI-Farbcodes für die Logdatei entfernen
  printf '%s\n' "$msg" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

separator() {
  local line="$(printf '=%.0s' {1..60})"
  printf '%s\n' "${CYAN}${line}${RESET}"
  echo "$line" >> "$LOG_FILE"
}

check_command() {
  command -v "$1" &>/dev/null
}

# --- CSV / Resume ---
CSV_HEADER="timestamp_local,timestamp_utc,round,callsign,registration,aircraft_type,flight_phase,altitude_ft,ground_speed_kts,heading_deg,temperature_c,lat,lon,dist_dest_nm,eta,elapsed_flight_time,internet_available,internet_unavailable_reason,ping_8888_avg_ms,ping_8888_loss_pct,ping_1111_avg_ms,ping_1111_loss_pct,dns_google_ms,dns_cloudflare_ms,http_google_ttfb_s,http_google_total_s,http_cloudflare_ttfb_s,http_cloudflare_total_s,curl_dl_mbps,curl_ul_mbps,iperf_dl_mbps,iperf_ul_mbps,iperf_server"

init_files() {
  START_ROUND=1
  RESUMED=0
  if [ -s "$CSV_FILE" ]; then
    # Rundenzähler aus der letzten CSV-Zeile fortführen (Spalte 3)
    local last
    last=$(tail -n 1 "$CSV_FILE" | cut -d',' -f3)
    [[ "$last" =~ ^[0-9]+$ ]] && START_ROUND=$((last + 1))
    RESUMED=1
  else
    echo "$CSV_HEADER" > "$CSV_FILE"
  fi
}

# --- Flugdaten ---
reset_flight_vars() {
  FLIGHT_CALLSIGN="N/A"; FLIGHT_REG="N/A"; FLIGHT_TYPE="N/A"; FLIGHT_PHASE="N/A"
  FLIGHT_ALT="N/A"; FLIGHT_SPEED="N/A"; FLIGHT_HEADING="N/A"; FLIGHT_TEMP="N/A"
  FLIGHT_LAT="N/A"; FLIGHT_LON="N/A"; FLIGHT_DIST="N/A"; FLIGHT_ETA="N/A"
  FLIGHT_ELAPSED="N/A"; FLIGHT_INET="N/A"; FLIGHT_INET_REASON="N/A"
}

# Liest die API-Antwort von stdin, hängt sie roh ans JSONL an und gibt
# shell-sichere KEY=value-Zeilen für eval aus (ein Python-Aufruf statt 15).
parse_flight_json() {
  "$PYTHON" -I -c '
import sys, json, shlex
jsonl, rnd, ts_local, ts_utc = sys.argv[1:5]
fields = {
    "FLIGHT_CALLSIGN": "callSign", "FLIGHT_REG": "aircraftRegistration",
    "FLIGHT_TYPE": "aircraftType", "FLIGHT_PHASE": "flightPhase",
    "FLIGHT_ALT": "altitude", "FLIGHT_SPEED": "groundSpeed",
    "FLIGHT_HEADING": "heading", "FLIGHT_TEMP": "temperature",
    "FLIGHT_LAT": "lat", "FLIGHT_LON": "lon", "FLIGHT_DIST": "distDest",
    "FLIGHT_ETA": "eta", "FLIGHT_ELAPSED": "elapsedFlightTime",
    "FLIGHT_INET": "internetAvailable",
    "FLIGHT_INET_REASON": "internetUnavailableReason",
}
try:
    d = json.load(sys.stdin)
    assert isinstance(d, dict) and "altitude" in d
except Exception:
    print("FLIGHT_OK=0")
    sys.exit(0)
with open(jsonl, "a", encoding="utf-8") as f:
    f.write(json.dumps({"ts_local": ts_local, "ts_utc": ts_utc,
                        "round": int(rnd), "flight": d}) + "\n")
print("FLIGHT_OK=1")
for var, key in fields.items():
    v = d.get(key)
    if isinstance(v, bool):
        v = "true" if v else "false"
    elif isinstance(v, float):
        v = ("%.5f" % v) if key in ("lat", "lon") else ("%.1f" % v)
    elif v is None:
        v = ""
    print(var + "=" + shlex.quote(str(v)))
' "$JSONL_FILE" "$ROUND" "$1" "$2" 2>/dev/null
}

test_flight_data() {
  log "${BOLD}[FLUGDATEN]${RESET}"
  local json ts_local ts_utc
  ts_local=$(date '+%Y-%m-%d %H:%M:%S')
  ts_utc=$(date -u '+%Y-%m-%d %H:%M:%S')
  json=$(curl -s -k --max-time 5 "$FLIGHT_API" 2>/dev/null)

  reset_flight_vars
  FLIGHT_OK=0
  [ -n "$json" ] && eval "$(printf '%s' "$json" | parse_flight_json "$ts_local" "$ts_utc")"

  if [ "$FLIGHT_OK" != "1" ]; then
    log "  ${RED}Flugdaten nicht verfügbar${RESET} (API nur im Flugzeug-WLAN erreichbar)"
    return
  fi

  local inet_txt
  if [ "$FLIGHT_INET" = "true" ]; then
    inet_txt="${GREEN}verfügbar${RESET}"
  else
    inet_txt="${RED}nicht verfügbar${RESET} (Code ${FLIGHT_INET_REASON:-?}; Flag = Portal-/Bezahlstatus, nicht der Link)"
  fi

  log "  Callsign:    ${GREEN}${FLIGHT_CALLSIGN}${RESET}  (${FLIGHT_REG}, ${FLIGHT_TYPE})"
  log "  Flugphase:   ${GREEN}${FLIGHT_PHASE}${RESET}  |  Flugzeit: ${FLIGHT_ELAPSED}"
  log "  Höhe:        ${GREEN}${FLIGHT_ALT} ft${RESET}"
  log "  Geschw.:     ${GREEN}${FLIGHT_SPEED} kts${RESET}  |  Kurs: ${FLIGHT_HEADING}°"
  log "  Temperatur:  ${FLIGHT_TEMP} °C"
  log "  Position:    ${FLIGHT_LAT}, ${FLIGHT_LON}"
  log "  Ziel-Dist.:  ${FLIGHT_DIST} nm  |  ETA: ${FLIGHT_ETA} (API-Zeit, vermutlich UTC)"
  log "  Internet:    ${inet_txt}"
}

# --- Ping ---
test_ping() {
  log "${BOLD}[PING / PAKETVERLUST]${RESET}"
  PING_RESULTS=()
  for host in "${PING_HOSTS[@]}"; do
    local result avg loss
    result=$(ping -n "$PING_COUNT" "$host" 2>&1)

    # Mittelwert (DE: "Mittelwert = 670ms" / EN: "Average = 670ms")
    avg=$(echo "$result" | grep -iE "Average|Mittelwert" | grep -oE '[0-9]+ms' | tail -1)
    # Paketverlust direkt als Prozentwert (DE: "(30% Verlust)" / EN: "(30% loss)")
    loss=$(echo "$result" | grep -oE '[0-9]+%' | head -1 | tr -d '%')

    if [ -n "$avg" ]; then
      local avg_num=$(echo "$avg" | tr -d 'ms')
      log "  $host → Avg: ${GREEN}${avg}${RESET}  Verlust: ${loss:-0}%"
      PING_RESULTS+=("${avg_num},${loss:-0}")
    else
      log "  $host → ${RED}nicht erreichbar${RESET}"
      PING_RESULTS+=("timeout,100")
    fi
  done
}

# --- DNS ---
test_dns() {
  log "${BOLD}[DNS-AUFLÖSUNG]${RESET}"
  DNS_RESULTS=()
  local domains=("google.com" "cloudflare.com")
  for domain in "${domains[@]}"; do
    local start end duration
    start=$(date +%s%3N)
    if nslookup "$domain" &>/dev/null; then
      end=$(date +%s%3N)
      duration=$((end - start))
      log "  $domain → ${GREEN}${duration}ms${RESET}"
      DNS_RESULTS+=("$duration")
    else
      log "  $domain → ${RED}Fehler${RESET}"
      DNS_RESULTS+=("error")
    fi
  done
}

# --- HTTP ---
test_http() {
  log "${BOLD}[HTTP-LATENZ]${RESET}"
  HTTP_RESULTS=()
  for url in "${HTTP_URLS[@]}"; do
    local result ttfb total http_code
    result=$(curl -o /dev/null -s -w \
      "%{time_starttransfer},%{time_total},%{http_code}" \
      --max-time 15 "$url" 2>&1)

    ttfb=$(echo "$result" | cut -d',' -f1)
    total=$(echo "$result" | cut -d',' -f2)
    http_code=$(echo "$result" | cut -d',' -f3)

    if [ "$http_code" = "200" ] || [ "$http_code" = "301" ] || [ "$http_code" = "302" ]; then
      local detail
      detail=$(curl -o /dev/null -s -w \
        "DNS:%{time_namelookup}s  Connect:%{time_connect}s  TTFB:%{time_starttransfer}s  Total:%{time_total}s  HTTP:%{http_code}" \
        --max-time 15 "$url" 2>&1)
      log "  $url"
      log "    ${detail}"
      HTTP_RESULTS+=("${ttfb},${total}")
    else
      log "  $url → ${RED}Fehler (HTTP:${http_code})${RESET}"
      HTTP_RESULTS+=("error,error")
    fi
  done
}

# --- Bandbreite per curl (HTTPS/443, wie echte Nutzer; vergleichbar mit Flug 1) ---
test_bandwidth_curl() {
  log "${BOLD}[BANDBREITE (curl)]${RESET}"
  CURL_DL="N/A"
  CURL_UL="N/A"

  local dl_urls=(
    "https://speed.cloudflare.com/__down?bytes=5000000"
    "https://proof.ovh.net/files/1Mb.dat"
  )

  for dl_url in "${dl_urls[@]}"; do
    log "  Download-Test: $(echo "$dl_url" | cut -d'/' -f3) ..."
    local dl_result dl_bytes dl_time dl_code
    dl_result=$(curl -o /dev/null -s -w "%{size_download},%{time_total},%{http_code}" \
      --max-time 30 --ssl-no-revoke "$dl_url" 2>&1)
    dl_bytes=$(echo "$dl_result" | cut -d',' -f1)
    dl_time=$(echo "$dl_result" | cut -d',' -f2)
    dl_code=$(echo "$dl_result" | cut -d',' -f3)

    if [ "$dl_code" = "200" ] && [ "$dl_bytes" -gt 0 ] 2>/dev/null; then
      CURL_DL=$(awk "BEGIN {printf \"%.2f\", ($dl_bytes * 8) / ($dl_time * 1000000)}")
      log "  ${GREEN}Download: ${CURL_DL} Mbit/s${RESET} (${dl_bytes} bytes in ${dl_time}s)"
      break
    else
      log "  ${YELLOW}Fehlgeschlagen (HTTP:${dl_code})${RESET}"
    fi
  done

  log "  Upload-Test: speed.cloudflare.com ..."
  local ul_result ul_bytes ul_time
  ul_result=$(dd if=/dev/urandom bs=1024 count=512 2>/dev/null | \
    curl -o /dev/null -s -w "%{size_upload},%{time_total},%{http_code}" \
    --max-time 30 --ssl-no-revoke \
    -X POST -H "Content-Type: application/octet-stream" \
    --data-binary @- "https://speed.cloudflare.com/__up" 2>&1)
  ul_bytes=$(echo "$ul_result" | cut -d',' -f1)
  ul_time=$(echo "$ul_result" | cut -d',' -f2)

  if [ "$ul_bytes" -gt 0 ] 2>/dev/null && [ -n "$ul_time" ]; then
    CURL_UL=$(awk "BEGIN {printf \"%.2f\", ($ul_bytes * 8) / ($ul_time * 1000000)}")
    log "  ${GREEN}Upload:   ${CURL_UL} Mbit/s${RESET} (${ul_bytes} bytes in ${ul_time}s)"
  else
    log "  ${YELLOW}Upload-Test fehlgeschlagen${RESET}"
  fi
}

# --- Bandbreite per iperf3 (TCP-Durchsatz ohne HTTP-Overhead; Port 5201 evtl. gesperrt) ---
IPERF_FAILS=0

iperf_mbps() {
  # stdin: iperf3 -J Ausgabe → Mbit/s (sum_received) oder leer bei Fehler
  "$PYTHON" -I -c '
import sys, json
try:
    d = json.load(sys.stdin)
    if "error" in d:
        sys.exit(0)
    print("%.2f" % (d["end"]["sum_received"]["bits_per_second"] / 1e6))
except Exception:
    pass
' 2>/dev/null
}

iperf_run() {
  # $1 = Server, weitere Argumente gehen an iperf3 (z.B. -R für Download)
  timeout $((IPERF_DURATION + 10)) iperf3 -c "$1" -p "$IPERF_PORT" -t "$IPERF_DURATION" \
    --connect-timeout 5000 -J "${@:2}" 2>/dev/null | iperf_mbps
}

test_iperf() {
  log "${BOLD}[BANDBREITE (iperf3)]${RESET}"
  IPERF_DL="N/A"; IPERF_UL="N/A"; IPERF_SRV="N/A"

  if ! check_command iperf3; then
    log "  ${YELLOW}iperf3 nicht installiert – überspringe${RESET}"
    return
  fi
  # Nach Fehlschlag nur jede 5. Runde erneut probieren (spart Zeit bei gesperrtem Port)
  if [ "$IPERF_FAILS" -gt 0 ] && [ $((ROUND % 5)) -ne 0 ]; then
    log "  ${YELLOW}übersprungen (letzter Versuch fehlgeschlagen, nächster in Runde $(( (ROUND / 5 + 1) * 5 )))${RESET}"
    return
  fi

  for srv in "${IPERF_SERVERS[@]}"; do
    log "  Server: $srv ..."
    local dl ul
    dl=$(iperf_run "$srv" -R)
    if [ -z "$dl" ]; then
      log "    ${YELLOW}nicht erreichbar oder belegt${RESET}"
      continue
    fi
    # Server braucht kurz Luft, sonst lehnt er den zweiten Test ab → Pause + ein Retry
    sleep 2
    ul=$(iperf_run "$srv")
    if [ -z "$ul" ]; then
      sleep 3
      ul=$(iperf_run "$srv")
    fi
    IPERF_DL="$dl"; IPERF_UL="${ul:-N/A}"; IPERF_SRV="$srv"
    IPERF_FAILS=0
    log "  ${GREEN}Download: ${IPERF_DL} Mbit/s  Upload: ${IPERF_UL} Mbit/s${RESET} (${IPERF_DURATION}s je Richtung)"
    return
  done

  IPERF_FAILS=$((IPERF_FAILS + 1))
  log "  ${YELLOW}kein iperf3-Server erreichbar (Port ${IPERF_PORT} vermutlich gesperrt)${RESET}"
}

# --- Traceroute ---
test_traceroute() {
  log "${BOLD}[TRACEROUTE → 8.8.8.8]${RESET}"
  local result
  if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* ]]; then
    # tracert schreibt in der OEM-Codepage (850) → nach UTF-8 wandeln
    result=$(tracert -d -h 20 -w 3000 "8.8.8.8" 2>&1 | iconv -f CP850 -t UTF-8 2>/dev/null || tracert -d -h 20 -w 3000 "8.8.8.8" 2>&1)
  else
    result=$(traceroute -n -m 20 -w 2 "8.8.8.8" 2>&1)
  fi
  echo "$result" | head -25 | tee -a "$LOG_FILE"
}

# --- CSV-Zeile ---
write_csv_row() {
  local ts_local ts_utc
  ts_local=$(date '+%Y-%m-%d %H:%M:%S')
  ts_utc=$(date -u '+%Y-%m-%d %H:%M:%S')

  local p1_avg p1_loss p2_avg p2_loss
  p1_avg=$(echo "${PING_RESULTS[0]:-N/A,N/A}" | cut -d',' -f1)
  p1_loss=$(echo "${PING_RESULTS[0]:-N/A,N/A}" | cut -d',' -f2)
  p2_avg=$(echo "${PING_RESULTS[1]:-N/A,N/A}" | cut -d',' -f1)
  p2_loss=$(echo "${PING_RESULTS[1]:-N/A,N/A}" | cut -d',' -f2)

  local dns1="${DNS_RESULTS[0]:-N/A}"
  local dns2="${DNS_RESULTS[1]:-N/A}"

  local h1_ttfb h1_total h2_ttfb h2_total
  h1_ttfb=$(echo "${HTTP_RESULTS[0]:-N/A,N/A}" | cut -d',' -f1)
  h1_total=$(echo "${HTTP_RESULTS[0]:-N/A,N/A}" | cut -d',' -f2)
  h2_ttfb=$(echo "${HTTP_RESULTS[1]:-N/A,N/A}" | cut -d',' -f1)
  h2_total=$(echo "${HTTP_RESULTS[1]:-N/A,N/A}" | cut -d',' -f2)

  echo "${ts_local},${ts_utc},${ROUND},${FLIGHT_CALLSIGN},${FLIGHT_REG},${FLIGHT_TYPE},${FLIGHT_PHASE},${FLIGHT_ALT},${FLIGHT_SPEED},${FLIGHT_HEADING},${FLIGHT_TEMP},${FLIGHT_LAT},${FLIGHT_LON},${FLIGHT_DIST},${FLIGHT_ETA},${FLIGHT_ELAPSED},${FLIGHT_INET},${FLIGHT_INET_REASON},${p1_avg},${p1_loss},${p2_avg},${p2_loss},${dns1},${dns2},${h1_ttfb},${h1_total},${h2_ttfb},${h2_total},${CURL_DL},${CURL_UL},${IPERF_DL:-N/A},${IPERF_UL:-N/A},${IPERF_SRV:-N/A}" >> "$CSV_FILE"
}

# --- Eine komplette Messrunde ---
run_round() {
  separator
  log "${BOLD}=== MESSRUNDE #${ROUND} (${FLIGHT_ID}) ===${RESET}"
  separator

  test_flight_data; echo ""
  test_ping; echo ""
  test_dns; echo ""
  test_http; echo ""
  test_bandwidth_curl
  if [ "$USE_IPERF" = 1 ]; then
    echo ""
    test_iperf
  fi

  write_csv_row
}

print_header() {
  printf '%s\n' "${BOLD}${CYAN}"
  echo "  ██╗    ██╗██╗███╗   ██╗ ██████╗ ███████╗"
  echo "  ██║    ██║██║████╗  ██║██╔════╝ ██╔════╝"
  echo "  ██║ █╗ ██║██║██╔██╗ ██║██║  ███╗███████╗"
  echo "  ██║███╗██║██║██║╚██╗██║██║   ██║╚════██║"
  echo "  ╚███╔███╔╝██║██║ ╚████║╚██████╔╝███████║"
  echo "   ╚══╝╚══╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚══════╝"
  printf '%s\n' "  Wings Connect – Verbindungstest${RESET}"
  echo ""
  log "Flug: ${BOLD}${FLIGHT_ID}${RESET}  |  Start: $(date '+%Y-%m-%d %H:%M:%S') lokal / $(date -u '+%H:%M:%S') UTC"
  log "Log:   $LOG_FILE"
  log "CSV:   $CSV_FILE"
  log "JSONL: $JSONL_FILE (rohe API-Antworten)"
  log "Intervall: ${INTERVAL}s | Ping-Pakete: ${PING_COUNT} | iperf3: $([ "$USE_IPERF" = 1 ] && echo "an (${IPERF_DURATION}s je Richtung)" || echo "aus")"
  if [ "$RESUMED" = 1 ]; then
    log "${YELLOW}Vorhandene Dateien gefunden – Messung wird ab Runde #${START_ROUND} fortgesetzt${RESET}"
  fi
}

finish() {
  echo ""
  log "Messung beendet. Letzte Runde: #${ROUND}"
  log "Log: $LOG_FILE"
  log "CSV: $CSV_FILE"
  exit 0
}

# --- Hauptprogramm ---
case "$MODE" in
  traceroute)
    test_traceroute
    ;;
  once)
    init_files
    ROUND=$START_ROUND
    print_header
    run_round
    separator
    log "Einzelmessung abgeschlossen (Runde #${ROUND})."
    log "Log: $LOG_FILE"
    log "CSV: $CSV_FILE"
    ;;
  loop)
    init_files
    ROUND=$START_ROUND
    print_header
    trap finish INT TERM

    separator
    log "${BOLD}=== TRACEROUTE (einmalig zu Beginn) ===${RESET}"
    test_traceroute

    while true; do
      run_round
      separator
      log "Runde #${ROUND} abgeschlossen. Nächste in ${INTERVAL}s (Strg+C = Ende)"
      separator
      echo ""
      ROUND=$((ROUND + 1))
      sleep "$INTERVAL"
    done
    ;;
esac
