#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wings Connect – Netzwerk-Probe: Was lässt das Bord-WLAN zu, und wie sichtbar ist das eigene Gerät?

Prüft ausschließlich eigene Verbindungen, das eigene Subnetz und das eigene Gerät.
Es werden keine Ports fremder Geräte gescannt.

  1. Umgebung     IP, Subnetz, Gateway, DNS, Netzwerkprofil, öffentliche IP/Provider, IPv6
  2. Portal/Proxy Captive-Portal-Checks, HTTP-Umleitung, Proxy-Header, TLS-Zertifikatsaussteller
  3. DNS          lokaler Resolver, direkt 8.8.8.8/1.1.1.1 (UDP+TCP), DoT 853, DoH, NXDOMAIN-Hijack, Resolver-Identität
  4. TCP-Egress   29 Ports gegen portquiz.net (lauscht auf allen Ports) + echte Dienste (FTP, SSH, Telnet, SMTP, IMAP …)
  5. UDP          NTP (mit Uhrabweichung), STUN (öffentliche IP, NAT-Typ)
  6. Isolation    Gateway, Ping-Sweep im eigenen /24, ARP-Tabelle, passives Mithören (mDNS/SSDP/LLMNR/NetBIOS), je eine mDNS-/SSDP-Anfrage
  7. Eigenes Gerät Firewall, Netzwerkerkennung, Datei-/Druckerfreigabe, RDP, NetBIOS/LLMNR, lauschende Ports

Ausgabe: logs/netprobe_<Datum>_<Uhrzeit>_<Flug>.txt und .json

Verwendung:
  /c/Python313/python probe_network.py --flight EW9444
  /c/Python313/python probe_network.py --quick          # ohne Ping-Sweep, 5 s Mithören
  /c/Python313/python probe_network.py --no-sweep --listen 30
"""
import argparse
import concurrent.futures
import ftplib
import ipaddress
import json
import os
import random
import re
import select
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")
FLIGHT_API = "https://www.wingsconnect.aero/map/api/flightData"

TCP_TIMEOUT = 8       # Satellit: Connect dauert 2–4 s, Timeout = vermutlich gefiltert
HTTP_TIMEOUT = 15
UDP_TIMEOUT = 6

# Testserver, die auf allen TCP-Ports lauschen und mit HTTP antworten: (Host, Prüfport, Erkennungstext).
# Beide sperren die Quell-IP bei zu vielen Verbindungen (portquiz.net am 18.10. nach 4 Läufen in 8 Min.) →
# die Probe sparsam einsetzen, Parallelität klein halten.
EGRESS_SERVERS = [
    ("portquiz.net", 80, "port"),
    ("letmeoutofyour.net", 8080, "w00tw00t"),
]
EGRESS_PORTS = [
    (21, "FTP"), (22, "SSH/SFTP"), (23, "Telnet"), (25, "SMTP"), (53, "DNS/TCP"),
    (80, "HTTP"), (110, "POP3"), (143, "IMAP"), (443, "HTTPS"), (465, "SMTPS"),
    (587, "SMTP Submission"), (993, "IMAPS"), (995, "POP3S"), (1080, "SOCKS"),
    (1194, "OpenVPN/TCP"), (1723, "PPTP"), (3306, "MySQL"), (3389, "RDP"),
    (5060, "SIP"), (5201, "iperf3"), (5222, "XMPP"), (5900, "VNC"), (6667, "IRC"),
    (8080, "HTTP-alt"), (8443, "HTTPS-alt"), (9001, "Tor"), (22000, "Syncthing"),
    (51820, "WireGuard-Port/TCP"), (44444, "Zufallsport"),
]

# Echte Dienste: Banner lesen zeigt, dass das Protokoll durchkommt (nicht nur der TCP-Connect)
BANNER_SERVICES = [
    ("speedtest.tele2.net", 21, "FTP", False),
    ("github.com", 22, "SSH", False),
    ("telehack.com", 23, "Telnet", False),
    ("gmail-smtp-in.l.google.com", 25, "SMTP (MX)", False),
    ("smtp.gmail.com", 587, "SMTP Submission", False),
    ("smtp.gmail.com", 465, "SMTPS", True),
    ("outlook.office365.com", 143, "IMAP/STARTTLS", False),
    ("imap.gmail.com", 993, "IMAPS", True),
    ("pop.gmail.com", 995, "POP3S", True),
]

OUT = []
R = {}


# ----------------------------------------------------------------- Ausgabe
def say(line=""):
    print(line)
    OUT.append(line)


def head(title):
    say()
    say(f"== {title}")


def mark(status, msg):
    # OK = geht, ZU = blockiert/gefiltert, !! = Hinweis/Risiko, ?? = nicht feststellbar, -- = Info
    say(f"  [{status}] {msg}")


def fmt_ms(ms):
    return f"{ms:.0f} ms"


# ----------------------------------------------------------------- Helfer
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_get(url, timeout=HTTP_TIMEOUT, headers=None, verify=True, follow=False):
    """→ dict(status, headers, body, ms, error). Fehlerstatus wird wie eine Antwort behandelt."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    if not follow:
        handlers.append(NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "wingsconnect-probe/1.0"})
    t0 = time.time()
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(4096)
            return {"status": resp.status, "headers": dict(resp.headers), "body": body.decode("utf-8", "replace"),
                    "ms": (time.time() - t0) * 1000, "error": None}
    except urllib.error.HTTPError as e:
        body = e.read(4096) if hasattr(e, "read") else b""
        return {"status": e.code, "headers": dict(e.headers or {}), "body": body.decode("utf-8", "replace"),
                "ms": (time.time() - t0) * 1000, "error": None}
    except Exception as e:  # noqa: BLE001 – jede Art von Netzfehler ist hier ein Messergebnis
        return {"status": None, "headers": {}, "body": "", "ms": (time.time() - t0) * 1000, "error": f"{type(e).__name__}: {e}"}


def tcp_connect(host, port, timeout=TCP_TIMEOUT):
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        return s, (time.time() - t0) * 1000, None
    except Exception as e:  # noqa: BLE001
        return None, (time.time() - t0) * 1000, f"{type(e).__name__}: {e}"


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung geschlossen")
        buf += chunk
    return buf


def printable(b):
    return re.sub(r"[^\x20-\x7e]", "", b.decode("latin-1")).strip()


# ----------------------------------------------------------------- Mini-DNS-Client (UDP / TCP / TLS)
def dns_build(name, qtype):
    qid = random.randint(0, 65535)
    q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    for label in name.rstrip(".").split("."):
        q += bytes([len(label)]) + label.encode("idna")
    return qid, q + b"\x00" + struct.pack(">HH", qtype, 1)


def dns_read_name(data, off):
    labels, jumped, end = [], False, None
    for _ in range(64):
        length = data[off]
        if length & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", data[off:off + 2])[0] & 0x3FFF
            if not jumped:
                end = off + 2
            off, jumped = ptr, True
            continue
        off += 1
        if length == 0:
            break
        labels.append(data[off:off + length].decode("latin-1"))
        off += length
    return ".".join(labels), (end if jumped else off)


def dns_parse(data, qid):
    rid, flags, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    if rid != qid:
        raise ValueError("DNS-ID passt nicht")
    off = 12
    for _ in range(qd):
        _, off = dns_read_name(data, off)
        off += 4
    answers = []
    for _ in range(an):
        _, off = dns_read_name(data, off)
        rtype, _, ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        off += rdlen
        if rtype == 1 and rdlen == 4:
            answers.append(socket.inet_ntoa(rdata))
        elif rtype == 16:
            txt, i = [], 0
            while i < len(rdata):
                ln = rdata[i]
                txt.append(rdata[i + 1:i + 1 + ln].decode("latin-1"))
                i += 1 + ln
            answers.append("".join(txt))
        elif rtype == 5:
            answers.append("CNAME " + dns_read_name(data, off - rdlen)[0])
        else:
            answers.append(f"type{rtype}:{rdata.hex()[:32]}")
    return {"rcode": flags & 0xF, "answers": answers, "ttl": ttl if an else None}


def dns_query(name, qtype=1, server="8.8.8.8", proto="udp", tls_name=None, timeout=UDP_TIMEOUT):
    qid, q = dns_build(name, qtype)
    t0 = time.time()
    if proto == "udp":
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(q, (server, 53))
            data, _ = s.recvfrom(4096)
        finally:
            s.close()
    else:
        port = 853 if proto == "tls" else 53
        s = socket.create_connection((server, port), timeout=timeout)
        try:
            if proto == "tls":
                s = ssl.create_default_context().wrap_socket(s, server_hostname=tls_name or server)
            s.settimeout(timeout)
            s.sendall(struct.pack(">H", len(q)) + q)
            data = recv_exact(s, struct.unpack(">H", recv_exact(s, 2))[0])
        finally:
            s.close()
    res = dns_parse(data, qid)
    res["ms"] = (time.time() - t0) * 1000
    return res


def dns_try(label, **kw):
    try:
        r = dns_query(**kw)
        rc = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}.get(r["rcode"], f"rcode {r['rcode']}")
        return r, f"{rc} {', '.join(r['answers'][:3]) or '–'} ({fmt_ms(r['ms'])})"
    except Exception as e:  # noqa: BLE001
        return None, f"Fehler: {type(e).__name__}: {e}"


# ----------------------------------------------------------------- UDP-Protokolle
def ntp_query(host="time.google.com", timeout=UDP_TIMEOUT):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.time()
        s.sendto(b"\x1b" + 47 * b"\0", (host, 123))
        data, _ = s.recvfrom(48)
        t1 = time.time()
    finally:
        s.close()
    tx = struct.unpack("!I", data[40:44])[0] - 2208988800 + struct.unpack("!I", data[44:48])[0] / 2 ** 32
    return {"rtt_ms": (t1 - t0) * 1000, "offset_ms": (tx - (t0 + t1) / 2) * 1000}


def stun_query(sock, host, port, timeout=UDP_TIMEOUT):
    txid = os.urandom(12)
    sock.settimeout(timeout)
    sock.sendto(struct.pack(">HHI", 0x0001, 0, 0x2112A442) + txid, (host, port))
    data, _ = sock.recvfrom(1024)
    _, mlen, _ = struct.unpack(">HHI", data[:8])
    off = 20
    while off < 20 + mlen:
        atype, alen = struct.unpack(">HH", data[off:off + 4])
        val = data[off + 4:off + 4 + alen]
        if atype in (0x0020, 0x8020) and val[1] == 1:
            port_ = struct.unpack(">H", val[2:4])[0] ^ 0x2112
            ip = bytes(b ^ m for b, m in zip(val[4:8], struct.pack(">I", 0x2112A442)))
            return socket.inet_ntoa(ip), port_
        if atype == 0x0001 and val[1] == 1:
            return socket.inet_ntoa(val[4:8]), struct.unpack(">H", val[2:4])[0]
        off += 4 + ((alen + 3) & ~3)
    raise ValueError("keine Mapped-Address in STUN-Antwort")


# ----------------------------------------------------------------- Windows-Infos per PowerShell
PS_INFO = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 | Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
$idx = $route.InterfaceIndex
$ip = Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 | Select-Object -First 1
$v6 = Get-NetIPAddress -AddressFamily IPv6 | Where-Object { $_.PrefixOrigin -in 'RouterAdvertisement','Dhcp' -and $_.IPAddress -notlike 'fe80*' } | Select-Object -ExpandProperty IPAddress
$prof = Get-NetConnectionProfile -InterfaceIndex $idx
function RuleOn($group) { @(Get-NetFirewallRule -Group $group -Direction Inbound -Enabled True | Where-Object { $_.Profile -match 'Public|Any' }).Count }
$listenTcp = Get-NetTCPConnection -State Listen | Where-Object { $_.LocalAddress -in '0.0.0.0','::' } |
  ForEach-Object { [pscustomobject]@{ Proto = 'TCP'; Port = [int]$_.LocalPort; ProcId = $_.OwningProcess } }
$listenUdp = Get-NetUDPEndpoint | Where-Object { $_.LocalAddress -in '0.0.0.0','::' -and $_.LocalPort -lt 49152 } |
  ForEach-Object { [pscustomobject]@{ Proto = 'UDP'; Port = [int]$_.LocalPort; ProcId = $_.OwningProcess } }

# Aktive eingehende Allow-Regeln, die im öffentlichen Profil gelten, mit Port- und Programmfilter
$rules = @{}; $groups = @{}
Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow | Where-Object { $_.Profile -match 'Public|Any' } |
  ForEach-Object { $rules[$_.Name] = [string]$_.DisplayName; $groups[$_.Name] = [string]$_.Group }
$pf = @{}; Get-NetFirewallPortFilter -All | Where-Object { $rules.ContainsKey($_.InstanceID) } | ForEach-Object { $pf[$_.InstanceID] = $_ }
$af = @{}; Get-NetFirewallApplicationFilter -All | Where-Object { $rules.ContainsKey($_.InstanceID) } | ForEach-Object { $af[$_.InstanceID] = $_ }

$listen = @($listenTcp) + @($listenUdp) | Sort-Object Proto, Port -Unique | ForEach-Object {
  $l = $_
  $proc = Get-Process -Id $l.ProcId
  $path = [string]$proc.Path
  $hits = foreach ($id in $rules.Keys) {
    $p = $pf[$id]; $a = $af[$id]
    if (-not $p) { continue }
    $protoOk = ($p.Protocol -eq 'Any') -or ($p.Protocol -eq $l.Proto)
    $ports = @($p.LocalPort)
    $portOk = ($ports -contains 'Any') -or ($ports -contains [string]$l.Port)
    $prog = if ($a) { [Environment]::ExpandEnvironmentVariables([string]$a.Program) } else { 'Any' }
    $progOk = ($prog -eq 'Any') -or ($path -and $prog -ieq $path) -or ($prog -ieq 'System' -and $l.ProcId -eq 4)
    # Regeln ohne jede Einschränkung (Port Any + Programm Any) betreffen nur Sonderprotokolle → ignorieren
    if ($protoOk -and $portOk -and $progOk -and -not (($ports -contains 'Any') -and $prog -eq 'Any')) {
      [pscustomobject]@{ Name = $rules[$id]; Group = $groups[$id] }
    }
  }
  [pscustomobject]@{ Proto = $l.Proto; Port = $l.Port; Proc = [string]$proc.ProcessName; AllowedBy = @($hits | Sort-Object Name -Unique | Select-Object -First 3) }
}
$nb = (Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=true" | Where-Object InterfaceIndex -eq $idx).TcpipNetbiosOptions
[pscustomobject]@{
  Interface      = [string](Get-NetAdapter -InterfaceIndex $idx).Name
  IP             = [string]$ip.IPAddress
  Prefix         = [int]$ip.PrefixLength
  Gateway        = [string]$route.NextHop
  DNS            = @((Get-DnsClientServerAddress -InterfaceIndex $idx -AddressFamily IPv4).ServerAddresses)
  IPv6           = @($v6)
  SSID           = [string]$prof.Name
  Category       = [string]$prof.NetworkCategory
  Firewall       = @(Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ Name = [string]$_.Name; Enabled = [bool]$_.Enabled; Inbound = [string]$_.DefaultInboundAction } })
  DiscoveryRules = RuleOn '@FirewallAPI.dll,-32752'
  SharingRules   = RuleOn '@FirewallAPI.dll,-28502'
  RdpRules       = RuleOn '@FirewallAPI.dll,-28752'
  RdpDenied      = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server').fDenyTSConnections
  SmbServer      = [string](Get-Service LanmanServer).Status
  NetBios        = $nb
  LlmnrPolicy    = (Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient').EnableMulticast
  Listening      = @($listen)
} | ConvertTo-Json -Depth 4
"""


def windows_info():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_INFO],
                           capture_output=True, timeout=90)
        info = json.loads(r.stdout.decode("utf-8", "replace"))
        for k in ("DNS", "IPv6", "Firewall", "Listening"):   # PS 5.1 macht aus 1-elementigen Arrays Objekte
            v = info.get(k)
            if v is None:
                info[k] = []
            elif not isinstance(v, list):
                info[k] = [v]
        return info
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def arp_table():
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, timeout=20).stdout.decode("latin-1")
    except Exception:  # noqa: BLE001
        return []
    entries = []
    for ip, mac in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})", out):
        mac = mac.lower()
        if mac.startswith(("ff-ff-ff", "01-00-5e")):
            continue
        entries.append((ip, mac))
    return entries


def ping_alive(ip):
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", "400", ip], capture_output=True, timeout=5)
        return ip if b"TTL=" in r.stdout else None
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------- Passives Mithören + Discovery-Anfragen
def listen_local(seconds, own_ip):
    groups = [("mDNS", 5353, "224.0.0.251"), ("SSDP", 1900, "239.255.255.250"),
              ("LLMNR", 5355, "224.0.0.252"), ("NetBIOS", 137, None)]
    socks, errors, seen = {}, {}, {}
    for name, port, group in groups:
        seen[name] = set()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            if group:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(group) + socket.inet_aton(own_ip))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(own_ip))
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setblocking(False)
            socks[s] = (name, port, group)
        except OSError as e:
            errors[name] = str(e)
    # Je eine Standard-Discovery-Anfrage (macht jedes Handy ständig): wer antwortet, ist nicht isoliert
    for s, (name, port, group) in socks.items():
        try:
            if name == "mDNS":
                _, q = dns_build("_services._dns-sd._udp.local", 12)
                s.sendto(b"\x00\x00" + q[2:], (group, port))
            elif name == "SSDP":
                s.sendto(b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n", (group, port))
        except OSError as e:
            errors[name + "-Anfrage"] = str(e)
    end = time.time() + seconds
    packets = 0
    while time.time() < end:
        ready, _, _ = select.select(list(socks), [], [], 0.5)
        for s in ready:
            try:
                _, (ip, _) = s.recvfrom(65535)
            except OSError:
                continue
            packets += 1
            if ip != own_ip:
                seen[socks[s][0]].add(ip)
    for s in socks:
        s.close()
    return seen, errors, packets


# ----------------------------------------------------------------- Abschnitte
def flight_snapshot():
    r = http_get(FLIGHT_API, timeout=5, verify=False)
    if r["status"] == 200:
        try:
            d = json.loads(r["body"])
            return {k: d.get(k) for k in ("callSign", "aircraftRegistration", "flightPhase", "altitude", "lat", "lon", "internetAvailable")}
        except ValueError:
            pass
    return None


def section_env(info):
    head("1. Umgebung")
    if "error" in info:
        mark("??", f"Windows-Infos nicht lesbar: {info['error']}")
        return
    net = ipaddress.ip_network(f"{info['IP']}/{info['Prefix']}", strict=False)
    mark("--", f"Interface {info['Interface']} · SSID/Netz „{info['SSID']}“ · Profil {info['Category']}")
    mark("--", f"IP {info['IP']}/{info['Prefix']} (Subnetz {net}, {net.num_addresses - 2} mögliche Hosts) · Gateway {info['Gateway']}")
    mark("--", f"DNS-Server (DHCP): {', '.join(info['DNS']) or '–'}")
    if info["Category"] != "Public":
        mark("!!", f"Netzwerkprofil ist „{info['Category']}“ – für fremde WLANs sollte es „Public/Öffentlich“ sein (Netzwerkerkennung/Freigaben aus)")
    else:
        mark("OK", "Netzwerkprofil „Öffentlich“: Windows deaktiviert Netzwerkerkennung und Freigaben in diesem Profil")
    R["env"] = {k: info.get(k) for k in ("Interface", "IP", "Prefix", "Gateway", "DNS", "SSID", "Category", "IPv6")}
    R["env"]["subnet"] = str(net)

    r = http_get("https://ifconfig.co/json")
    if r["status"] == 200:
        try:
            d = json.loads(r["body"])
            mark("--", f"Öffentliche IP {d.get('ip')} · {d.get('asn')} {d.get('asn_org')} · {d.get('country')} ({fmt_ms(r['ms'])})")
            R["env"]["public"] = {k: d.get(k) for k in ("ip", "asn", "asn_org", "country", "city")}
        except ValueError:
            mark("??", "ifconfig.co: keine JSON-Antwort (Portal?)")
    else:
        r2 = http_get("https://api.ipify.org?format=json")
        mark("--" if r2["status"] == 200 else "??", f"Öffentliche IP: {r2['body'].strip() if r2['status'] == 200 else r2['error'] or r2['status']}")
    if info["IPv6"]:
        # Literal-Adresse (dns.google) statt Hostname: trennt IPv6-Routing von DNS
        s, ms, err = tcp_connect("2001:4860:4860::8888", 443)
        if s:
            s.close()
        mark("OK" if s else "ZU", f"IPv6: globale Adresse {info['IPv6'][0]}, [2001:4860:4860::8888]:443 {'erreichbar' if s else 'nicht erreichbar: ' + str(err)[:60]} ({fmt_ms(ms)})")
    else:
        mark("--", "IPv6: keine globale Adresse (nur IPv4)")


def section_portal():
    head("2. Captive Portal / Proxy / TLS")
    res = {}
    for url, expect in (("http://connectivitycheck.gstatic.com/generate_204", 204),
                        ("http://www.msftconnecttest.com/connecttest.txt", 200)):
        r = http_get(url)
        host = url.split("/")[2]
        if r["status"] == expect and (expect == 204 or "Microsoft Connect Test" in r["body"]):
            mark("OK", f"{host}: erwartete Antwort {expect} ({fmt_ms(r['ms'])}) – kein Portal im Weg")
        elif r["status"] in (301, 302, 303, 307):
            mark("!!", f"{host}: Umleitung {r['status']} → {r['headers'].get('Location', '?')[:80]} (Captive Portal aktiv / nicht eingeloggt)")
        else:
            mark("!!", f"{host}: Status {r['status']} {r['error'] or ''}")
        res[host] = {"status": r["status"], "location": r["headers"].get("Location"), "ms": r["ms"]}
    # Klartext-HTTP zu einem Server mit bekannter Antwort: Proxy-Header oder veränderte Antwort zeigen Middleboxen
    r = http_get("http://neverssl.com/")
    proxy_hdrs = {k: v for k, v in r["headers"].items() if k.lower() in ("via", "x-cache", "x-forwarded-for", "proxy-connection", "x-squid-error", "x-bluecoat-via")}
    if r["status"] == 200 and "neverssl" in r["body"].lower():
        mark("!!" if proxy_hdrs else "OK", f"HTTP-Klartext zu neverssl.com: unverändert, Server={r['headers'].get('Server', '?')}" + (f" · Proxy-Header {proxy_hdrs}" if proxy_hdrs else " · keine Proxy-Header"))
    elif r["status"] in (301, 302, 303, 307):
        mark("!!", f"HTTP-Klartext zu neverssl.com: Umleitung {r['status']} → {r['headers'].get('Location', '?')[:80]} (Portal/Proxy)")
    else:
        mark("??", f"HTTP-Klartext zu neverssl.com: {r['status']} {r['error'] or ''}")
    res["proxy_headers"] = proxy_hdrs
    for host in ("www.google.com", "www.eurowings.com"):
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=TCP_TIMEOUT) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as s:
                    cert = s.getpeercert()
                    issuer = dict(x[0] for x in cert.get("issuer", ()))
                    org, cn = issuer.get("organizationName", "?"), issuer.get("commonName", "?")
                    mark("OK", f"TLS {host}: {s.version()}, Zertifikat gültig, Aussteller „{org} / {cn}“")
                    res[host] = {"issuer": f"{org} / {cn}", "tls": s.version()}
        except ssl.SSLCertVerificationError as e:
            mark("!!", f"TLS {host}: Zertifikat NICHT vertrauenswürdig ({e.verify_message}) – mögliche TLS-Interception oder Portal")
            res[host] = {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            mark("??", f"TLS {host}: {type(e).__name__}: {e}")
            res[host] = {"error": str(e)}
    R["portal"] = res


def section_dns(info):
    head("3. DNS")
    res = {}
    local_dns = (info.get("DNS") or [None])[0]
    # lokaler Resolver (Systemweg)
    t0 = time.time()
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo("www.google.com", 443, socket.AF_INET)})
        mark("OK", f"System-Resolver: www.google.com → {', '.join(ips[:3])} ({fmt_ms((time.time() - t0) * 1000)})")
        res["system"] = ips
    except socket.gaierror as e:
        mark("ZU", f"System-Resolver: {e}")
    if local_dns:
        _, txt = dns_try("lokal", name="www.google.com", server=local_dns)
        mark("--", f"DHCP-DNS {local_dns} direkt (UDP): {txt}")
        res["dhcp_dns"] = txt
        r, txt = dns_try("nx", name=f"nx-{random.randint(10**6, 10**7)}.example", server=local_dns)
        if r and r["rcode"] == 0 and r["answers"]:
            mark("!!", f"NXDOMAIN-Hijack: nicht existierende Domain wird aufgelöst → {txt}")
        else:
            mark("OK", f"Nicht existierende Domain: {txt}")
        res["nxdomain"] = txt
    for server, tls_name in (("8.8.8.8", "dns.google"), ("1.1.1.1", "one.one.one.one")):
        for proto in ("udp", "tcp", "tls"):
            r, txt = dns_try("", name="www.google.com", server=server, proto=proto, tls_name=tls_name)
            label = {"udp": "UDP/53", "tcp": "TCP/53", "tls": "DoT 853"}[proto]
            mark("OK" if r else "ZU", f"{server} {label}: {txt}")
            res[f"{server}/{proto}"] = txt
    r = http_get("https://cloudflare-dns.com/dns-query?name=www.google.com&type=A", headers={"accept": "application/dns-json"})
    mark("OK" if r["status"] == 200 else "ZU", f"DoH cloudflare-dns.com: {'Status ' + str(r['status']) if r['status'] else r['error']} ({fmt_ms(r['ms'])})")
    res["doh"] = r["status"]
    # Welche Resolver-IP sieht Google? Bei 8.8.8.8 muss das eine Google-Adresse sein, sonst wird DNS umgeleitet.
    # Google antwortet mit zwei TXT-Einträgen: Resolver-IP und "edns0-client-subnet …" – nur die IP zählt
    def resolver_ip(r):
        return next((a for a in (r["answers"] if r else []) if not a.startswith("edns0")), None)

    r, txt = dns_try("", name="o-o.myaddr.l.google.com", qtype=16, server="8.8.8.8")
    ident = resolver_ip(r)
    if ident:
        google = re.match(r"^(74\.125\.|172\.217\.|172\.253\.|173\.194\.|142\.25[0-1]\.|108\.177\.|209\.85\.|34\.|35\.|2001:4860|2404:6800|2a00:1450|2607:f8b0|2800:3f0|2c0f:fb50)", ident)
        mark("OK" if google else "!!", f"Resolver-Identität via 8.8.8.8: {ident}" + (" (Google)" if google else " – KEINE Google-Adresse, DNS wird abgefangen"))
        res["resolver_identity_8888"] = ident
    else:
        mark("??", f"Resolver-Identität via 8.8.8.8: {txt}")
    if local_dns:
        r, txt = dns_try("", name="o-o.myaddr.l.google.com", qtype=16, server=local_dns)
        ident = resolver_ip(r) or txt
        mark("--", f"Resolver-Identität via DHCP-DNS: {ident} (= Ausstiegs-IP des Bord-Resolvers)")
        res["resolver_identity_local"] = ident
    R["dns"] = res


def short_err(err):
    if not err:
        return "?"
    if "timed out" in err:
        return "Timeout"
    if "10061" in err or "Refused" in err:
        return "abgelehnt (RST)"
    return err[:60]


def egress_one(host, marker, port, name):
    s, ms, err = tcp_connect(host, port)
    if not s:
        return port, name, "ZU", f"kein Connect ({short_err(err)})", ms
    try:
        s.settimeout(TCP_TIMEOUT)
        s.sendall(f"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: wingsconnect-probe\r\n\r\n".encode())
        data = b""
        while len(data) < 4000:
            chunk = s.recv(2048)
            if not chunk:
                break
            data += chunk
    except Exception as e:  # noqa: BLE001
        data = b""
        err = f"{type(e).__name__}"
    finally:
        s.close()
    txt = data.decode("latin-1", "replace")
    if data.startswith(b"HTTP/") and marker in txt.lower() and "Location:" not in txt.split("\r\n\r\n")[0]:
        return port, name, "OK", f"offen, echte Antwort von {host}", ms
    if data.startswith(b"HTTP/"):
        first = txt.split("\r\n")[0]
        loc = re.search(r"Location:\s*(\S+)", txt)
        return port, name, "!!", f"Connect ok, aber fremde Antwort „{first}“{' → ' + loc.group(1)[:60] if loc else ''} (Portal/Proxy fängt ab)", ms
    if "ConnectionReset" in (err or ""):
        return port, name, "--", f"Connect ok ({fmt_ms(ms)}), dann Reset – Testserver sperrt einzelne Ports selbst (portquiz.net: 21, 1723, 5060); Protokoll siehe 4b", ms
    return port, name, "!!", f"Connect ok ({fmt_ms(ms)}), aber keine HTTP-Antwort ({err or 'leer'}) – Firewall akzeptiert und verwirft?", ms


def banner_one(host, port, name, use_tls):
    s, ms, err = tcp_connect(host, port)
    if not s:
        return host, port, name, "ZU", f"kein Connect ({'Timeout' if 'timed out' in (err or '') else err})"
    try:
        if use_tls:
            s = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        s.settimeout(TCP_TIMEOUT)
        if port == 22:
            s.sendall(b"SSH-2.0-wingsconnect-probe\r\n")
        # Erste Zeile lesen (SSH schickt direkt nach der Kennung Binärdaten, Telnet erst Negotiation-Bytes)
        raw = b""
        for _ in range(4):
            raw += s.recv(300)
            if b"\n" in raw or len(raw) > 600:
                break
        if raw[:1] == b"\xff":   # Telnet: IAC-Aushandlung statt Klartext
            return host, port, name, "OK", f"Telnet-Aushandlung (IAC) empfangen ({fmt_ms(ms)})"
        banner = printable(raw.split(b"\n")[0])[:70]
        if banner:
            return host, port, name, "OK", f"Banner „{banner}“ ({fmt_ms(ms)})"
        return host, port, name, "!!", f"Connect ok ({fmt_ms(ms)}), aber kein Banner"
    except ssl.SSLError as e:
        return host, port, name, "!!", f"Connect ok, TLS-Fehler {e.reason or e}"
    except Exception as e:  # noqa: BLE001
        return host, port, name, "!!", f"Connect ok ({fmt_ms(ms)}), dann {type(e).__name__}"
    finally:
        s.close()


def section_tcp():
    head("4. Ausgehende TCP-Ports (gegen Testserver, der auf allen Ports lauscht)")
    res = {}
    server = None
    for host, check_port, marker in EGRESS_SERVERS:
        base = egress_one(host, marker, check_port, "Prüfport")
        if base[2] == "OK":
            server = (host, marker)
            mark("--", f"Testserver {host} (Prüfport {check_port} antwortet, {fmt_ms(base[4])})")
            break
        mark("??", f"Testserver {host}:{check_port} nicht nutzbar: {base[3]}")
    if not server:
        mark("??", "Kein Testserver erreichbar – Port-Matrix nicht prüfbar (Portal nicht freigeschaltet oder IP vom Testserver gesperrt). Abschnitt 4b zeigt echte Dienste.")
        R["tcp_egress"] = {"error": "kein Testserver erreichbar"}
    else:
        host, marker = server
        # Testserver drosseln bei vielen parallelen Verbindungen → 3 parallel, Timeouts einmal einzeln wiederholen
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(lambda p: egress_one(host, marker, *p), EGRESS_PORTS))
        retry = [i for i, r in enumerate(results) if r[2] == "ZU"]
        if retry:
            say(f"  ({len(retry)} ohne Connect – werden einzeln wiederholt …)")
            for i in retry:
                time.sleep(0.5)
                results[i] = egress_one(host, marker, *EGRESS_PORTS[i])
        open_ports = []
        for port, name, status, txt, ms in results:
            mark(status, f"{port:>5} {name:<20} {txt}" + (f" ({fmt_ms(ms)})" if status == "OK" else ""))
            res[port] = {"name": name, "status": status, "detail": txt, "ms": ms}
            if status == "OK":
                open_ports.append(port)
        n_ok = len(open_ports)
        if n_ok == 0:
            verdict = " – keiner, obwohl der Prüfport antwortete: Testserver blockt vermutlich während des Laufs"
        elif n_ok == len(EGRESS_PORTS):
            verdict = ": alle – kein Egress-Filter"
        elif set(open_ports) <= {80, 443, 8080, 8443}:
            verdict = " – nur Web-Ports"
        else:
            verdict = ""
        say(f"  → {n_ok} von {len(EGRESS_PORTS)} Ports offen (Server {host}){verdict}")
        R["tcp_egress"] = {"server": host, "ports": res}
    head("4b. Echte Dienste (Protokoll-Banner)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda b: banner_one(*b), BANNER_SERVICES))
    banners = {}
    for host, port, name, status, txt in results:
        mark(status, f"{name:<16} {host}:{port} {txt}")
        banners[f"{host}:{port}"] = {"name": name, "status": status, "detail": txt}
    # FTP komplett: Login + Listing über den Passive-Datenkanal (zweite Verbindung auf hohem Port)
    last = None
    for host, user, pw in (("test.rebex.net", "demo", "password"), ("speedtest.tele2.net", "anonymous", "probe@example.com")):
        try:
            t0 = time.time()
            ftp = ftplib.FTP(host, timeout=TCP_TIMEOUT * 2)
            ftp.login(user, pw)
            names = ftp.nlst()[:3]
            ftp.quit()
            mark("OK", f"FTP komplett ({host}): Login + Listing ({', '.join(names)}) in {fmt_ms((time.time() - t0) * 1000)}")
            banners["ftp_full"] = f"ok {host}"
            break
        except Exception as e:  # noqa: BLE001
            last = f"{host}: {type(e).__name__}: {str(e)[:60]}"
    else:
        mark("ZU", f"FTP komplett (Login + Passive-Datenkanal): {last}")
        banners["ftp_full"] = last
    R["banners"] = banners


def section_udp():
    head("5. UDP")
    res = {}
    try:
        n = ntp_query()
        mark("OK", f"NTP time.google.com:123 antwortet ({fmt_ms(n['rtt_ms'])}), Uhr weicht {n['offset_ms']:+.0f} ms ab")
        res["ntp"] = n
    except Exception as e:  # noqa: BLE001
        mark("ZU", f"NTP time.google.com:123: {type(e).__name__}: {e}")
        res["ntp"] = str(e)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    mapped = []
    for host, port in (("stun.l.google.com", 19302), ("stun.cloudflare.com", 3478)):
        try:
            ip, p = stun_query(sock, host, port)
            mapped.append((ip, p))
            mark("OK", f"STUN {host}:{port}: öffentliche Adresse {ip}:{p}")
        except Exception as e:  # noqa: BLE001
            mark("ZU", f"STUN {host}:{port}: {type(e).__name__}: {e}")
    sock.close()
    if len(mapped) == 2:
        same = mapped[0] == mapped[1]
        mark("--", "NAT-Mapping: " + ("endpoint-unabhängig (Cone) – P2P/VoIP/WireGuard möglich" if same else "unterschiedlich je Ziel (symmetrisches NAT) – P2P nur über Relay"))
        res["nat"] = "cone" if same else "symmetric"
    res["stun"] = mapped
    mark("--", "UDP-VPNs (OpenVPN 1194, WireGuard 51820, IPsec 500/4500) sind ohne eigenen Server nicht prüfbar; STUN zeigt, ob UDP auf hohe Ports grundsätzlich geht")
    R["udp"] = res


def section_isolation(info, sweep, listen_s):
    head("6. Client-Isolation (eigenes Subnetz)")
    res = {}
    if "error" in info:
        mark("??", "ohne Windows-Infos nicht möglich")
        return
    own, gw = info["IP"], info["Gateway"]
    gw_alive = ping_alive(gw) if gw else None
    mark("--", f"Gateway {gw}: {'antwortet auf Ping' if gw_alive else 'antwortet nicht auf Ping'}")
    net = ipaddress.ip_network(f"{own}/{info['Prefix']}", strict=False)
    sweep_net = net if net.prefixlen >= 24 else ipaddress.ip_network(f"{own}/24", strict=False)
    alive = []
    if sweep:
        hosts = [str(h) for h in sweep_net.hosts() if str(h) not in (own, gw)]
        say(f"  Ping-Sweep über {sweep_net} ({len(hosts)} Adressen, je 1 Paket, 400 ms)" + (f" – Subnetz ist {net}, nur das eigene /24 wird geprüft" if sweep_net != net else "") + " …")
        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
            alive = [ip for ip in ex.map(ping_alive, hosts) if ip]
        mark("!!" if alive else "OK", f"{len(alive)} andere Geräte antworten auf Ping ({fmt_ms((time.time() - t0) * 1000)})" + (": " + ", ".join(alive[:10]) + (" …" if len(alive) > 10 else "") if alive else " – ICMP zu Nachbarn blockiert (gut)"))
    else:
        mark("--", "Ping-Sweep übersprungen (--no-sweep/--quick)")
    arp = [(ip, mac) for ip, mac in arp_table() if ipaddress.ip_address(ip) in net and ip not in (own, gw)]
    mark("!!" if arp else "OK", f"ARP-Tabelle: {len(arp)} Nachbarn mit MAC-Adresse" + (" (antworten also auf Layer 2, auch wenn Ping blockiert ist)" if arp else " – keine Nachbarn sichtbar"))
    res.update({"gateway_ping": bool(gw_alive), "sweep_net": str(sweep_net), "ping_alive": alive, "arp_neighbors": len(arp)})
    say(f"  Passives Mithören {listen_s} s (mDNS/SSDP/LLMNR/NetBIOS) + je eine mDNS-/SSDP-Anfrage …")
    seen, errors, packets = listen_local(listen_s, own)
    total = set().union(*seen.values())
    for name, ips in seen.items():
        mark("!!" if ips else "OK", f"{name:<8} {len(ips)} fremde Absender" + (": " + ", ".join(sorted(ips)[:6]) if ips else "") + (f"  (Socket: {errors[name]})" if name in errors else ""))
    mark("!!" if total else "OK", f"Insgesamt {len(total)} fremde Geräte per Broadcast/Multicast sichtbar, {packets} Pakete" + (" – keine Client-Isolation" if total else " – sieht nach Client-Isolation aus"))
    res.update({"broadcast_sources": {k: sorted(v) for k, v in seen.items()}, "packets": packets, "errors": errors})
    R["isolation"] = res


# Firewall-Gruppen der Windows-Standardregeln für Wi-Fi Direct („WFD Driver-only“ u.a.)
WINDOWS_WFD_GROUPS = {"@wlansvc.dll,-36865", "@wlansvc.dll,-37378", "@FirewallAPI.dll,-36851"}

RISKY_PORTS = {135: "RPC", 139: "NetBIOS", 445: "SMB", 3389: "RDP", 5357: "WSD", 5985: "WinRM", 22: "SSH", 80: "HTTP", 8080: "HTTP", 21: "FTP", 23: "Telnet", 5900: "VNC", 1433: "MSSQL", 3306: "MySQL", 5432: "Postgres"}


def section_self(info):
    head("7. Eigenes Gerät: Sichtbarkeit und Angriffsfläche")
    if "error" in info:
        mark("??", "ohne Windows-Infos nicht möglich")
        return
    pub = info.get("Category") == "Public"
    for fw in info["Firewall"]:
        inbound = "Block (Standard)" if fw["Inbound"] == "NotConfigured" else fw["Inbound"]
        mark("OK" if fw["Enabled"] else "!!", f"Firewall-Profil {fw['Name']:<8} {'an' if fw['Enabled'] else 'AUS'}, eingehend standardmäßig {inbound}")
    mark("OK" if info["DiscoveryRules"] == 0 else "!!", f"Netzwerkerkennung: {info['DiscoveryRules']} eingehende Regeln im öffentlichen Profil aktiv" + (" – Gerät ist nicht per WSD/SSDP/LLMNR auffindbar" if info["DiscoveryRules"] == 0 else " – Gerät ist für andere auffindbar"))
    mark("OK" if info["SharingRules"] == 0 else "!!", f"Datei-/Druckerfreigabe: {info['SharingRules']} eingehende Regeln im öffentlichen Profil aktiv (SMB-Dienst {info['SmbServer']})")
    rdp_on = info.get("RdpDenied") == 0
    mark("OK" if not rdp_on or info["RdpRules"] == 0 else "!!", f"Remotedesktop: {'aktiviert' if rdp_on else 'deaktiviert'}, {info['RdpRules']} Firewall-Regeln im öffentlichen Profil")
    nb = {0: "Standard (per DHCP, meist an)", 1: "an", 2: "aus"}.get(info.get("NetBios"), "?")
    llmnr = "aus (Richtlinie)" if info.get("LlmnrPolicy") == 0 else "an (Standard)"
    mark("--", f"NetBIOS über TCP/IP: {nb} · LLMNR: {llmnr} – beide beantworten Namensanfragen von Nachbarn, wenn keine Isolation besteht")
    listening = info["Listening"]
    for l in listening:   # PS 5.1: 1-elementige Arrays kommen als einzelnes Objekt
        a = l.get("AllowedBy")
        l["AllowedBy"] = [] if not a else (a if isinstance(a, list) else [a])
    tcp = [l for l in listening if l["Proto"] == "TCP"]
    udp = [l for l in listening if l["Proto"] == "UDP"]
    mark("--", f"{len(tcp)} TCP-Ports lauschen auf allen Adressen: " + ", ".join(f"{l['Port']}/{l['Proc']}" for l in tcp[:14]) + (" …" if len(tcp) > 14 else ""))
    mark("--", f"{len(udp)} UDP-Ports (< 49152) lauschen auf allen Adressen: " + ", ".join(f"{l['Port']}/{l['Proc']}" for l in udp[:14]) + (" …" if len(udp) > 14 else ""))
    exposed = [l for l in listening if l["AllowedBy"]]
    for l in exposed:
        label = RISKY_PORTS.get(int(l["Port"]), "")
        names = "“, „".join(r["Name"] for r in l["AllowedBy"])
        port_txt = f"{l['Proto']} {l['Port']}{' (' + label + ')' if label else ''} {l['Proc']}"
        if all(r.get("Group") in WINDOWS_WFD_GROUPS for r in l["AllowedBy"]):
            mark("??", f"{port_txt} – nur durch Windows-Standardregel „{names}“ (Wi-Fi Direct) erlaubt; greift vermutlich nur auf dem Wi-Fi-Direct-Adapter, vom Laptop selbst nicht prüfbar → Gegenprobe")
        else:
            mark("!!", f"Von außen erreichbar: {port_txt} – Allow-Regel im öffentlichen Profil: „{names}“")
    if any(not all(r.get("Group") in WINDOWS_WFD_GROUPS for r in l["AllowedBy"]) for l in exposed):
        say("     → Ohne Client-Isolation können Mitreisende diese Ports erreichen. Regel auf Profil „Privat“ beschränken: wf.msc → Eingehende Regeln → Eigenschaften → Erweitert.")
    if not exposed:
        mark("OK", "Kein lauschender Port hat eine Allow-Regel im öffentlichen Profil – die Firewall blockt alle eingehenden Verbindungen")
    risky = [l for l in tcp if int(l["Port"]) in RISKY_PORTS and not l["AllowedBy"]]
    if risky:
        mark("--", "Lauschen, aber von der Firewall geblockt: " + ", ".join(f"{l['Port']} ({RISKY_PORTS[int(l['Port'])]})" for l in risky) + ("" if pub else " – Achtung: Profil ist nicht öffentlich"))
    say(f"  Gegenprobe von einem zweiten Gerät im selben WLAN: ping {info['IP']} und z.B. eine Netzwerkscanner-App – ohne Isolation sieht sie dieses Gerät trotz Firewall per ARP.")
    R["self"] = {k: info.get(k) for k in ("Category", "Firewall", "DiscoveryRules", "SharingRules", "RdpRules", "RdpDenied", "SmbServer", "NetBios", "LlmnrPolicy", "Listening")}


# ----------------------------------------------------------------- Hauptprogramm
def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flight", "-f", default="test", help="Flug-ID für den Dateinamen")
    ap.add_argument("--no-sweep", action="store_true", help="Ping-Sweep im eigenen Subnetz überspringen")
    ap.add_argument("--listen", type=int, default=15, help="Sekunden passives Mithören (Standard 15)")
    ap.add_argument("--quick", action="store_true", help="= --no-sweep --listen 5")
    args = ap.parse_args()
    if args.quick:
        args.no_sweep, args.listen = True, 5

    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now()
    flight_id = re.sub(r"[^A-Za-z0-9_-]", "", args.flight) or "test"
    base = os.path.join(LOG_DIR, f"netprobe_{now.strftime('%Y-%m-%d_%H-%M')}_{flight_id}")
    R.update({"flight": flight_id, "started_local": now.strftime("%Y-%m-%d %H:%M:%S"),
              "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})

    say(f"Wings Connect Netzwerk-Probe · Flug {flight_id} · {R['started_local']} lokal / {R['started_utc']} UTC")
    snap = flight_snapshot()
    R["flight_data"] = snap
    if snap:
        say(f"Flugdaten: {snap.get('callSign')} ({snap.get('aircraftRegistration')}) · {snap.get('flightPhase')} · {snap.get('altitude')} ft · Internet-Flag {snap.get('internetAvailable')}")
    else:
        say("Flugdaten: Bord-API nicht erreichbar (nicht im Flugzeug-WLAN)")
    say("Legende: [OK] geht  [ZU] blockiert  [!!] Hinweis/Risiko  [??] nicht feststellbar  [--] Info")

    t0 = time.time()
    say("  (lese Windows-Netzwerkinfos …)")
    info = windows_info()
    section_env(info)
    section_portal()
    section_dns(info)
    section_tcp()
    section_udp()
    section_isolation(info, not args.no_sweep, args.listen)
    section_self(info)

    say()
    say(f"Dauer {time.time() - t0:.0f} s · Dateien: {base}.txt / .json")
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
