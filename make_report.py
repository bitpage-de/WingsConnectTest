#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wings Connect – HTML-Bericht aus den Messdaten erzeugen.

Liest eine oder mehrere CSV-Dateien von test_connection.sh (altes Format von
Flug 1 und neues Format werden erkannt), optional die .jsonl-Rohdaten, und
schreibt eine einzelne HTML-Datei ohne externe Ressourcen (funktioniert offline).

Verwendung:
  python make_report.py --flight EW9444
      → alle logs/wingsconnect_*_EW9444.csv, Ausgabe logs/REPORT_<Datum>_EW9444.html
  python make_report.py logs/wingsconnect_2026-03-31_*.csv -o logs/REPORT_2026-03-31_EWG39C.html --route "DUS → ACE"
  python make_report.py --flight EW9444 --open
      → danach im Standardbrowser öffnen
"""
import argparse
import csv
import glob
import html
import json
import math
import os
import statistics
import sys
import webbrowser
from datetime import datetime, timedelta

TS_FMT = "%Y-%m-%d %H:%M:%S"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")


# ----------------------------------------------------------------- Laden
def num(v):
    """'N/A', 'timeout', 'error' und leer → None, sonst float."""
    if v is None:
        return None
    v = str(v).strip()
    if v in ("", "N/A", "timeout", "error", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def text(v):
    v = (v or "").strip()
    return None if v in ("", "N/A") else v


def parse_ts(s):
    try:
        return datetime.strptime((s or "").strip(), TS_FMT)
    except ValueError:
        return None


def eu_offset_hours(dt):
    """Europe/Berlin ohne tzdata: MESZ (+2) zwischen letztem Sonntag im März
    und letztem Sonntag im Oktober, sonst MEZ (+1)."""
    def last_sunday(year, month):
        d = datetime(year, month, 31)
        while d.weekday() != 6:
            d -= timedelta(days=1)
        return d
    start = last_sunday(dt.year, 3).replace(hour=2)
    end = last_sunday(dt.year, 10).replace(hour=3)
    return 2 if start <= dt < end else 1


def normalize(r, legacy, src):
    """Eine CSV-Zeile in ein einheitliches Dict wandeln.

    legacy = Format von Flug 1: Spalte 'timestamp' (lokal), kein UTC, Paketverlust
    als Anzahl verlorener Pakete (von 10) statt Prozent, curl-Bandbreite in den
    Spalten iperf_dl_mbps/iperf_ul_mbps.
    """
    g = r.get
    t_local = parse_ts(g("timestamp") if legacy else g("timestamp_local"))
    if t_local is None:
        return None
    if legacy:
        t_utc = t_local - timedelta(hours=eu_offset_hours(t_local))
    else:
        t_utc = parse_ts(g("timestamp_utc"))

    loss_factor = 10.0 if legacy else 1.0

    def loss(key):
        v = num(g(key))
        return None if v is None else min(100.0, v * loss_factor)

    try:
        rnd = int(float(g("round") or 0))
    except ValueError:
        rnd = 0

    return {
        "t_local": t_local, "t_utc": t_utc, "round": rnd, "src": src, "legacy": legacy,
        "callsign": text(g("callsign")), "reg": text(g("registration")), "type": text(g("aircraft_type")),
        "phase": text(g("flight_phase")), "alt": num(g("altitude_ft")), "speed": num(g("ground_speed_kts")),
        "heading": num(g("heading_deg")), "temp": num(g("temperature_c")),
        "lat": num(g("lat")), "lon": num(g("lon")), "dist": num(g("dist_dest_nm")),
        "eta": text(g("eta")), "elapsed": text(g("elapsed_flight_time")),
        "inet": text(g("internet_available")), "inet_reason": text(g("internet_unavailable_reason")),
        "p1_avg": num(g("ping_8888_avg_ms")), "p1_loss": loss("ping_8888_loss_pct"),
        "p1_timeout": (g("ping_8888_avg_ms") or "").strip() == "timeout",
        "p2_avg": num(g("ping_1111_avg_ms")), "p2_loss": loss("ping_1111_loss_pct"),
        "p2_timeout": (g("ping_1111_avg_ms") or "").strip() == "timeout",
        "dns1": num(g("dns_google_ms")), "dns2": num(g("dns_cloudflare_ms")),
        "h1_ttfb": num(g("http_google_ttfb_s")), "h1_total": num(g("http_google_total_s")),
        "h1_err": (g("http_google_ttfb_s") or "").strip() == "error",
        "h2_ttfb": num(g("http_cloudflare_ttfb_s")), "h2_total": num(g("http_cloudflare_total_s")),
        "h2_err": (g("http_cloudflare_ttfb_s") or "").strip() == "error",
        "curl_dl": num(g("iperf_dl_mbps") if legacy else g("curl_dl_mbps")),
        "curl_ul": num(g("iperf_ul_mbps") if legacy else g("curl_ul_mbps")),
        "iperf_dl": None if legacy else num(g("iperf_dl_mbps")),
        "iperf_ul": None if legacy else num(g("iperf_ul_mbps")),
        "iperf_srv": None if legacy else text(g("iperf_server")),
    }


def load_rows(paths):
    rows = []
    for p in paths:
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            rd = csv.DictReader(f)
            if not rd.fieldnames or "round" not in rd.fieldnames:
                print(f"überspringe {p}: keine Messdaten-CSV", file=sys.stderr)
                continue
            legacy = "timestamp_utc" not in rd.fieldnames
            for r in rd:
                row = normalize(r, legacy, os.path.basename(p))
                if row:
                    rows.append(row)
    rows.sort(key=lambda r: r["t_local"])
    seen, out = set(), []
    for r in rows:
        if r["t_local"] in seen:
            continue
        seen.add(r["t_local"])
        out.append(r)
    return out


def load_jsonl_info(paths):
    """Flughafen-Codes und Flugzeugdaten aus den Rohantworten (nur neues Format)."""
    info = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)["flight"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    for k in ("orig", "dest"):
                        code = (d.get(k) or {}).get("code") if isinstance(d.get(k), dict) else None
                        if code and k not in info:
                            info[k] = code
                    for k in ("callSign", "aircraftRegistration", "aircraftType", "flightNumber"):
                        if d.get(k) and k not in info:
                            info[k] = str(d[k])
        except OSError:
            pass
    return info


# ----------------------------------------------------------------- Statistik / Format
def vals(rows, key):
    return [r[key] for r in rows if r.get(key) is not None]


def med(xs):
    return statistics.median(xs) if xs else None


def mean(xs):
    return statistics.fmean(xs) if xs else None


def fmt(v, decimals=0, unit="", dash="–"):
    """Deutsche Zahlenschreibweise (1.234,5) mit schmalem Leerzeichen vor der Einheit."""
    if v is None:
        return dash
    s = f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + (f" {unit}" if unit else "")


def rng(xs, decimals=0, unit=""):
    return f"{fmt(min(xs), decimals)} – {fmt(max(xs), decimals, unit)}" if xs else "–"


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def first(rows, key):
    for r in rows:
        if r.get(key):
            return r[key]
    return None


# ----------------------------------------------------------------- Auswertung
def detect_events(rows):
    """Auffälligkeiten pro Runde: (index, severity, text)."""
    events = []
    pings = vals(rows, "p1_avg") + vals(rows, "p2_avg")
    pmed = med(pings)
    prev = None
    for i, r in enumerate(rows):
        notes = []
        if r["p1_timeout"] and r["p2_timeout"]:
            notes.append(("crit", "Kompletter Ausfall: beide Ping-Ziele Timeout"))
        elif r["p1_timeout"] or r["p2_timeout"]:
            notes.append(("crit", "Ping-Timeout " + ("8.8.8.8" if r["p1_timeout"] else "1.1.1.1")))
        losses = [x for x in (r["p1_loss"], r["p2_loss"]) if x is not None and x < 100]
        if losses and max(losses) >= 20:   # 1 von 10 Paketen (10 %) ist auf Satellit normales Rauschen
            notes.append(("warn", f"Paketverlust {fmt(max(losses), 0, '%')}"))
        pr = [x for x in (r["p1_avg"], r["p2_avg"]) if x is not None]
        if pr and pmed and max(pr) > 1.5 * pmed:
            notes.append(("warn", f"Latenz erhöht: {fmt(max(pr), 0, 'ms')} (Median {fmt(pmed, 0, 'ms')})"))
        dns = [x for x in (r["dns1"], r["dns2"]) if x is not None]
        if dns and max(dns) > 3000:
            notes.append(("warn", f"DNS langsam: {fmt(max(dns), 0, 'ms')}"))
        if r["h1_err"] or r["h2_err"]:
            who = " und ".join(n for n, e in (("google.com", r["h1_err"]), ("cloudflare.com", r["h2_err"])) if e)
            notes.append(("warn", f"HTTP-Fehler: {who}"))
        if r["curl_dl"] is not None and r["curl_dl"] < 0.1:
            notes.append(("warn", f"Download eingebrochen: {fmt(r['curl_dl'], 2, 'Mbit/s')}"))
        if prev:
            if r["phase"] and prev["phase"] and r["phase"] != prev["phase"]:
                notes.append(("info", f"Flugphase {prev['phase']} → {r['phase']}"))
            if r["alt"] is not None and prev["alt"] is not None and abs(r["alt"] - prev["alt"]) >= 2000:
                notes.append(("info", f"Höhenänderung {fmt(prev['alt'])} → {fmt(r['alt'], 0, 'ft')}"))
        for sev, msg in notes:
            events.append((i, sev, msg))
        prev = r
    return events


def kpi_tiles(rows):
    n = len(rows)
    pings = vals(rows, "p1_avg") + vals(rows, "p2_avg")
    losses = vals(rows, "p1_loss") + vals(rows, "p2_loss")
    outages = sum(1 for r in rows if r["p1_timeout"] or r["p2_timeout"])
    dns = vals(rows, "dns1") + vals(rows, "dns2")
    ttfb = vals(rows, "h1_ttfb") + vals(rows, "h2_ttfb")
    dl = vals(rows, "curl_dl")
    ul = vals(rows, "curl_ul")
    return [
        ("Ping, Median", fmt(med(pings), 0, "ms"), rng(pings, 0, "ms")),
        ("Paketverlust, Mittel", fmt(mean(losses), 1, "%"), f"max. {fmt(max(losses), 0, '%')}" if losses else "–"),
        ("Runden mit Timeout", str(outages), f"von {n} Runden"),
        ("Verfügbarkeit", fmt(100.0 * (n - outages) / n, 0, "%") if n else "–", "Runden ohne Ping-Timeout"),
        ("DNS, Median", fmt(med(dns), 0, "ms"), rng(dns, 0, "ms")),
        ("HTTP TTFB, Median", fmt(med(ttfb), 1, "s"), rng(ttfb, 1, "s")),
        ("Download, Median", fmt(med(dl), 2, "Mbit/s"), f"max. {fmt(max(dl), 2, 'Mbit/s')} · curl" if dl else "nicht gemessen"),
        ("Upload, Median", fmt(med(ul), 2, "Mbit/s"), f"max. {fmt(max(ul), 2, 'Mbit/s')} · curl" if ul else "nicht gemessen"),
    ]


def runs(indices):
    """Zusammenhängende Index-Bereiche: [1,2,3,7] → [[1,3],[7,7]]"""
    out = []
    for i in indices:
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def build_payload(rows):
    t0 = rows[0]["t_local"]

    def series(name, slot, key):
        return {"name": name, "slot": slot, "values": [r[key] for r in rows]}

    timeouts = [i for i, r in enumerate(rows) if r["p1_timeout"] or r["p2_timeout"]]
    bands = runs(timeouts)
    markers = []
    for i in range(1, len(rows)):
        if rows[i]["phase"] and rows[i - 1]["phase"] and rows[i]["phase"] != rows[i - 1]["phase"]:
            markers.append([i, rows[i]["phase"]])

    charts = [
        {"id": "ping", "title": "Ping-Latenz", "sub": "Mittelwert aus 10 Paketen, in ms", "unit": "ms",
         "decimals": 0, "series": [series("8.8.8.8", 1, "p1_avg"), series("1.1.1.1", 2, "p2_avg")],
         "bands": bands, "nullText": "Timeout"},
        {"id": "loss", "title": "Paketverlust", "sub": "Anteil verlorener Ping-Pakete, in %", "unit": "%",
         "decimals": 0, "series": [series("8.8.8.8", 1, "p1_loss"), series("1.1.1.1", 2, "p2_loss")],
         "bands": bands, "minTop": 10},
        {"id": "dns", "title": "DNS-Auflösung", "sub": "Dauer von nslookup, in ms", "unit": "ms",
         "decimals": 0, "series": [series("google.com", 1, "dns1"), series("cloudflare.com", 2, "dns2")],
         "bands": bands},
        {"id": "ttfb", "title": "HTTP Time-to-First-Byte", "sub": "curl, Sekunden bis zum ersten Byte", "unit": "s",
         "decimals": 2, "series": [series("google.com", 1, "h1_ttfb"), series("cloudflare.com", 2, "h2_ttfb")],
         "bands": bands, "nullText": "Fehler"},
        {"id": "curl", "title": "Bandbreite (curl)", "sub": "5 MB Download / 512 KB Upload über HTTPS, ein TCP-Stream, in Mbit/s",
         "unit": "Mbit/s", "decimals": 2,
         "series": [series("Download", 1, "curl_dl"), series("Upload", 2, "curl_ul")], "bands": bands},
    ]
    if vals(rows, "iperf_dl") or vals(rows, "iperf_ul"):
        charts.append({"id": "iperf", "title": "Bandbreite (iperf3)", "sub": "TCP-Durchsatz gegen öffentlichen iperf3-Server, in Mbit/s",
                       "unit": "Mbit/s", "decimals": 2,
                       "series": [series("Download", 1, "iperf_dl"), series("Upload", 2, "iperf_ul")], "bands": bands})
    charts += [
        {"id": "alt", "title": "Flughöhe", "sub": "in ft, Wechsel der Flugphase markiert", "unit": "ft", "decimals": 0,
         "series": [series("Höhe", 1, "alt")], "area": True, "markers": markers, "half": True},
        {"id": "speed", "title": "Geschwindigkeit über Grund", "sub": "in kts", "unit": "kts", "decimals": 0,
         "series": [series("Speed", 1, "speed")], "half": True},
    ]

    track = []
    for i, r in enumerate(rows):
        pr = [x for x in (r["p1_avg"], r["p2_avg"]) if x is not None]
        track.append({
            "i": i, "lat": r["lat"], "lon": r["lon"],
            "ping": min(pr) if pr else None,
            "timeout": bool(r["p1_timeout"] or r["p2_timeout"]),
            "tip": [
                [fmt(r["alt"], 0, "ft"), "Höhe"],
                [r["phase"] or "–", "Phase"],
                [fmt(min(pr), 0, "ms") if pr else "Timeout", "Ping"],
                [fmt(r["curl_dl"], 2, "Mbit/s"), "Download"],
                [f"{fmt(r['lat'], 3)}, {fmt(r['lon'], 3)}" if r["lat"] is not None else "–", "Position"],
            ],
        })

    return {
        "minutes": [(r["t_local"] - t0).total_seconds() / 60.0 for r in rows],
        "startMin": t0.hour * 60 + t0.minute + t0.second / 60.0,
        "labels": [r["t_local"].strftime("%H:%M") for r in rows],
        "utc": [r["t_utc"].strftime("%H:%M") if r["t_utc"] else "" for r in rows],
        "rounds": [r["round"] for r in rows],
        "timeout": [bool(r["p1_timeout"] or r["p2_timeout"]) for r in rows],
        "charts": charts,
        "track": track,
    }


# ----------------------------------------------------------------- HTML
CSS = r"""
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --band: rgba(11,11,11,0.06);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --seq-1: #86b6ef; --seq-2: #5598e7; --seq-3: #2a78d6; --seq-4: #1c5cab; --seq-5: #0d366b;
  --crit: #d03b3b; --warn: #fab219; --info: #898781;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --band: rgba(255,255,255,0.08);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec; --seq-4: #3987e5; --seq-5: #256abf;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --band: rgba(255,255,255,0.08);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec; --seq-4: #3987e5; --seq-5: #256abf;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 24px 16px 48px; }
header { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 12px 24px; margin-bottom: 20px; }
header h1 { font-size: 26px; margin: 0 0 4px; font-weight: 650; letter-spacing: -0.01em; }
header .meta { color: var(--text-secondary); margin: 0; }
header .meta span + span::before { content: " · "; color: var(--text-muted); }
.spacer { flex: 1; }
button.theme { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary);
  border-radius: 8px; padding: 6px 10px; font: inherit; font-size: 13px; cursor: pointer; }
h2 { font-size: 17px; font-weight: 650; margin: 28px 0 10px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.tile .label { color: var(--text-secondary); font-size: 13px; }
.tile .value { font-size: 26px; font-weight: 600; margin: 2px 0; }
.tile .sub { color: var(--text-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.grid.half { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px 10px; }
.card h3 { margin: 0; font-size: 15px; font-weight: 650; }
.card .sub { margin: 2px 0 8px; color: var(--text-muted); font-size: 12.5px; }
.plot { position: relative; width: 100%; min-height: 120px; }
.plot svg { display: block; overflow: visible; }
.empty { color: var(--text-muted); font-size: 13px; padding: 24px 0; text-align: center; margin: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 6px; color: var(--text-secondary); font-size: 12.5px; }
.lg-item { display: inline-flex; align-items: center; gap: 6px; }
.key { display: inline-block; width: 14px; height: 2px; border-radius: 1px; }
.key.band-key { width: 14px; height: 10px; background: var(--band); border: 1px solid var(--border); }
.key.dotkey { width: 10px; height: 10px; border-radius: 50%; }
.key.ring { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--text-primary); background: transparent; }
svg .grid { stroke: var(--grid); stroke-width: 1; }
svg .baseline { stroke: var(--axis); stroke-width: 1; }
svg .tick { fill: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
svg .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
svg .area { opacity: 0.10; }
svg .dot { stroke: var(--surface-1); stroke-width: 2; }
svg .band { fill: var(--band); }
svg .crosshair { stroke: var(--text-secondary); stroke-width: 1; pointer-events: none; }
svg .marker { stroke: var(--axis); stroke-width: 1; }
svg .marker-label { fill: var(--text-secondary); font-size: 11px; }
svg .track { fill: none; stroke: var(--axis); stroke-width: 1; }
svg .pt { stroke: var(--surface-1); stroke-width: 2; }
svg .pt-timeout { fill: none; stroke: var(--text-primary); stroke-width: 2; }
svg .map-label { fill: var(--text-secondary); font-size: 11.5px; }
svg .hit { fill: transparent; cursor: crosshair; }
.tip { position: fixed; z-index: 10; display: none; pointer-events: none; background: var(--surface-1);
  color: var(--text-primary); border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px;
  font-size: 12.5px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); max-width: 260px; }
.tip-h { color: var(--text-secondary); margin-bottom: 4px; }
.tip-r { display: flex; align-items: center; gap: 8px; font-variant-numeric: tabular-nums; }
.tip-r strong { font-weight: 600; }
.tip-n { color: var(--text-secondary); }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-secondary); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
td.num, th.num { text-align: right; }
.tablewrap { overflow: auto; max-height: 70vh; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-1); }
details > summary { cursor: pointer; color: var(--text-secondary); margin-bottom: 8px; }
.sev { display: inline-flex; align-items: center; gap: 6px; }
.sev::before { content: ""; width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.sev.crit::before { background: var(--crit); } .sev.warn::before { background: var(--warn); } .sev.info::before { background: var(--info); }
.notes { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 10px 16px; color: var(--text-secondary); font-size: 13.5px; }
.notes ul { margin: 6px 0; padding-left: 18px; }
footer { margin-top: 32px; color: var(--text-muted); font-size: 12.5px; }
@media print { button.theme { display: none; } .tablewrap { max-height: none; } }
"""

JS = r"""
(function () {
  const D = JSON.parse(document.getElementById('report-data').textContent);
  const M = D.minutes, N = M.length;
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function hhmm(min) { min = ((Math.round(min) % 1440) + 1440) % 1440;
    return String(Math.floor(min / 60)).padStart(2, '0') + ':' + String(min % 60).padStart(2, '0'); }
  function fmtNum(v, d) { return v == null ? '–' : v.toLocaleString('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function compact(v) { return Math.abs(v) >= 1000 ? (v / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1 }) + 'K'
    : v.toLocaleString('de-DE', { maximumFractionDigits: 2 }); }
  function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw))); const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p; }
  function yScale(maxVal) { if (!(maxVal > 0)) maxVal = 1; const step = niceStep(maxVal / 4);
    const top = Math.ceil(maxVal / step - 1e-9) * step; const ticks = [];
    for (let t = 0; t <= top + 1e-9; t += step) ticks.push(+t.toFixed(6)); return { top, ticks }; }
  function xTicks() { const span = Math.max(M[N - 1] - M[0], 1); const steps = [5, 10, 15, 20, 30, 60, 120, 180];
    const step = steps.find(s => span / s <= 8) || 240; const out = [];
    const first = Math.ceil((D.startMin + M[0]) / step) * step;
    for (let t = first; t <= D.startMin + M[N - 1] + 1e-9; t += step) out.push(t - D.startMin); return out; }
  function segments(values) { const segs = []; let cur = [];
    values.forEach((v, i) => { if (v == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(i); });
    if (cur.length) segs.push(cur); return segs; }

  // ---- Tooltip (eins für alle Charts)
  const tip = document.createElement('div'); tip.className = 'tip'; document.body.appendChild(tip);
  function showTip(x, y, head, rows) {
    tip.replaceChildren();
    const h = document.createElement('div'); h.className = 'tip-h'; h.textContent = head; tip.appendChild(h);
    rows.forEach(r => {
      const d = document.createElement('div'); d.className = 'tip-r';
      if (r.color) { const k = document.createElement('span'); k.className = 'key'; k.style.background = r.color; d.appendChild(k); }
      const v = document.createElement('strong'); v.textContent = r.value; d.appendChild(v);
      const n = document.createElement('span'); n.className = 'tip-n'; n.textContent = r.name; d.appendChild(n);
      tip.appendChild(d);
    });
    tip.style.display = 'block';
    const pad = 14, bw = tip.offsetWidth, bh = tip.offsetHeight;
    let tx = x + pad, ty = y + pad;
    if (tx + bw > window.innerWidth - 8) tx = x - bw - pad;
    if (ty + bh > window.innerHeight - 8) ty = y - bh - pad;
    tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }

  // ---- Zeitreihen-Chart
  function renderChart(card, cfg) {
    const plot = card.querySelector('.plot'); plot.replaceChildren();
    const W = plot.clientWidth || 600, H = cfg.half ? 200 : 240;
    const allVals = cfg.series.flatMap(s => s.values).filter(v => v != null);
    if (!allVals.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = 'Keine Daten'; plot.appendChild(p); return; }
    const ys = yScale(Math.max(Math.max(...allVals), cfg.minTop || 0));
    const yLabels = ys.ticks.map(compact);
    const L = Math.max(...yLabels.map(s => s.length)) * 7 + 14, R = 14, T = 12, B = 30;
    const pw = Math.max(W - L - R, 50), ph = H - T - B;
    const span = Math.max(M[N - 1] - M[0], 1e-9);
    const x = i => L + (N > 1 ? (M[i] - M[0]) / span * pw : pw / 2);
    const y = v => T + ph - v / ys.top * ph;
    const svg = el('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, plot);

    (cfg.bands || []).forEach(([i0, i1]) => {
      const x0 = i0 > 0 ? (x(i0 - 1) + x(i0)) / 2 : L, x1 = i1 < N - 1 ? (x(i1) + x(i1 + 1)) / 2 : L + pw;
      el('rect', { x: x0, y: T, width: Math.max(2, x1 - x0), height: ph, class: 'band' }, svg);
    });
    ys.ticks.forEach((t, k) => {
      el('line', { x1: L, x2: L + pw, y1: y(t), y2: y(t), class: k === 0 ? 'baseline' : 'grid' }, svg);
      const tx = el('text', { x: L - 8, y: y(t) + 4, class: 'tick', 'text-anchor': 'end' }, svg); tx.textContent = yLabels[k];
    });
    xTicks().forEach(m => {
      const xx = L + (m - M[0]) / span * pw; if (xx < L - 1 || xx > L + pw + 1) return;
      el('line', { x1: xx, x2: xx, y1: T + ph, y2: T + ph + 4, class: 'baseline' }, svg);
      const t = el('text', { x: xx, y: T + ph + 18, class: 'tick', 'text-anchor': 'middle' }, svg); t.textContent = hhmm(D.startMin + m);
    });
    (cfg.markers || []).forEach(([i, label]) => {
      el('line', { x1: x(i), x2: x(i), y1: T, y2: T + ph, class: 'marker' }, svg);
      const t = el('text', { x: x(i) + 4, y: T + 11, class: 'marker-label' }, svg); t.textContent = label;
    });
    cfg.series.forEach(s => {
      const color = `var(--series-${s.slot})`;
      const segs = segments(s.values);
      if (cfg.area) segs.filter(sg => sg.length > 1).forEach(sg => {
        const d = `M${x(sg[0]).toFixed(1)} ${y(0).toFixed(1)} ` + sg.map(i => `L${x(i).toFixed(1)} ${y(s.values[i]).toFixed(1)}`).join(' ')
          + ` L${x(sg[sg.length - 1]).toFixed(1)} ${y(0).toFixed(1)} Z`;
        el('path', { d, class: 'area', style: `fill:${color}` }, svg);
      });
      const d = segs.filter(sg => sg.length > 1).map(sg => sg.map((i, k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)} ${y(s.values[i]).toFixed(1)}`).join(' ')).join(' ');
      if (d) el('path', { d, class: 'line', style: `stroke:${color}` }, svg);
      if (N <= 40) s.values.forEach((v, i) => { if (v != null) el('circle', { cx: x(i), cy: y(v), r: 4, class: 'dot', style: `fill:${color}` }, svg); });
      else segs.forEach(sg => { if (sg.length === 1) el('circle', { cx: x(sg[0]), cy: y(s.values[sg[0]]), r: 4, class: 'dot', style: `fill:${color}` }, svg); });
    });
    const ch = el('line', { x1: 0, x2: 0, y1: T, y2: T + ph, class: 'crosshair', style: 'display:none' }, svg);
    const hit = el('rect', { x: L, y: T, width: pw, height: ph, class: 'hit' }, svg);
    hit.addEventListener('pointermove', e => {
      const px = e.clientX - svg.getBoundingClientRect().left;
      let best = 0, bd = Infinity;
      for (let i = 0; i < N; i++) { const dd = Math.abs(x(i) - px); if (dd < bd) { bd = dd; best = i; } }
      ch.setAttribute('x1', x(best)); ch.setAttribute('x2', x(best)); ch.style.display = '';
      const rows = cfg.series.map(s => ({ color: `var(--series-${s.slot})`, name: s.name,
        value: s.values[best] == null ? (cfg.nullText || '–') : fmtNum(s.values[best], cfg.decimals) + ' ' + cfg.unit }));
      if (D.timeout[best] && cfg.id !== 'ping') rows.push({ value: 'Timeout', name: 'Ping-Ausfall in dieser Runde' });
      showTip(e.clientX, e.clientY, D.labels[best] + ' Uhr' + (D.utc[best] ? ' (' + D.utc[best] + ' UTC)' : '') + ' · Runde ' + D.rounds[best], rows);
    });
    hit.addEventListener('pointerleave', () => { ch.style.display = 'none'; hideTip(); });

    const lg = card.querySelector('.legend'); lg.replaceChildren();
    if (cfg.series.length >= 2) cfg.series.forEach(s => {
      const it = document.createElement('span'); it.className = 'lg-item';
      const k = document.createElement('span'); k.className = 'key'; k.style.background = `var(--series-${s.slot})`;
      it.appendChild(k); it.appendChild(document.createTextNode(s.name)); lg.appendChild(it);
    });
    if ((cfg.bands || []).length) {
      const it = document.createElement('span'); it.className = 'lg-item';
      const k = document.createElement('span'); k.className = 'key band-key';
      it.appendChild(k); it.appendChild(document.createTextNode('Ping-Timeout')); lg.appendChild(it);
    }
  }

  // ---- Flugspur
  function renderMap(card) {
    const plot = card.querySelector('.plot'); plot.replaceChildren();
    const lg = card.querySelector('.legend'); lg.replaceChildren();
    const P = D.track.filter(p => p.lat != null && p.lon != null);
    if (P.length < 2) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = 'Keine Positionsdaten'; plot.appendChild(p); return; }
    const W = plot.clientWidth || 600;
    const lats = P.map(p => p.lat), lons = P.map(p => p.lon);
    let minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
    const k = Math.cos((minLat + maxLat) / 2 * Math.PI / 180);
    const padLat = Math.max((maxLat - minLat) * 0.12, 0.15), padLon = Math.max((maxLon - minLon) * 0.12, 0.15);
    minLat -= padLat; maxLat += padLat; minLon -= padLon; maxLon += padLon;
    const L = 44, R = 14, T = 12, B = 26, pw = Math.max(W - L - R, 50);
    const ph = Math.max(180, Math.min(480, pw * (maxLat - minLat) / ((maxLon - minLon) * k)));
    const scale = Math.min(pw / ((maxLon - minLon) * k), ph / (maxLat - minLat));
    const cx = (minLon + maxLon) / 2, cy = (minLat + maxLat) / 2;
    const X = lon => L + pw / 2 + (lon - cx) * k * scale, Y = lat => T + ph / 2 - (lat - cy) * scale;
    const svg = el('svg', { width: W, height: T + ph + B, viewBox: `0 0 ${W} ${T + ph + B}` }, plot);
    el('rect', { x: L, y: T, width: pw, height: ph, fill: 'none', class: 'baseline' }, svg);

    // Gradnetz
    const visLon0 = cx - (pw / 2) / (k * scale), visLon1 = cx + (pw / 2) / (k * scale);
    const visLat0 = cy - (ph / 2) / scale, visLat1 = cy + (ph / 2) / scale;
    const maxSpan = Math.max(visLon1 - visLon0, visLat1 - visLat0);
    const step = [0.25, 0.5, 1, 2, 5, 10].find(s => maxSpan / s <= 8) || 20;
    for (let lo = Math.ceil(visLon0 / step) * step; lo <= visLon1; lo += step) {
      el('line', { x1: X(lo), x2: X(lo), y1: T, y2: T + ph, class: 'grid' }, svg);
      const t = el('text', { x: X(lo), y: T + ph + 16, class: 'tick', 'text-anchor': 'middle' }, svg);
      t.textContent = Math.abs(lo).toLocaleString('de-DE') + '°' + (lo < 0 ? 'W' : 'E');
    }
    for (let la = Math.ceil(visLat0 / step) * step; la <= visLat1; la += step) {
      el('line', { x1: L, x2: L + pw, y1: Y(la), y2: Y(la), class: 'grid' }, svg);
      const t = el('text', { x: L - 6, y: Y(la) + 4, class: 'tick', 'text-anchor': 'end' }, svg);
      t.textContent = Math.abs(la).toLocaleString('de-DE') + '°' + (la < 0 ? 'S' : 'N');
    }
    el('polyline', { points: P.map(p => `${X(p.lon).toFixed(1)},${Y(p.lat).toFixed(1)}`).join(' '), class: 'track' }, svg);

    // Farbe = Ping (sequenziell, 5 Stufen)
    const pings = P.filter(p => p.ping != null).map(p => p.ping);
    const pmin = pings.length ? Math.min(...pings) : 0, pmax = pings.length ? Math.max(...pings) : 1;
    const bin = v => pmax > pmin ? Math.min(4, Math.floor((v - pmin) / (pmax - pmin) * 5)) : 2;
    P.forEach(p => {
      if (p.timeout && p.ping == null) el('circle', { cx: X(p.lon), cy: Y(p.lat), r: 6, class: 'pt-timeout' }, svg);
      else el('circle', { cx: X(p.lon), cy: Y(p.lat), r: 4.5, class: 'pt', style: `fill:var(--seq-${bin(p.ping) + 1})` }, svg);
    });
    P.forEach(p => {
      const h = el('circle', { cx: X(p.lon), cy: Y(p.lat), r: 12, class: 'hit' }, svg);
      h.addEventListener('pointermove', e => showTip(e.clientX, e.clientY,
        D.labels[p.i] + ' Uhr · Runde ' + D.rounds[p.i], p.tip.map(([value, name]) => ({ value, name }))));
      h.addEventListener('pointerleave', hideTip);
    });
    const a = P[0], b = P[P.length - 1];
    [[a, 'Start ' + D.labels[a.i]], [b, 'Ende ' + D.labels[b.i]]].forEach(([p, label]) => {
      const left = X(p.lon) < L + pw / 2;
      const t = el('text', { x: X(p.lon) + (left ? 10 : -10), y: Y(p.lat) + 4, class: 'map-label', 'text-anchor': left ? 'start' : 'end' }, svg);
      t.textContent = label;
    });

    if (pings.length) {
      const w = (pmax - pmin) / 5;
      for (let i = 0; i < 5; i++) {
        const it = document.createElement('span'); it.className = 'lg-item';
        const kk = document.createElement('span'); kk.className = 'key dotkey'; kk.style.background = `var(--seq-${i + 1})`;
        it.appendChild(kk);
        it.appendChild(document.createTextNode(pmax > pmin ? `${Math.round(pmin + i * w)}–${Math.round(pmin + (i + 1) * w)} ms` : `${Math.round(pmin)} ms`));
        lg.appendChild(it);
      }
    }
    if (P.some(p => p.timeout && p.ping == null)) {
      const it = document.createElement('span'); it.className = 'lg-item';
      const kk = document.createElement('span'); kk.className = 'key ring'; it.appendChild(kk);
      it.appendChild(document.createTextNode('Ping-Timeout')); lg.appendChild(it);
    }
  }

  function renderAll() {
    D.charts.forEach(cfg => { const card = document.querySelector(`[data-chart="${cfg.id}"]`); if (card) renderChart(card, cfg); });
    const map = document.querySelector('[data-map]'); if (map) renderMap(map);
  }
  let raf = 0;
  new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(renderAll); }).observe(document.body);
  renderAll();

  // ---- Theme-Umschalter
  const btn = document.getElementById('theme');
  function applyTheme(t) { if (t) document.documentElement.setAttribute('data-theme', t); else document.documentElement.removeAttribute('data-theme'); }
  try { applyTheme(localStorage.getItem('wc-theme')); } catch (e) {}
  btn.addEventListener('click', () => {
    const dark = getComputedStyle(document.documentElement).colorScheme.includes('dark');
    const next = dark ? 'light' : 'dark'; applyTheme(next);
    try { localStorage.setItem('wc-theme', next); } catch (e) {}
  });
})();
"""


def render_html(rows, payload, meta, events, sources):
    tiles = "".join(
        f'<div class="tile"><div class="label">{esc(l)}</div><div class="value">{esc(v)}</div><div class="sub">{esc(s)}</div></div>'
        for l, v, s in kpi_tiles(rows)
    )

    def card(c):
        return (f'<div class="card" data-chart="{esc(c["id"])}"><h3>{esc(c["title"])}</h3>'
                f'<p class="sub">{esc(c["sub"])}</p><div class="plot"></div><div class="legend"></div></div>')

    full = "".join(card(c) for c in payload["charts"] if not c.get("half"))
    half = "".join(card(c) for c in payload["charts"] if c.get("half"))

    ev_rows = "".join(
        f'<tr><td>{esc(rows[i]["t_local"].strftime("%H:%M"))}</td><td class="num">{rows[i]["round"]}</td>'
        f'<td>{esc(rows[i]["phase"] or "–")}</td><td class="num">{esc(fmt(rows[i]["alt"], 0))}</td>'
        f'<td>{esc(f"{fmt(rows[i]['lat'], 2)}, {fmt(rows[i]['lon'], 2)}") if rows[i]["lat"] is not None else "–"}</td>'
        f'<td><span class="sev {sev}">{esc(msg)}</span></td></tr>'
        for i, sev, msg in events
    ) or '<tr><td colspan="6" class="empty">Keine Auffälligkeiten</td></tr>'

    has_iperf = any(c["id"] == "iperf" for c in payload["charts"])

    def cell(v, d=0, cls="num"):
        return f'<td class="{cls}">{esc(fmt(v, d))}</td>'

    def ping_cell(avg, timeout):
        return '<td class="num">Timeout</td>' if timeout else cell(avg)

    data_rows = []
    for r in rows:
        cells = [
            f'<td>{esc(r["t_local"].strftime("%H:%M:%S"))}</td>',
            f'<td>{esc(r["t_utc"].strftime("%H:%M") if r["t_utc"] else "–")}</td>',
            f'<td class="num">{r["round"]}</td>',
            f'<td>{esc(r["phase"] or "–")}</td>',
            cell(r["alt"]), cell(r["speed"]),
            ping_cell(r["p1_avg"], r["p1_timeout"]), cell(r["p1_loss"]),
            ping_cell(r["p2_avg"], r["p2_timeout"]), cell(r["p2_loss"]),
            cell(r["dns1"]), cell(r["dns2"]),
            '<td class="num">Fehler</td>' if r["h1_err"] else cell(r["h1_ttfb"], 2),
            '<td class="num">Fehler</td>' if r["h2_err"] else cell(r["h2_ttfb"], 2),
            cell(r["curl_dl"], 2), cell(r["curl_ul"], 2),
        ]
        if has_iperf:
            cells += [cell(r["iperf_dl"], 2), cell(r["iperf_ul"], 2)]
        cells.append(f'<td>{esc(f"{fmt(r['lat'], 3)}, {fmt(r['lon'], 3)}") if r["lat"] is not None else "–"}</td>')
        data_rows.append("<tr>" + "".join(cells) + "</tr>")

    head = ["Lokal", "UTC", "Rd", "Phase", "Höhe ft", "kts", "Ping 8.8.8.8 ms", "Verlust %", "Ping 1.1.1.1 ms", "Verlust %",
            "DNS google ms", "DNS cf ms", "TTFB google s", "TTFB cf s", "DL curl Mbit/s", "UL curl Mbit/s"]
    if has_iperf:
        head += ["DL iperf3", "UL iperf3"]
    head.append("Position")
    numeric_from = 4
    head_html = "".join(f'<th class="{"num" if i >= numeric_from and h != "Position" and h not in ("Phase",) else ""}">{esc(h)}</th>'
                        for i, h in enumerate(head))

    notes = [
        "Zeiten sind Laptop-Zeit (lokal); UTC steht daneben. Die ETA der Bord-API ist nach den Daten von Flug 1 UTC.",
        "Bandbreite (curl) nutzt einen einzelnen TCP-Stream über HTTPS. Bei 700–1400 ms Latenz begrenzt das TCP-Fenster den Wert; die reale Linkkapazität kann höher sein.",
        "Ping-Timeout = alle 10 Pakete verloren. Grau hinterlegte Bereiche in den Charts markieren diese Runden.",
    ]
    if any(r["legacy"] for r in rows):
        notes.append("Dateien im Format von Flug 1 speicherten den Paketverlust als Anzahl verlorener Pakete (von 10). Der Bericht rechnet sie in Prozent um (×10).")

    meta_spans = "".join(f"<span>{esc(m)}</span>" for m in meta["line"] if m)
    src_list = ", ".join(esc(s) for s in sources)
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(meta["title"])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>{esc(meta["title"])}</h1>
    <p class="meta">{meta_spans}</p>
  </div>
  <div class="spacer"></div>
  <button class="theme" id="theme" type="button">Hell / Dunkel</button>
</header>

<section class="kpis">{tiles}</section>

<h2>Verlauf</h2>
<div class="grid">{full}</div>
<div class="grid half" style="margin-top:12px">{half}</div>

<h2>Flugspur</h2>
<div class="card" data-map><h3>Position je Messrunde</h3><p class="sub">Punktfarbe = Ping-Latenz (bester Wert der Runde), hohle Punkte = Ping-Timeout</p><div class="plot"></div><div class="legend"></div></div>

<h2>Auffälligkeiten</h2>
<div class="tablewrap"><table>
<thead><tr><th>Lokal</th><th class="num">Rd</th><th>Phase</th><th class="num">Höhe ft</th><th>Position</th><th>Ereignis</th></tr></thead>
<tbody>{ev_rows}</tbody></table></div>

<h2>Alle Messrunden</h2>
<details open><summary>{len(rows)} Runden, alle Werte (Tabellenansicht zu den Charts)</summary>
<div class="tablewrap"><table><thead><tr>{head_html}</tr></thead><tbody>{"".join(data_rows)}</tbody></table></div>
</details>

<h2>Hinweise</h2>
<div class="notes"><ul>{"".join(f"<li>{esc(n)}</li>" for n in notes)}</ul></div>

<footer>Erstellt {esc(datetime.now().strftime("%d.%m.%Y %H:%M"))} mit make_report.py · Quellen: {src_list}</footer>
</div>
<script id="report-data" type="application/json">{payload_json}</script>
<script>{JS}</script>
</body>
</html>
"""


# ----------------------------------------------------------------- Textzusammenfassung
def text_summary(rows, meta, events, last=5):
    """Kompakter Status für Terminal/Chat (--summary): Kennzahlen, letzte Runden, Auffälligkeiten."""
    lines = [meta["title"], "  " + " · ".join(m for m in meta["line"] if m), ""]
    for label, value, sub in kpi_tiles(rows):
        lines.append(f"  {label + ':':<22}{value:>16}   {sub}")
    lines.append("")
    row_fmt = "  {:>5}  {:>3}  {:<8} {:>9}  {:>12}  {:>12}  {:>7}  {:>7}"
    lines.append(f"Letzte {min(last, len(rows))} Runden:")
    lines.append(row_fmt.format("Zeit", "Rd", "Phase", "Höhe ft", "Ping 8.8.8.8", "Ping 1.1.1.1", "Verlust", "DL curl"))
    for r in rows[-last:]:
        p1 = "Timeout" if r["p1_timeout"] else fmt(r["p1_avg"], 0, "ms")
        p2 = "Timeout" if r["p2_timeout"] else fmt(r["p2_avg"], 0, "ms")
        loss = max([x for x in (r["p1_loss"], r["p2_loss"]) if x is not None] or [None])
        lines.append(row_fmt.format(r["t_local"].strftime("%H:%M"), r["round"], r["phase"] or "–", fmt(r["alt"]),
                                    p1, p2, fmt(loss, 0, "%"), fmt(r["curl_dl"], 2)))
    notable = [(i, s, m) for i, s, m in events if s != "info"]
    lines.append("")
    lines.append(f"Auffälligkeiten: {len(notable)}" + (f" (letzte {min(8, len(notable))})" if len(notable) > 8 else ""))
    for i, _, msg in notable[-8:]:
        lines.append(f"  {rows[i]['t_local'].strftime('%H:%M')}  {msg}")
    return "\n".join(lines)


# ----------------------------------------------------------------- Hauptprogramm
def build_meta(rows, info, args, flight_id):
    callsign = first(rows, "callsign") or info.get("callSign") or flight_id
    reg = first(rows, "reg") or info.get("aircraftRegistration")
    actype = first(rows, "type") or info.get("aircraftType")
    route = args.route or (f"{info['orig']} → {info['dest']}" if "orig" in info and "dest" in info else None)
    t0, t1 = rows[0], rows[-1]
    dur = t1["t_local"] - t0["t_local"]
    alts = vals(rows, "alt")
    phases = []
    for r in rows:
        if r["phase"] and r["phase"] not in phases:
            phases.append(r["phase"])
    title = args.title or " · ".join(x for x in (f"Wings Connect {callsign}", route) if x)
    window = f"{t0['t_local'].strftime('%d.%m.%Y %H:%M')} – {t1['t_local'].strftime('%H:%M')} lokal"
    if t0["t_utc"] and t1["t_utc"]:
        window += f" ({t0['t_utc'].strftime('%H:%M')} – {t1['t_utc'].strftime('%H:%M')} UTC)"
    line = [
        f"{actype} {reg}" if actype or reg else None,
        window,
        f"{len(rows)} Runden in {int(dur.total_seconds() // 3600)}:{int(dur.total_seconds() % 3600 // 60):02d} h",
        f"Höhe {fmt(min(alts))} – {fmt(max(alts), 0, 'ft')}" if alts else None,
        " / ".join(phases) if phases else None,
    ]
    return {"title": title, "line": line, "callsign": callsign}


def main():
    # Windows-Konsole ist oft cp1252 → Pfeile/Umlaute in Meldungen würden sonst abbrechen
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="CSV-Dateien (Globs erlaubt)")
    ap.add_argument("--flight", "-f", help="Flug-ID wie in --flight von test_connection.sh, z.B. EW9444")
    ap.add_argument("--date", help="nur Dateien dieses Tages (YYYY-MM-DD), zusammen mit --flight")
    ap.add_argument("-o", "--output", help="Zieldatei (.html)")
    ap.add_argument("--title", help="Titel überschreiben")
    ap.add_argument("--route", help='Route für die Kopfzeile, z.B. "DUS → BCN"')
    ap.add_argument("--open", action="store_true", help="Bericht danach im Browser öffnen")
    ap.add_argument("--summary", action="store_true", help="nur kurze Textzusammenfassung ausgeben, kein HTML")
    ap.add_argument("--last", type=int, default=5, help="Anzahl der letzten Runden in --summary (Standard 5)")
    args = ap.parse_args()

    files = []
    for pat in args.files:
        files += glob.glob(pat)
    if args.flight:
        date = args.date or "*"
        files += glob.glob(os.path.join(LOG_DIR, f"wingsconnect_{date}_{args.flight}.csv"))
    files = sorted(set(os.path.abspath(f) for f in files if f.lower().endswith(".csv")))
    if not files:
        ap.error("keine CSV-Dateien gefunden (Dateien angeben oder --flight nutzen)")

    rows = load_rows(files)
    if not rows:
        sys.exit("keine Messrunden in den Dateien gefunden")

    jsonl = [f[:-4] + ".jsonl" for f in files if os.path.exists(f[:-4] + ".jsonl")]
    info = load_jsonl_info(jsonl)

    flight_id = args.flight or os.path.basename(files[0]).rsplit("_", 1)[-1][:-4]
    meta = build_meta(rows, info, args, flight_id)
    payload = build_payload(rows)
    events = detect_events(rows)
    sources = [os.path.basename(f) for f in files] + [os.path.basename(j) for j in jsonl]

    if args.summary:
        print(text_summary(rows, meta, events, args.last))
        return

    out = args.output or os.path.join(LOG_DIR, f"REPORT_{rows[0]['t_local'].strftime('%Y-%m-%d')}_{meta['callsign']}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(rows, payload, meta, events, sources))
    print(f"{len(rows)} Runden aus {len(files)} Datei(en) → {out}")
    if args.open:
        webbrowser.open("file:///" + os.path.abspath(out).replace("\\", "/"))


if __name__ == "__main__":
    main()
