---
name: status
description: Kurzstatus der Wings-Connect-Messung (Kennzahlen, letzte Runden, Auffälligkeiten) über make_report.py --summary. Nutzen, wenn nach dem Stand der Messung, den letzten Runden oder Auffälligkeiten gefragt wird.
---

Gib den aktuellen Messstand aus, ohne Logdateien zu lesen.

1. Flug-ID: `$ARGUMENTS`, falls leer die ID aus „Aktueller Stand“ in CLAUDE.md (derzeit `EW9444`).
2. Führe genau einen Befehl aus:
   `/c/Python313/python make_report.py --flight <ID> --summary --last 5`
3. Gib die Ausgabe unverändert als Codeblock wieder und ergänze höchstens drei Sätze Einordnung (z.B. Verbindung stabil / Handover-Phase / Ausfall seit …). Vergleichswerte aus Flug 1 stehen in CLAUDE.md unter „Erfahrungswerte“.

Nicht tun: `.log`, `.jsonl` oder `.html` aus `logs/` lesen, HTML-Bericht erzeugen (das ist `--open` ohne `--summary`, nur auf Wunsch).
