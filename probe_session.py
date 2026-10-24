#!/usr/bin/env python3
"""Sidecar: schreibt den Wings-Connect-Sitzungs-/Tarifstatus mit (redigiert).

Laeuft unabhaengig von test_connection.sh und beeintraechtigt die laufende
Messung nicht. Es werden NUR unbedenkliche Felder gespeichert - keine
Zugangsdaten, MAC, IP oder Redirect-Token (Repo wird versioniert/gepusht).
"""
import argparse, datetime, json, os, ssl, time, urllib.request

URL = "https://onboard.abu.inmarsat.com/ac/device/info"
SAFE_TOP = ["status", "status_reason"]
SAFE_PAX = ["session_status", "session_status_reason", "logged_in",
            "purchased_plan", "is_upsell_available", "IFEAccess",
            "session_start_time", "session_end_time", "session_resume_time",
            "session_time_remaining", "voucher"]
CTX = ssl.create_default_context()

def snapshot():
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {"captured_utc": now}
    try:
        req = urllib.request.Request(URL, headers={
            "Accept": "application/json", "User-Agent": "Mozilla/5.0",
            "Origin": "https://www.wingsconnect.aero"})
        raw = json.load(urllib.request.urlopen(req, timeout=30, context=CTX))
        pax = json.loads(raw.get("additional_content") or "{}")
        for k in SAFE_TOP:
            if k in raw:
                rec[k] = raw[k]
        for k in SAFE_PAX:
            if k in pax:
                rec["pax_" + k] = pax[k]
    except Exception as e:
        rec["error"] = type(e).__name__ + ": " + str(e)[:120]
    return rec

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flight", required=True)
    ap.add_argument("--interval", type=int, default=300, help="Sekunden (Standard 300)")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    os.makedirs("logs", exist_ok=True)
    date = datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join("logs", "session_%s_%s.jsonl" % (date, a.flight))
    while True:
        rec = snapshot()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        rem = rec.get("pax_session_time_remaining")
        remh = ("%.1fh" % (rem / 3600)) if isinstance(rem, (int, float)) else "-"
        state = rec.get("pax_session_status") or rec.get("error") or rec.get("status") or "?"
        print("[%s] %s rest=%s -> %s" % (rec["captured_utc"], state, remh, path), flush=True)
        if a.once:
            break
        try:
            time.sleep(a.interval)
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()
