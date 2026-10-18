#!/usr/bin/env bash
# ============================================================
# Wings Connect – Verbindungsqualität testen
# Misst: Latenz, Paketverlust, DNS, HTTP-Latenzen, iperf3,
#        plus Flugdaten (Höhe, Speed, Position) via lokale API
# ============================================================

# --- Konfiguration ---
INTERVAL=120          # Sekunden zwischen Messrunden (2 Min.)
PING_COUNT=10         # Ping-Pakete pro Host
LOG_DIR="./logs"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/wingsconnect_$TIMESTAMP.log"
CSV_FILE="$LOG_DIR/wingsconnect_$TIMESTAMP.csv"

PING_HOSTS=(
  "8.8.8.8"           # Google DNS
  "1.1.1.1"           # Cloudflare DNS
)

HTTP_URLS=(
  "https://www.google.com"
  "https://www.cloudflare.com"
)

# Wings Connect lokale Flugdaten-API
FLIGHT_API="https://www.wingsconnect.aero/map/api/flightData"

# Öffentliche iperf3-Server (Fallback-Liste)
IPERF_SERVERS=(
  "bouygues.iperf.fr"
  "ping.online.net"
  "iperf.he.net"
)
IPERF_PORT=5201
IPERF_DURATION=10     # Sekunden pro iperf3-Test

# --- Farben für Terminal ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# --- Hilfsfunktionen ---
mkdir -p "$LOG_DIR"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  echo -e "$msg"
  # Strip ANSI codes for log file
  echo "$msg" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

separator() {
  local line="$(printf '=%.0s' {1..60})"
  echo -e "${CYAN}${line}${RESET}"
  echo "$line" >> "$LOG_FILE"
}

check_command() {
  command -v "$1" &>/dev/null
}

# JSON-Werte extrahieren via Python (zuverlässig bei verschachteltem JSON)
PYTHON="/c/Python313/python"

json_val() {
  local json="$1" key="$2"
  echo "$json" | "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    v = d.get('$key', '')
    print(v if v is not None else '')
except: print('')
" 2>/dev/null
}

# --- CSV-Header schreiben ---
init_csv() {
  echo "timestamp,round,altitude_ft,ground_speed_kts,temperature_c,lat,lon,flight_phase,dist_dest_nm,eta,ping_8888_avg_ms,ping_8888_loss_pct,ping_1111_avg_ms,ping_1111_loss_pct,dns_google_ms,dns_cloudflare_ms,http_google_ttfb_s,http_google_total_s,http_cloudflare_ttfb_s,http_cloudflare_total_s,iperf_dl_mbps,iperf_ul_mbps" > "$CSV_FILE"
}

# --- Einzelne Messtests ---

test_flight_data() {
  log "${BOLD}[FLUGDATEN]${RESET}"
  local flight_json
  flight_json=$(curl -s -k --max-time 5 "$FLIGHT_API" 2>&1)

  if [ -z "$flight_json" ] || echo "$flight_json" | grep -qi "error\|not found"; then
    log "  ${RED}Flugdaten nicht verfügbar${RESET}"
    FLIGHT_ALT="N/A"; FLIGHT_SPEED="N/A"; FLIGHT_TEMP="N/A"
    FLIGHT_LAT="N/A"; FLIGHT_LON="N/A"; FLIGHT_PHASE="N/A"
    FLIGHT_DIST="N/A"; FLIGHT_ETA="N/A"
    return
  fi

  FLIGHT_ALT=$(json_val "$flight_json" "altitude")
  FLIGHT_SPEED=$(json_val "$flight_json" "groundSpeed")
  FLIGHT_TEMP=$(json_val "$flight_json" "temperature")
  FLIGHT_LAT=$(json_val "$flight_json" "lat")
  FLIGHT_LON=$(json_val "$flight_json" "lon")
  FLIGHT_PHASE=$(json_val "$flight_json" "flightPhase")
  FLIGHT_DIST=$(json_val "$flight_json" "distDest" | cut -c1-7)
  FLIGHT_ETA=$(json_val "$flight_json" "eta")
  local callsign=$(json_val "$flight_json" "callSign")
  local reg=$(json_val "$flight_json" "aircraftRegistration")
  local inet=$(json_val "$flight_json" "internetAvailable")

  log "  Callsign:    ${GREEN}${callsign}${RESET}  (${reg})"
  log "  Flugphase:   ${GREEN}${FLIGHT_PHASE}${RESET}"
  log "  Höhe:        ${GREEN}${FLIGHT_ALT} ft${RESET}"
  log "  Geschw.:     ${GREEN}${FLIGHT_SPEED} kts${RESET}"
  log "  Temperatur:  ${FLIGHT_TEMP} °C"
  log "  Position:    ${FLIGHT_LAT}, ${FLIGHT_LON}"
  log "  Ziel-Dist.:  ${FLIGHT_DIST} nm  |  ETA: ${FLIGHT_ETA}"
  log "  Internet:    $([ "$inet" = "true" ] && echo "${GREEN}verfügbar${RESET}" || echo "${RED}nicht verfügbar${RESET}")"
}

test_ping() {
  log "${BOLD}[PING / PAKETVERLUST]${RESET}"
  PING_RESULTS=()
  for host in "${PING_HOSTS[@]}"; do
    local result avg loss
    result=$(ping -n "$PING_COUNT" "$host" 2>&1)

    # Mittelwert extrahieren (DE: "Mittelwert = 670ms" / EN: "Average = 670ms")
    avg=$(echo "$result" | grep -iE "Average|Mittelwert" | grep -oE '[0-9]+ms' | tail -1)
    # Paketverlust extrahieren (DE: "(0% Verlust)" / EN: "(0% loss)")
    loss=$(echo "$result" | grep -iE "Lost|Verloren" | grep -oE '[0-9]+' | head -3 | tail -1)

    # Fallback: Verlust aus Prozent-Zeile
    if [ -z "$loss" ]; then
      loss=$(echo "$result" | grep -oE '[0-9]+%' | head -1 | tr -d '%')
    fi

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

test_dns() {
  log "${BOLD}[DNS-AUFLÖSUNG]${RESET}"
  DNS_RESULTS=()
  local domains=("google.com" "cloudflare.com")
  for domain in "${domains[@]}"; do
    local start end duration
    start=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")
    if nslookup "$domain" &>/dev/null; then
      end=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")
      duration=$((end - start))
      log "  $domain → ${GREEN}${duration}ms${RESET}"
      DNS_RESULTS+=("$duration")
    else
      log "  $domain → ${RED}Fehler${RESET}"
      DNS_RESULTS+=("error")
    fi
  done
}

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

test_bandwidth() {
  log "${BOLD}[BANDBREITE (curl)]${RESET}"
  IPERF_DL="N/A"
  IPERF_UL="N/A"

  # --- DOWNLOAD ---
  # Testet gegen mehrere Quellen (Cloudflare ist am zuverlässigsten über Sat.)
  local dl_urls=(
    "https://speed.cloudflare.com/__down?bytes=5000000"
    "https://proof.ovh.net/files/1Mb.dat"
  )

  for dl_url in "${dl_urls[@]}"; do
    log "  Download-Test: $(echo "$dl_url" | cut -d'/' -f3) ..."
    local dl_result
    dl_result=$(curl -o /dev/null -s -w "%{size_download},%{time_total},%{http_code}" \
      --max-time 30 --ssl-no-revoke "$dl_url" 2>&1)

    local dl_bytes dl_time dl_code
    dl_bytes=$(echo "$dl_result" | cut -d',' -f1)
    dl_time=$(echo "$dl_result" | cut -d',' -f2)
    dl_code=$(echo "$dl_result" | cut -d',' -f3)

    if [ "$dl_code" = "200" ] && [ "$dl_bytes" -gt 0 ] 2>/dev/null; then
      IPERF_DL=$(awk "BEGIN {printf \"%.2f\", ($dl_bytes * 8) / ($dl_time * 1000000)}")
      log "  ${GREEN}Download: ${IPERF_DL} Mbit/s${RESET} (${dl_bytes} bytes in ${dl_time}s)"
      break
    else
      log "  ${YELLOW}Fehlgeschlagen (HTTP:${dl_code})${RESET}"
    fi
  done

  # --- UPLOAD ---
  # Generiere Testdaten und sende sie an Cloudflare Speed
  log "  Upload-Test: speed.cloudflare.com ..."
  local ul_result
  ul_result=$(dd if=/dev/urandom bs=1024 count=512 2>/dev/null | \
    curl -o /dev/null -s -w "%{size_upload},%{time_total},%{http_code}" \
    --max-time 30 --ssl-no-revoke \
    -X POST -H "Content-Type: application/octet-stream" \
    --data-binary @- "https://speed.cloudflare.com/__up" 2>&1)

  local ul_bytes ul_time ul_code
  ul_bytes=$(echo "$ul_result" | cut -d',' -f1)
  ul_time=$(echo "$ul_result" | cut -d',' -f2)
  ul_code=$(echo "$ul_result" | cut -d',' -f3)

  if [ "$ul_bytes" -gt 0 ] 2>/dev/null && [ -n "$ul_time" ]; then
    IPERF_UL=$(awk "BEGIN {printf \"%.2f\", ($ul_bytes * 8) / ($ul_time * 1000000)}")
    log "  ${GREEN}Upload:   ${IPERF_UL} Mbit/s${RESET} (${ul_bytes} bytes in ${ul_time}s)"
  else
    log "  ${YELLOW}Upload-Test fehlgeschlagen${RESET}"
  fi
}

test_traceroute() {
  log "${BOLD}[TRACEROUTE → 8.8.8.8]${RESET}"
  local result
  if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* ]]; then
    result=$(tracert -d -h 20 -w 3000 "8.8.8.8" 2>&1 | head -25)
  else
    result=$(traceroute -n -m 20 -w 2 "8.8.8.8" 2>&1 | head -25)
  fi
  echo "$result" | tee -a "$LOG_FILE"
}

# --- CSV-Zeile schreiben ---
write_csv_row() {
  local round="$1"
  local ts=$(date '+%Y-%m-%d %H:%M:%S')

  # Ping-Daten aufbereiten
  local p1_avg p1_loss p2_avg p2_loss
  p1_avg=$(echo "${PING_RESULTS[0]:-N/A,N/A}" | cut -d',' -f1)
  p1_loss=$(echo "${PING_RESULTS[0]:-N/A,N/A}" | cut -d',' -f2)
  p2_avg=$(echo "${PING_RESULTS[1]:-N/A,N/A}" | cut -d',' -f1)
  p2_loss=$(echo "${PING_RESULTS[1]:-N/A,N/A}" | cut -d',' -f2)

  # DNS-Daten
  local dns1="${DNS_RESULTS[0]:-N/A}"
  local dns2="${DNS_RESULTS[1]:-N/A}"

  # HTTP-Daten
  local h1_ttfb h1_total h2_ttfb h2_total
  h1_ttfb=$(echo "${HTTP_RESULTS[0]:-N/A,N/A}" | cut -d',' -f1)
  h1_total=$(echo "${HTTP_RESULTS[0]:-N/A,N/A}" | cut -d',' -f2)
  h2_ttfb=$(echo "${HTTP_RESULTS[1]:-N/A,N/A}" | cut -d',' -f1)
  h2_total=$(echo "${HTTP_RESULTS[1]:-N/A,N/A}" | cut -d',' -f2)

  echo "${ts},${round},${FLIGHT_ALT},${FLIGHT_SPEED},${FLIGHT_TEMP},${FLIGHT_LAT},${FLIGHT_LON},${FLIGHT_PHASE},${FLIGHT_DIST},${FLIGHT_ETA},${p1_avg},${p1_loss},${p2_avg},${p2_loss},${dns1},${dns2},${h1_ttfb},${h1_total},${h2_ttfb},${h2_total},${IPERF_DL},${IPERF_UL}" >> "$CSV_FILE"
}

# --- Hauptprogramm ---

main() {
  clear
  echo -e "${BOLD}${CYAN}"
  echo "  ██╗    ██╗██╗███╗   ██╗ ██████╗ ███████╗"
  echo "  ██║    ██║██║████╗  ██║██╔════╝ ██╔════╝"
  echo "  ██║ █╗ ██║██║██╔██╗ ██║██║  ███╗███████╗"
  echo "  ██║███╗██║██║██║╚██╗██║██║   ██║╚════██║"
  echo "  ╚███╔███╔╝██║██║ ╚████║╚██████╔╝███████║"
  echo "   ╚══╝╚══╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚══════╝"
  echo -e "  Wings Connect – Verbindungstest${RESET}"
  echo ""
  log "Logdatei: $LOG_FILE"
  log "CSV-Datei: $CSV_FILE"
  log "Messintervall: ${INTERVAL}s | Ping-Pakete: ${PING_COUNT}"
  init_csv

  local round=1

  # Einmalig: Traceroute zu Beginn
  separator
  log "${BOLD}=== TRACEROUTE (einmalig) ===${RESET}"
  test_traceroute

  while true; do
    separator
    log "${BOLD}=== MESSRUNDE #${round} ===${RESET}"
    separator

    test_flight_data
    echo ""
    test_ping
    echo ""
    test_dns
    echo ""
    test_http
    echo ""
    test_bandwidth

    # CSV-Zeile schreiben
    write_csv_row "$round"

    separator
    log "Runde #${round} abgeschlossen. Nächste in ${INTERVAL}s (Strg+C = Ende)"
    separator
    echo ""

    round=$((round + 1))
    sleep "$INTERVAL"
  done
}

# Einzelmessung oder Dauerbetrieb?
case "${1:-}" in
  --once | -1)
    init_csv
    separator
    log "=== EINZELMESSUNG ==="
    separator
    test_flight_data; echo ""
    test_ping; echo ""
    test_dns; echo ""
    test_http; echo ""
    test_bandwidth
    write_csv_row 1
    separator
    log "Log: $LOG_FILE"
    log "CSV: $CSV_FILE"
    ;;
  --traceroute | -t)
    test_traceroute
    ;;
  --help | -h)
    echo "Verwendung: $0 [Option]"
    echo "  (kein Argument)   Dauermessung alle ${INTERVAL}s"
    echo "  --once / -1       Nur eine Messrunde"
    echo "  --traceroute / -t Nur Traceroute"
    echo "  --help / -h       Diese Hilfe"
    ;;
  *)
    main
    ;;
esac
