"""
CurrentBench - desktop control panel for Korad KA/KD-series bench power supplies.

Requires: Python 3.10+, pyserial and Pillow (py -m pip install pyserial pillow)
Start   : py korad_paneel.py

Unofficial project, not affiliated with Korad. See README.md for the safety notes.
The interface is available in Dutch, English and German; the source text is Dutch (see korad_taal.py).
"""
import csv
import os
import html
import webbrowser
import json
import math
import hmac
import queue
import re
import secrets
import socket
import sys
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
from bisect import bisect_left
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import korad_paden
import korad_taal
from korad_taal import dec, tr
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

import serial
import serial.tools.list_ports

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk
except ImportError:      # zonder Pillow geen ringmeters: duidelijk melden in plaats van een lege foutmelding
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(tr("Pillow ontbreekt"), tr("CurrentBench heeft Pillow nodig.\n\nInstalleren: py -m pip "
                                                "install pillow"))
    raise SystemExit(1)

import korad_analyse as ana
import korad_koppeling
from korad_demo import DEMO_POORT, DemoVoeding
from korad_voeding import (PLAFOND_A, PLAFOND_V, Korad, Model, begrijpt_opdrachten, geldig_bereik, herken, schoon_idn,
                           sleutel)

# ---------------------------------------------------------------- uiterlijk (modern donker, 05-10-2026)
BG = "#0F1216"          # venster
CARD = "#171B21"        # kaarten
CARD_2 = "#21262E"      # invoervelden en knoppen
CARD_3 = "#2B313B"      # knop onder de muis
LINE = "#2A3039"        # randen
GRID = "#222831"        # rasterlijnen in de grafiek
GLASS = "#12161B"       # achtergrond van de grafiek
TEXT = "#E8EBF0"
MUTED = "#8D96A4"
DIM = "#5C6470"
LED_RED = "#FF5E54"     # spanning
LED_AMBER = "#FFB224"   # stroom
LED_GREEN = "#3CCF7A"   # vermogen, uitgang aan
LAMP_OFF = "#3A414C"
BLUE = "#3D7BF2"        # hoofdknoppen en selectie
BTN_GREEN = "#1E9E55"   # knoppen: donkerder dan de meterkleuren, zodat witte tekst leesbaar blijft
BTN_RED = "#D6453C"
BTN_AMBER = "#B97C0B"
MARK = "#8792A2"        # markeringen in de grafiek
GOOD = "#3CCF7A"
BAD = "#FF6B61"
ACCENT = "#6FB1FF"      # lichtblauwe cijfers en de tweede meting bij vergelijken
THEMA = korad_taal.gekozen_thema()
if THEMA == "licht":
    BG, CARD, CARD_2, CARD_3 = "#ECEEF2", "#FFFFFF", "#E4E7EC", "#D6DBE3"
    LINE, GRID, GLASS = "#CFD5DE", "#E6E9EE", "#F8F9FB"
    TEXT, MUTED, DIM = "#1A2029", "#566070", "#7C8695"
    LED_RED, LED_AMBER, LED_GREEN = "#D42C22", "#B06F00", "#128347"
    LAMP_OFF, BLUE, MARK = "#BFC6D1", "#2F6FE0", "#667183"
    BTN_GREEN, BTN_RED, BTN_AMBER = "#178A4B", "#C93A31", "#A66F08"
    GOOD, BAD, ACCENT = "#128347", "#C62F26", "#2569C9"
KEUZE_AAN = "#BCD3F8" if THEMA == "licht" else BLUE      # gekozen tijdvak: de tekst erop blijft in de tekstkleur
GEKLEURD = (BLUE, BTN_GREEN, BTN_RED, BTN_AMBER)         # op deze knopkleuren staat altijd witte tekst
PANEL, PANEL_DARK, INK, BAND, DIAL = BG, CARD_2, TEXT, CARD, CARD_3   # oude namen, nog gebruikt in de vensters
FONT = "Bahnschrift"            # standaard op Windows 10/11
FONT_NUM = "Bahnschrift SemiBold"
FONT_ICON = "Segoe MDL2 Assets"  # standaard op Windows 10/11: scherpe icoontjes als lettertype
UI_SCALE = 1.0                  # schermschaal (2,0 bij 200 %), gezet bij het starten
NAAM = "CurrentBench"
VERSIE = "0.9.0"
MAKER = "Ronny Hullegie"
WEBSITE = "www.ronnyhullegie.nl"
# Waar een gebruiker een fout meldt. Leeg = de knop staat er niet. Het programma verstuurt zelf niets: het
# kopieert de foutinformatie en opent de pagina, de gebruiker plakt en verstuurt.
MELD_GITHUB = "https://github.com/RonnyCHL/currentbench/issues/new"        # de pagina voor een nieuwe melding in de openbare repository
MELD_WEBSITE = ""       # het contactformulier, voor wie geen GitHub-account heeft
ICONEN = {"info": "\uE946", "hulp": "\uE897", "werkbank": "\uE740", "mini": "\uE73F", "projecten": "\uE8F1",
          "afdruk": "\uE928", "gereedschap": "\uE90F", "werkboek": "\uE736", "instellingen": "\uE713",
          "ververs": "\uE72C", "omlaag": "\uE70D", "curve": "\uE9D2", "onderdeel": "\uE950",
          "nacht": "\uE708", "vergelijk": "\uE9D9", "telefoon": "\uE8EA"}
SOORT_KLEUR = {"fout": LED_RED, "alarm": LED_RED, "goed": LED_GREEN, "auto": ACCENT,
               "stap": MUTED, "notitie": TEXT, "gewoon": MUTED}


def px(n):
    """Maat in beeldpunten bij 100 %, omgerekend naar de schermschaal."""
    return int(round(n * UI_SCALE))


def lighten(color, amount=0.10):
    r, g, b = (int(color[k:k + 2], 16) for k in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(int(c + (255 - c) * amount) for c in (r, g, b))


def blend(onder, boven, f):
    """Kleur `boven` voor een fractie f over kleur `onder` (tkinter kent geen doorzichtigheid)."""
    a = [int(onder[k:k + 2], 16) for k in (1, 3, 5)]
    b = [int(boven[k:k + 2], 16) for k in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(int(x + (y - x) * f) for x, y in zip(a, b))


def _scale_pad(kw):
    for k in ("padx", "pady", "ipadx", "ipady"):
        v = kw.get(k)
        if isinstance(v, (int, float)):
            kw[k] = px(v)
        elif isinstance(v, tuple):
            kw[k] = tuple(px(x) if isinstance(x, (int, float)) else x for x in v)
    return kw


# Marges bij pack en grid volgen de schermschaal, zodat alle vensters op 150 of 200 % dezelfde verhoudingen houden.
_pack_orig, _grid_orig = tk.Pack.pack_configure, tk.Grid.grid_configure


def _pack_scaled(self, cnf={}, **kw):
    return _pack_orig(self, cnf, **_scale_pad(kw))


def _grid_scaled(self, cnf={}, **kw):
    return _grid_orig(self, cnf, **_scale_pad(kw))


tk.Pack.pack_configure = tk.Pack.pack = _pack_scaled
tk.Grid.grid_configure = tk.Grid.grid = _grid_scaled

try:   # scherp op een scherm met schaal 150 of 200 % (anders vergroot Windows het venster als een plaatje)
    import ctypes
    import ctypes.wintypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

def fmt(x):
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def nice_ceil(x):
    """Rond af naar een 'mooie' schaalwaarde (1, 1.2, 1.5, 2, 2.5 ...)."""
    if not x or x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * e >= x - 1e-12:
            return m * e
    return 10 * e


PRESET_FILE = korad_paden.bestand("korad_presets.json")
DEFAULT_PRESETS = {"1": [3.3, 0.5], "2": [5.0, 1.0], "3": [12.0, 0.5], "4": [13.8, 0.5]}


def load_presets():
    try:
        data = json.loads(PRESET_FILE.read_text(encoding="utf-8"))
        return {k: data.get(k, v) for k, v in DEFAULT_PRESETS.items()}
    except (OSError, ValueError):
        return dict(DEFAULT_PRESETS)


GUARD_FILE = korad_paden.bestand("korad_bewaking.json")
GUARD_DEFAULTS = [
    {"aan": False, "wat": "stroom", "richting": "boven", "waarde": 300.0, "duur": 5.0, "actie": "uitgang uit"},
    {"aan": False, "wat": "stroom", "richting": "onder", "waarde": 40.0, "duur": 10.0, "actie": "waarschuwen"},
    {"aan": False, "wat": "spanning", "richting": "onder", "waarde": 4.5, "duur": 2.0, "actie": "waarschuwen"},
]
UNITS = {"stroom": "mA", "spanning": "V", "vermogen": "W"}


def load_guards():
    try:
        data = json.loads(GUARD_FILE.read_text(encoding="utf-8"))
        out = []
        for d, g in zip(data, GUARD_DEFAULTS):
            out.append({k: d.get(k, v) for k, v in g.items()})
        return out + [dict(g) for g in GUARD_DEFAULTS[len(out):]]
    except (OSError, ValueError, TypeError, AttributeError):
        return [dict(g) for g in GUARD_DEFAULTS]


SETTINGS_FILE = korad_paden.bestand("korad_instellingen.json")   # lokaal, niet in git (ntfy-onderwerp, IP)
ERROR_LOG = korad_paden.bestand("korad_fouten.log")
SETTINGS_DEFAULTS = {"uitgebreid": False, "welkom_gezien": False, "bereik": [30.0, 5.0], "model": "", "bereik_per_idn": {}, "taal": "", "thema": "donker", "project": "vrij", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "", "ntfy_aan": False,
                     "geluid_cc": True, "web_poort": 8085, "web_code": "", "web_aan": False, "mini_pos": "",
                     "spraak_aan": False, "api_aan": False, "api_poort": 8086, "api_code": "",
                     "afdruk_actief": ""}
# Grens per project: het paneel weigert alles daarboven (instellen, geheugenknoppen, testprogramma's, accusimulatie)
# en zet de uitgang uit als de voeding aan de voorkant hoger wordt gezet.
PROJECT_FILE = korad_paden.bestand("korad_projecten.json")
MAX_V, MAX_A = 30.0, 5.0            # het bereik van de aangesloten voeding; zet_bereik() past het aan
PROJECT_KLEUREN = ("#38BDF8", "#A78BFA", "#F472B6", "#2DD4BF", "#FACC15", "#FB923C", "#94A3B8")
BASIS_PROJECTEN = {
    "vrij": {"naam": "", "kort": tr("Vrij"), "kleur": "#F472B6", "vmax": 30.0, "imax": 5.0,
             "reden": tr("het bereik van de voeding"), "programmas": ""},
}


def schoon_project(p):
    """Een projectprofiel controleren. Geeft een nette kopie, of None als het niet deugt: een beschadigd bestand
    mag een grens nooit ongemerkt verhogen."""
    try:
        vmax, imax = float(p["vmax"]), float(p["imax"])
        naam, kort = str(p["naam"]).strip(), str(p.get("kort") or p["naam"]).strip()
    except (KeyError, TypeError, ValueError):
        return None
    if not (naam and kort and 0 < vmax <= PLAFOND_V and 0 < imax <= PLAFOND_A):
        return None
    kleur = str(p.get("kleur") or "")
    uit = {"naam": naam, "kort": kort, "kleur": kleur if re.fullmatch(r"#[0-9A-Fa-f]{6}", kleur) else PROJECT_KLEUREN[-1],
           "vmax": vmax, "imax": imax, "reden": str(p.get("reden") or tr("eigen grens van dit project")),
           "programmas": str(p.get("programmas") or "")}
    geh = {}
    for k, v in (p.get("geheugens") or {}).items() if isinstance(p.get("geheugens"), dict) else ():
        try:
            pv, pi = float(v[0]), float(v[1])
        except (IndexError, TypeError, ValueError):
            continue
        if k in ("1", "2", "3", "4") and 0 <= pv <= vmax and 0 <= pi <= imax:
            geh[k] = [pv, pi]
    if geh:
        uit["geheugens"] = geh
    if isinstance(p.get("bewaking"), list) and p["bewaking"]:
        regels = []
        for r, basis in zip(p["bewaking"], GUARD_DEFAULTS):
            if not isinstance(r, dict):
                return None
            regel = {k: r.get(k, v) for k, v in basis.items()}
            if (regel["wat"] not in UNITS or regel["richting"] not in ("boven", "onder")
                    or regel["actie"] not in ("uitgang uit", "waarschuwen")):
                return None
            try:
                regel["waarde"], regel["duur"] = float(regel["waarde"]), float(regel["duur"])
            except (TypeError, ValueError):
                return None
            regel["aan"] = bool(regel["aan"])
            regels.append(regel)
        uit["bewaking"] = regels
    return uit


def load_projects():
    uit = json.loads(json.dumps(BASIS_PROJECTEN))
    try:
        data = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return uit
    if isinstance(data, dict):
        for key, p in data.items():
            schoon = schoon_project(p) if isinstance(p, dict) and key != "vrij" else None
            if schoon:
                uit[str(key)] = schoon
    return uit


def save_projects():
    PROJECT_FILE.write_text(json.dumps(PROJECTS, indent=2, ensure_ascii=False), encoding="utf-8")


PROJECTS = load_projects()


def zet_bereik(vmax, imax):
    """Het bereik van de voeding vastleggen. Het project Vrij volgt dat; de andere projecten begrenst _limits()."""
    global MAX_V, MAX_A
    MAX_V, MAX_A = float(vmax), float(imax)
    PROJECTS["vrij"].update(naam=tr("Vrij: 0 tot {0} V, 0 tot {1} A", dec(f"{MAX_V:g}"), dec(f"{MAX_A:g}")),
                            vmax=MAX_V, imax=MAX_A)


def _bereik_ok(b):
    try:
        return len(b) == 2 and geldig_bereik(float(b[0]), float(b[1]))
    except (TypeError, ValueError):
        return False


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        out = {k: data.get(k, v) for k, v in SETTINGS_DEFAULTS.items()}
    except (OSError, ValueError, AttributeError):
        out = dict(SETTINGS_DEFAULTS)
    if out["project"] not in PROJECTS:
        out["project"] = "vrij"
    if not _bereik_ok(out["bereik"]):
        out["bereik"] = list(SETTINGS_DEFAULTS["bereik"])
    eigen = out["bereik_per_idn"] if isinstance(out["bereik_per_idn"], dict) else {}
    out["bereik_per_idn"] = {str(k): [float(b[0]), float(b[1])] for k, b in eigen.items() if _bereik_ok(b)}
    if korad_paden.DEMO:
        out.update(_gedeelde_keuzes()[1])
    return out


def _gedeelde_keuzes():
    """De instellingen van het gewone paneel en daaruit de keuzes die de demo deelt: taal en weergave."""
    try:
        data = json.loads(korad_paden.INSTELLINGEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return data, {k: data[k] for k in ("taal", "thema") if k in data}


def save_settings(st):
    try:
        SETTINGS_FILE.write_text(json.dumps(st, indent=2), encoding="utf-8")
        if korad_paden.DEMO:
            hoofd = _gedeelde_keuzes()[0]
            hoofd.update(taal=st["taal"], thema=st["thema"])
            korad_paden.INSTELLINGEN.write_text(json.dumps(hoofd, indent=2), encoding="utf-8")
    except OSError:
        pass


def ntfy_send(server, topic, title, message, priority=3, tags=(), done=None):
    """Melding naar de telefoon via ntfy. JSON naar de hoofd-URL, zodat titel en tekst UTF-8 mogen zijn.
    Loopt in een eigen thread; done(ok, fout) wordt in die thread aangeroepen."""
    def run():
        try:
            body = json.dumps({"topic": topic, "title": title, "message": message,
                               "priority": priority, "tags": list(tags)}).encode("utf-8")
            req = urllib.request.Request(server.rstrip("/"), data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            ok, err = True, ""
        except Exception as e:
            ok, err = False, str(e)
        if done:
            done(ok, err)
    threading.Thread(target=run, daemon=True).start()


AFDRUK_FILE = korad_paden.bestand("korad_afdrukken.json")      # stroomafdrukken, alleen op deze pc


def load_afdrukken():
    try:
        data = json.loads(AFDRUK_FILE.read_text(encoding="utf-8"))
        return [a for a in data if isinstance(a, dict) and a.get("naam") and isinstance(a.get("starts"), list)]
    except (OSError, ValueError, TypeError):
        return []


def save_afdrukken(lijst):
    try:
        AFDRUK_FILE.write_text(json.dumps(lijst), encoding="utf-8")
    except OSError:
        pass


PROG_DIR = korad_paden.bestand("testprogrammas")
DEFAULT_PROGRAM = {
    "naam": tr("Herstart-test"), "herhalen": 1, "uit_na_afloop": True,
    "stappen": [
        {"overgang": "sprong", "v": 13.8, "i": 0.5, "uit": "aan", "duur": 60},
        {"overgang": "sprong", "v": 13.8, "i": 0.5, "uit": "uit", "duur": 3},
        {"overgang": "sprong", "v": 13.8, "i": 0.5, "uit": "aan", "duur": 60},
        {"overgang": "helling", "v": 11.0, "i": 0.5, "uit": "aan", "duur": 120},
        {"overgang": "helling", "v": 13.8, "i": 0.5, "uit": "aan", "duur": 30},
    ],
}


def parse_duur(txt):
    """'90', '1:30', ':30', '0:30', '1:00:00' of '45 s' naar seconden. Een leeg deel telt als 0."""
    t = txt.strip().lower().replace(",", ".").rstrip("s").strip()
    if not t or t.count(":") > 2:
        raise ValueError(txt)
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + (float(part) if part.strip() else 0.0)
    return secs


def fmt_duur(s):
    s = int(round(s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def load_last_program():
    try:
        return json.loads((PROG_DIR / "laatste.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_PROGRAM))


def save_program(prog, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prog, indent=2), encoding="utf-8")


def expect_text(st):
    """Verwachting van een stap in het kort, voor de tabel in de editor."""
    e = st.get("verwacht") or {}
    parts = []
    lo, hi = e.get("i_min"), e.get("i_max")
    if lo is not None and hi is not None:
        parts.append(f"{nl(lo)}-{nl(hi)} mA")
    elif lo is not None:
        parts.append(tr("min. {0} mA", nl(lo)))
    elif hi is not None:
        parts.append(tr("max. {0} mA", nl(hi)))
    return ", ".join(parts)


REPORT_DIR = korad_paden.bestand("rapporten")


def nlf(x, d):
    return dec(f"{x:.{d}f}")


def nl_date(t):
    d = datetime.fromtimestamp(t)
    return korad_taal.datum(d.day, d.month, d.year)


def beep():
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass


def nl(x):
    """Getal met het decimaalteken van de gekozen taal."""
    return dec(fmt(x))


def fmt_span(s):
    s = int(round(s))
    return f"{s}s" if s < 60 else (f"{s // 60}m" if s % 60 == 0 else f"{s // 60}m{s % 60:02d}")


LOG_DIR = korad_paden.bestand("logs")
WEB_HOST = "0.0.0.0"     # telefoon: luisteren op het thuisnetwerk (de proef zet dit op 127.0.0.1)


def read_log(path):
    """CSV-log van het paneel inlezen: (metingen, markeringen), elk op tijd gesorteerd."""
    pts, marks = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["tijd"]).timestamp()
            pts.append((t, float(row["spanning_V"]), float(row["stroom_A"])))
            for part in (row.get("markering") or "").split(" | "):
                if part.strip():
                    marks.append((t, part.strip()))
    pts.sort()
    return pts, marks


def in_window(data, t0, t1):
    """Punten tussen t0 en t1 uit een op tijd gesorteerde reeks. Loopt van achteren: live kijken blijft snel,
    ook als er uren aan metingen in het geheugen staan."""
    out = []
    for p in reversed(data):
        if p[0] > t1:
            continue
        if p[0] < t0:
            break
        out.append(p)
    out.reverse()
    return out


def stats(pts):
    """Samenvatting van metingen (t, V, A): duur, gemiddelden, uitersten, lading (mAh) en energie (Wh)."""
    if len(pts) < 2:
        return None
    cs, vs = [p[2] for p in pts], [p[1] for p in pts]
    q = e = 0.0
    for a, b in zip(pts, pts[1:]):
        dt = b[0] - a[0]
        if 0 < dt < 2:
            q += dt * (a[2] + b[2]) / 2
            e += dt * (a[1] * a[2] + b[1] * b[2]) / 2
    return {"duur": pts[-1][0] - pts[0][0], "n": len(pts), "i_gem": sum(cs) / len(cs), "i_max": max(cs),
            "i_min": min(cs), "v_gem": sum(vs) / len(vs), "v_max": max(vs), "v_min": min(vs),
            "w_gem": sum(p[1] * p[2] for p in pts) / len(pts), "mah": q / 3.6, "wh": e / 3600}


def fmt_ma(a):
    """Stroom leesbaar: onder 1 A in mA, anders in A."""
    return f"{nlf(a * 1000, 0)} mA" if a < 1 else f"{nlf(a, 2)} A"


def is_opstartcurve(label):
    """De opstartcurve van de gebruiker zelf (het label is vertaald), niet een curve binnen een andere proef."""
    return label in ("opstartcurve", tr("opstartcurve"))


def curve_analysis(c):
    """Uitleg bij een opstartcurve in gewone taal."""
    pts, out = c["pts"], []
    if c["cc_at"] is not None:
        v = c["cc_at"]
        if v < 1.5:
            out.append(tr("De stroomgrens werd al bij {0} V bereikt. Dat is bijna altijd kortsluiting of een "
                          "diode die verkeerd om zit (die geleidt dan vanaf ongeveer 0,7 V). De uitgang is "
                          "uitgezet.", nlf(v, 1)))
        else:
            out.append(tr("De stroomgrens ({0}) werd bereikt bij {1} V. Er trekt iets meer dan verwacht; de "
                          "uitgang is uitgezet. Zoek een verkeerd geplaatst onderdeel, of de stroomgrens is te "
                          "laag voor wat er op de print zit.", fmt_ma(c['i_lim']), nlf(v, 1)))
        return out
    low = [p for p in pts if p[0] <= 3.0]
    if low and max(p[2] for p in low) > 0.010:
        out.append(tr("Onder 3 V loopt al {0} mA. Voor een motor, lampje of weerstand is dat gewoon. Een print "
                      "trekt daar bijna niets: zoek dan een tinbrug, of een diode of elco die verkeerd om zit.",
                      nlf(max((p[2] for p in low)) * 1000, 0)))
    if len(pts) > 4:
        end_i = pts[-1][2] if c.get("i_end") is None else c["i_end"]
        mid = [p for p in pts if 3.5 <= p[0] <= 9.0]
        if mid:
            peak = max(mid, key=lambda p: p[2])
            if peak[2] > 0.02 and peak[2] > end_i * 1.3:
                out.append(tr("Rond {0} V trekt de print het meest ({1} mA). Dat is normaal met een schakelende "
                              "regelaar: die trekt bij lage spanning meer stroom voor hetzelfde vermogen.", nlf(peak[0], 1), nlf(peak[2] * 1000, 0)))
    if not out:
        out.append(tr("Geen bijzonderheden: de stroom loopt rustig mee met de spanning."))
    if pts:
        end_i = pts[-1][2] if c.get("i_end") is None else c["i_end"]
        out.append(tr("Bij {0} V loopt {1} mA.", nlf(c['v_end'], 1), nlf(end_i * 1000, 0)))
    return out


def svg_curve(pts, w=520, h=180, i_lim=None, cc_at=None):
    """Kleine opstartcurve als SVG voor de rapporten: x = spanning, y = stroom."""
    if len(pts) < 2:
        return ""
    L, R, T, B = 46, 10, 10, 26
    pw, ph = w - L - R, h - T - B
    xmax = max(max(p[0] for p in pts), 1.0)
    ymax = nice_ceil(max(max(p[2] for p in pts) * 1000, 5) * 1.2)
    X = lambda v: L + pw * v / xmax
    Y = lambda ma: T + ph * (1 - min(ma / ymax, 1))
    o = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" style="width:{w}px;max-width:100%">',
         f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="#F3EEDF"/>']
    for k in range(5):
        y = T + ph * k / 4
        o.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="#DDD5C1"/>')
        o.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#6E6A60">'
                 f'{nl(ymax * (1 - k / 4))}</text>')
    for k in range(0, int(xmax) + 1, 2):
        o.append(f'<text x="{X(k):.1f}" y="{T + ph + 16}" text-anchor="middle" font-size="11" fill="#6E6A60">{k}</text>')
    o.append(f'<text x="{L + pw}" y="{h - 2}" text-anchor="end" font-size="11" fill="#6E6A60">V</text>')
    o.append(f'<text x="4" y="{T + 8}" font-size="11" fill="#6E6A60">mA</text>')
    if i_lim and i_lim * 1000 <= ymax:
        o.append(f'<line x1="{L}" y1="{Y(i_lim * 1000):.1f}" x2="{L + pw}" y2="{Y(i_lim * 1000):.1f}" '
                 f'stroke="#D9301F" stroke-dasharray="5 4"/>')
    line = " ".join(f"{X(p[0]):.1f},{Y(p[2] * 1000):.1f}" for p in pts)
    o.append(f'<polyline points="{line}" fill="none" stroke="#C98400" stroke-width="2"/>')
    if cc_at is not None:
        last = pts[-1]
        o.append(f'<circle cx="{X(last[0]):.1f}" cy="{Y(last[2] * 1000):.1f}" r="5" fill="#D9301F"/>')
    o.append("</svg>")
    return "".join(o)


def local_ip():
    """IP-adres van deze laptop op het thuisnetwerk (er gaat niets het netwerk op)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def qr_photo(text, module_px):
    """QR-code als PhotoImage (qrcodegen van Project Nayuki, MIT, staat naast dit programma). None als hij ontbreekt."""
    try:
        from qrcodegen import QrCode
    except ImportError:
        return None
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    n, border = qr.get_size(), 4
    im = Image.new("RGB", (n + 2 * border, n + 2 * border), "#FFFFFF")
    pix = im.load()
    for y in range(n):
        for x in range(n):
            if qr.get_module(x, y):
                pix[x + border, y + border] = (0, 0, 0)
    size = im.width * module_px
    return ImageTk.PhotoImage(im.resize((size, size), Image.NEAREST))


WEB_PAGE = r"""<!doctype html>
<html lang="__TAAL__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0F1216">
<title>CurrentBench</title>
<style>
  :root { --bg:#0F1216; --card:#171B21; --card2:#21262E; --line:#2A3039; --text:#E8EBF0; --muted:#8D96A4;
          --red:#FF5E54; --amber:#FFB224; --green:#3CCF7A; --btnred:#D6453C; --blue:#3D7BF2; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.4 "Segoe UI", system-ui, sans-serif;
         padding:16px 16px 28px; }
  header { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px; margin-bottom:12px; }
  header b { font-size:20px; letter-spacing:.02em; } header span.m { color:var(--muted); font-size:20px; }
  .pill { margin-left:auto; display:flex; align-items:center; gap:6px; font-size:13px; color:var(--muted); }
  .dot { width:10px; height:10px; border-radius:50%; background:#3A414C; }
  .alarm { background:#3A1A18; border:1px solid var(--btnred); color:#FFB3AD; border-radius:10px; padding:10px 12px;
           margin-bottom:12px; font-weight:600; }
  .tiles { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; }
  .tile { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 10px 8px; }
  .tile span { display:block; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }
  .tile b { display:block; font-size:clamp(20px, 6.4vw, 26px); font-variant-numeric:tabular-nums; margin-top:2px; }
  .tile small { color:var(--muted); font-size:12px; }
  .row { display:flex; align-items:center; gap:8px; margin:12px 0 8px; flex-wrap:wrap; }
  .chip { padding:3px 10px; border-radius:20px; background:var(--card2); font-size:13px; font-weight:600; }
  .muted { color:var(--muted); font-size:13px; margin:4px 0; overflow-wrap:anywhere; }
  canvas { width:100%; height:170px; display:block; background:#12161B; border:1px solid var(--line); border-radius:12px; }
  button { font:inherit; border:0; border-radius:12px; cursor:pointer; }
  #off { width:100%; margin:16px 0 12px; padding:16px; background:var(--btnred); color:#fff; font-size:18px;
         font-weight:700; letter-spacing:.02em; }
  #off:active { filter:brightness(1.15); }
  .mark { display:flex; gap:8px; }
  .mark input { flex:1; min-width:0; font:inherit; padding:10px 12px; border-radius:10px; border:1px solid var(--line);
                background:var(--card2); color:var(--text); }
  .mark button { padding:0 16px; background:var(--card2); color:var(--text); border:1px solid var(--line); }
  .foot { color:var(--muted); font-size:12px; margin-top:16px; }
  :focus-visible { outline:2px solid var(--blue); outline-offset:2px; }
</style></head>
<body>
<header><b>CurrentBench</b><span class="m">__MODEL__</span>
  <span class="pill"><span class="dot" id="dot"></span><span id="st">verbinden...</span></span></header>
<div class="alarm" id="alarm" hidden></div>
<div class="tiles">
  <div class="tile"><span>@@Spanning@@</span><b id="v" style="color:var(--red)">--</b><small id="vs"></small></div>
  <div class="tile"><span>@@Stroom@@</span><b id="i" style="color:var(--amber)">--</b><small id="is"></small></div>
  <div class="tile"><span>@@Vermogen@@</span><b id="w" style="color:var(--green)">--</b><small>W</small></div>
</div>
<div class="row"><span class="chip" id="mode">--</span><span class="chip" id="out">--</span>
  <span class="muted" id="grens"></span></div>
<canvas id="c" width="700" height="340" aria-label="@@Spanning en stroom, laatste vijf minuten@@"></canvas>
<p class="muted" id="prog"></p>
<button id="off">@@Uitgang uit@@</button>
<div class="mark"><input id="txt" maxlength="60" placeholder="@@Notitie als markering@@" aria-label="@@Notitie@@">
  <button id="mk">@@Plaatsen@@</button></div>
<p class="foot">Vanaf de telefoon kun je kijken, een markering plaatsen en de uitgang uitzetten. Aanzetten of de
  spanning veranderen kan alleen aan de laptop.</p>
<script>
const K = "__CODE__";
const $ = (id) => document.getElementById(id);
const nl = (x, d) => (x === null || x === undefined) ? "--" : x.toFixed(d).replace(".", __KOMMA__ ? "," : ".");
let last = 0;
function draw(pts) {
  const c = $("c"), g = c.getContext("2d"), W = c.width, H = c.height;
  g.clearRect(0, 0, W, H);
  g.strokeStyle = "#222831"; g.lineWidth = 1;
  for (let k = 1; k < 4; k++) { g.beginPath(); g.moveTo(0, H * k / 4); g.lineTo(W, H * k / 4); g.stroke(); }
  if (!pts || pts.length < 2) return;
  let vmax = 1, imax = 0.01;
  for (const p of pts) { vmax = Math.max(vmax, p[1]); imax = Math.max(imax, p[2]); }
  vmax *= 1.15; imax *= 1.25;
  const X = (a) => W - (a / 300) * W;
  for (const [idx, max, col] of [[2, imax, "#FFB224"], [1, vmax, "#FF5E54"]]) {
    g.beginPath(); g.strokeStyle = col; g.lineWidth = 3;
    pts.forEach((p, n) => { const x = X(p[0]), y = H - 8 - (H - 16) * p[idx] / max; n ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  }
  g.fillStyle = "#8D96A4"; g.font = "22px Segoe UI, sans-serif"; g.fillText("@@laatste 5 minuten@@", 12, 30);
}
async function poll() {
  try {
    const r = await fetch("/api/stand?k=" + K, {cache: "no-store"});
    if (!r.ok) throw new Error(r.status);
    const s = await r.json();
    last = Date.now();
    $("dot").style.background = s.verbonden ? "#3CCF7A" : "#FF5E54";
    $("st").textContent = s.verbonden ? "@@verbonden@@" : "@@voeding niet verbonden@@";
    $("v").textContent = nl(s.v, 2); $("i").textContent = nl(s.i, 3);
    $("w").textContent = (s.v === null || s.i === null) ? "--" : nl(s.v * s.i, 2);
    $("vs").textContent = s.vset === null ? "" : "@@ingesteld@@ " + nl(s.vset, 2) + " V";
    $("is").textContent = s.iset === null ? "" : "@@grens@@ " + nl(s.iset, 3) + " A";
    $("mode").textContent = !s.uit ? "@@uitgang uit@@" : (s.cc ? "@@CC begrensd@@" : "CV");
    $("mode").style.color = s.uit && s.cc ? "#FF5E54" : "";
    $("out").textContent = s.uit ? "@@uitgang aan@@" : "@@uitgang uit@@";
    $("out").style.color = s.uit ? "#3CCF7A" : "";
    $("grens").textContent = "@@Grens@@: " + s.grens;
    $("alarm").hidden = !s.alarm; $("alarm").textContent = s.alarm;
    $("prog").textContent = s.programma || "";
    draw(s.punten);
  } catch (e) {
    $("dot").style.background = "#FF5E54";
    $("st").textContent = "@@geen verbinding met het paneel@@";
  }
}
$("off").onclick = async () => {
  if (!confirm("@@Uitgang van de voeding uitzetten?@@")) return;
  try { await fetch("/api/uit?k=" + K, {method: "POST"}); } catch (e) {}
  poll();
};
$("mk").onclick = async () => {
  const t = $("txt").value.trim(); if (!t) return;
  try { await fetch("/api/markering?k=" + K, {method: "POST", body: t}); $("txt").value = ""; } catch (e) {}
};
$("txt").addEventListener("keydown", (e) => { if (e.key === "Enter") $("mk").click(); });
poll(); setInterval(poll, 1000);
</script>
</body></html>
"""


def web_pagina(code, model=""):
    """De telefoonpagina met de code, de taal en de vertaalde teksten ingevuld."""
    pagina = WEB_PAGE.replace("__CODE__", code).replace("__TAAL__", korad_taal.huidig()).replace("__MODEL__", html.escape(model))
    pagina = pagina.replace("__KOMMA__", "true" if dec("1.5") == "1,5" else "false")
    return re.sub(r"@@(.+?)@@", lambda m: html.escape(tr(m.group(1)), quote=True), pagina)


def make_web_handler(app):
    """HTTP-afhandeling voor de telefoonpagina. Alles behalve de code in de link wordt geweigerd; de telefoon kan
    alleen kijken, een markering plaatsen en de uitgang UIT zetten (via de hoofdthread)."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "KoradPaneel"

        def log_message(self, *a):
            pass

        def _check(self):
            u = urllib.parse.urlparse(self.path)
            given = urllib.parse.parse_qs(u.query).get("k", [""])[0]
            code = app.settings.get("web_code") or ""
            return u.path, bool(code) and hmac.compare_digest(given.encode(), code.encode())

        def _send(self, status, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _deny(self):
            self._send(403, tr("Geen toegang. Open de link of QR-code uit CurrentBench."), "text/plain; charset=utf-8")

        def do_GET(self):
            path, ok = self._check()
            if not ok:
                return self._deny()
            if path == "/":
                return self._send(200, web_pagina(app.settings["web_code"], "DEMO" if korad_paden.DEMO else app.settings["model"]), "text/html; charset=utf-8")
            if path == "/api/stand":
                return self._send(200, json.dumps(app._web_snap or {}), "application/json")
            self._send(404, tr("Niet gevonden"), "text/plain; charset=utf-8")

        def do_POST(self):
            path, ok = self._check()
            if not ok:
                return self._deny()
            n = min(int(self.headers.get("Content-Length") or 0), 2000)
            body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            if path == "/api/uit":
                app.inq.put(("call", lambda: app._emergency_stop("telefoon")))
                return self._send(200, '{"ok":1}', "application/json")
            if path == "/api/markering":
                text = " ".join(body.split())[:60]
                if text:
                    app.inq.put(("call", lambda: app._add_marker(tr("telefoon: {0}", text))))
                return self._send(200, '{"ok":1}', "application/json")
            self._send(404, tr("Niet gevonden"), "text/plain; charset=utf-8")

    return Handler


# ---------------------------------------------------------------- voeding
# ---------------------------------------------------------------- onderdelentester, rooktest, werkboek, spraak (06-10-2026)
WORKBOOK_FILE = korad_paden.bestand("korad_werkboek.json")   # werkboek: alles wat je hebt gemeten, op datum
PART_MODES = {   # per soort onderdeel: spanning, stroomgrens, uitleg
    "diode": {"naam": tr("Diode of led"), "v": 5.0, "i": 0.010, "kort": tr("5 V, grens 10 mA"), "timeout": 8.0,
              "hoe": tr("Rode klem aan de anode (bij een led de lange poot), zwarte klem aan de kathode: de kant "
                        "met de streep, bij een led de korte poot. Weet je de richting niet? Meet gewoon: zonder "
                        "stroom zit hij andersom. Een led brandt zacht tijdens de meting.")},
    "weerstand": {"naam": tr("Weerstand"), "v": 1.0, "i": 0.100, "kort": tr("1 V, grens 100 mA"), "timeout": 8.0,
                  "hoe": tr("De weerstand tussen de rode en de zwarte klem; de richting maakt niet uit. Goed "
                            "voor ongeveer 1 tot 200 Ω. Hogere en heel lage waarden meet je met een multimeter.")},
}
PART_SCALES = {   # schaal onder de uitslag: van, tot, logaritmisch, zones (van, tot, tekst, kleur)
    "diode": (0.0, 4.0, False, ((0.0, 0.1, "kort", "#4A2422"), (0.1, 0.45, tr("schottky"), "#1E3550"),
                                (0.45, 0.95, tr("silicium"), "#1D4A33"), (1.5, 2.4, tr("led rood/geel"), "#55381A"),
                                (2.4, 3.8, tr("led groen/blauw/wit"), "#1C3D5C"))),
    "weerstand": (0.5, 1000.0, True, ((1.0, 200.0, tr("goed te meten"), "#1D4A33"),)),
}


def part_verdict(mode, v, i, cc):
    """Uitleg bij een onderdeelmeting: (kop, uitleg). cc = de voeding begrensde de stroom."""
    if mode == "diode":
        if v < 0.10 and (cc or i >= 0.005):
            return tr("Kortsluiting"), tr("Bijna 0 V bij 10 mA: kortsluiting, of een doorgeslagen diode.")
        if not cc:
            if i < 0.002:
                return tr("Geen stroom"), (tr("Bij 5 V loopt er niets: de diode zit in sperrichting (draai hem om en "
                                          "meet opnieuw), of hij is onderbroken."))
            return (tr("{0} mA bij {1} V", nlf(i * 1000, 0), nlf(v, 2)),
                    tr("De stroom komt niet aan de grens van 10 mA: een led met een ingebouwde weerstand, of een "
                       "weerstand in plaats van een diode?"))
        if v < 0.45:
            return (tr("Schottkydiode: {0} V", nlf(v, 2)), tr("Lage doorlaatspanning: een schottkydiode, in "
                                                        "doorlaatrichting. De streep (kathode) zit aan de zwarte "
                                                        "klem."))
        if v < 0.95:
            return (tr("Diode: {0} V", nlf(v, 2)), tr("Een gewone siliciumdiode in doorlaatrichting; de streep "
                                                "(kathode) zit aan de zwarte klem."))
        if v < 1.5:
            return f"{nlf(v, 2)} V", tr("Meer dan een gewone diode: twee diodes in serie, of een diode met een "
                                        "weerstand?")
        if v < 2.4:
            return tr("Led: {0} V", nlf(v, 2)), tr("Een rode, oranje of gele led. De lange poot (anode) zit aan de "
                                             "rode klem.")
        if v < 3.8:
            return tr("Led: {0} V", nlf(v, 2)), tr("Een groene, blauwe of witte led. De lange poot (anode) zit aan de "
                                             "rode klem.")
        return f"{nlf(v, 2)} V", tr("Hoger dan een led: meer leds in serie?")
    if mode == "weerstand":
        if not cc and i < 0.0015:
            return tr("Meer dan 700 Ω"), (tr("Bij 1 V loopt bijna niets: een hoge weerstand, of hij is onderbroken. "
                                          "Meet deze met een multimeter."))
        if v < 0.02:
            return tr("Bijna 0 Ω"), tr("Kortsluiting of een draad (minder dan 0,2 Ω).")
        r = v / max(i, 0.0005)
        if i < 0.005:
            return tr("Ongeveer {0} Ω", nlf(r, 0)), tr("Grof: bij 1 V loopt maar weinig stroom. Meet deze "
                                                  "nauwkeuriger met een multimeter.")
        err = max(0.002 / i, 0.01 / v) * 100
        txt = tr("Op ongeveer {0} % nauwkeurig: de voeding meet de stroom in stappen van 1 mA.", nlf(err, 0))
        if r < 5:
            txt += tr(" Bij zo'n kleine waarde tellen de meetsnoeren mee (samen ongeveer 0,05 Ω).")
        return f"{nlf(r, 2 if r < 10 else 1 if r < 100 else 0)} Ω", txt
    return tr("Geen meting"), ""


WB_KINDS = {   # soort in het werkboek: naam en kleur (staafjes per dag)
    "opstartcurve": (tr("Opstartcurve"), "#FFB224"), "onderdeel": (tr("Onderdeel"), "#FF8A5C"),
    "programma": (tr("Testprogramma"), "#F2D16B"),
    "controle": (tr("Controle"), "#4FD1C5"), "nachttest": (tr("Nachttest"), "#A98BF0"), "log": (tr("Log"), "#8D96A4"),
    "rapport": (tr("Rapport"), "#6F9CF7"), "vergelijking": (tr("Vergelijking"), "#5BB8F5"), "notitie": (tr("Notitie"), TEXT),
}


def load_workbook():
    try:
        data = json.loads(WORKBOOK_FILE.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and "t" in e and "soort" in e]
    except (OSError, ValueError, TypeError):
        return []


def save_workbook(wb):
    try:
        WORKBOOK_FILE.write_text(json.dumps(wb[-500:], indent=1), encoding="utf-8")
    except OSError:
        pass


def donut_image(parts, d, bg, thick=0.17):
    """Ring met gekleurde stukken: parts = [(aantal, kleur)]."""
    ss = 3
    D = d * ss
    im = Image.new("RGB", (D, D), bg)
    dr = ImageDraw.Draw(im)
    w = max(ss, int(D * thick))
    box = (ss, ss, D - ss - 1, D - ss - 1)
    total = sum(n for n, _ in parts if n > 0)
    used = [(n, c) for n, c in parts if n > 0]
    if not total:
        dr.arc(box, 0, 360, fill=LINE, width=w)
    else:
        gap = 2.5 if len(used) > 1 else 0.0
        a = -90.0
        for n, col in used:
            sweep = 360.0 * n / total
            dr.arc(box, a + gap / 2, a + sweep - gap / 2, fill=col, width=w)
            a += sweep
    return ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS))


def spoken(text):
    """Eenheden voluit voor de stem: '13,8 V' wordt '13,8 volt'."""
    eenheden = korad_taal.eenheden_gesproken()
    return re.sub(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(mAh|mA|Wh|V|A|W|Ω|%)(?!\w)",
                  lambda m: f"{m.group(1)} {eenheden[m.group(2)]}", str(text))


# Gesproken meldingen: een verborgen PowerShell-proces met de spraak van Windows (Windows.Media.SpeechSynthesis; dat
# zijn ook de stemmen die je via Instellingen > Tijd en taal > Spraak toevoegt). Het leest regels op stdin en spreekt
# ze een voor een uit; voor elke regel antwoordt het met GESPROKEN en de tekst.
SPEAK_PS = r'''param([string]$Taal = 'nl', [string]$Voorkeur = 'nl-NL', [switch]$Stil, [string]$Wav = '')
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime] | Out-Null
    $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
        Where-Object { $_.Language -like ($Taal + '*') } |
        Sort-Object { $_.Language -ne $Voorkeur } | Select-Object -First 1
} catch { [Console]::Out.WriteLine('FOUT ' + $_.Exception.Message); [Console]::Out.Flush(); exit 3 }
if (-not $voice) { [Console]::Out.WriteLine('GEEN_STEM'); [Console]::Out.Flush(); exit 2 }
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$synth.Voice = $voice
$path = if ($Wav) { $Wav } else { Join-Path $env:TEMP ('korad_spraak_' + $PID + '.wav') }
[Console]::Out.WriteLine('KLAAR ' + $voice.DisplayName + ' (' + $voice.Language + ')')
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line.Trim() -eq '') { continue }
    try {
        $t = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke(
            $null, @($synth.SynthesizeTextToStreamAsync($line)))
        $t.Wait(-1) | Out-Null
        $rs = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($t.Result)
        $fs = [System.IO.File]::Create($path); $rs.CopyTo($fs); $fs.Close(); $rs.Close()
        if (-not $Stil) { (New-Object System.Media.SoundPlayer $path).PlaySync() }
        [Console]::Out.WriteLine('GESPROKEN ' + $line); [Console]::Out.Flush()
    } catch { [Console]::Out.WriteLine('FOUT ' + $_.Exception.Message); [Console]::Out.Flush() }
}
if (-not $Wav) { Remove-Item $path -ErrorAction SilentlyContinue }
'''


class Speaker:
    """Gesproken meldingen in een eigen PowerShell-proces. state: start, ok, geen_stem of fout.
    Wat binnenkomt terwijl het proces nog opstart, wordt bewaard en daarna uitgesproken."""

    def __init__(self, lang=None, silent=False, wav=None):
        self.lang, self.silent, self.wav = lang or korad_taal.huidig(), silent, wav
        self.proc = None
        self.state, self.voice = "start", ""
        self.spoken, self.last = 0, ""
        self.pending = []
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            script = Path(tempfile.gettempdir()) / "korad_spraak.ps1"
            script.write_text(SPEAK_PS, encoding="utf-8-sig")
            args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                    "-Taal", self.lang, "-Voorkeur", korad_taal.stem_voorkeur()] + (["-Stil"] if self.silent else []) + (["-Wav", str(self.wav)] if self.wav else [])
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, creationflags=0x08000000,   # geen consolevenster
                                         text=True, encoding="utf-8", errors="replace")
            first = (self.proc.stdout.readline() or "").strip().lstrip("﻿")
            if first.startswith("KLAAR"):
                with self.lock:
                    self.voice, self.state = first[6:], "ok"
                    waiting, self.pending = self.pending, []
                for text in waiting:
                    self._write(text)
                for line in self.proc.stdout:          # leeglezen, anders loopt de pijp ooit vol
                    if line.startswith("GESPROKEN"):
                        self.last = line[10:].rstrip("\r\n")
                        self.spoken += 1
            else:
                self.state = "geen_stem" if first == "GEEN_STEM" else "fout"
                self.voice = first or tr("PowerShell gaf geen antwoord")
                self.stop()
        except Exception as e:
            self.state, self.voice = "fout", str(e)

    def _write(self, text):
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            self.state = "fout"
            return False

    def say(self, text):
        text = " ".join(str(text).split())
        with self.lock:
            if self.state == "start":
                self.pending.append(text)
                return True
        if self.state != "ok" or not self.proc:
            return False
        return self._write(text)

    def stop(self):
        """Invoer sluiten: het proces spreekt uit wat het nog had en stopt dan zelf."""
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.close()
            except Exception:
                pass


# ---------------------------------------------------------------- meter en lampjes
_DOTS = {}


def dot_image(color, d):
    """Glad rondje (Pillow, overbemonsterd), bewaard per kleur en maat."""
    key = (color, d)
    if key not in _DOTS:
        ss = 4
        im = Image.new("RGBA", (d * ss, d * ss), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=color)
        _DOTS[key] = ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS))
    return _DOTS[key]


def check_images(d):
    """Eigen vinkje (uit, aan): afgerond vierkant, aan = blauw met een wit vinkje."""
    key = ("vinkje", d)
    if key not in _DOTS:
        ss = 4
        D = d * ss
        box = (ss, ss, D - ss - 1, D - ss - 1)
        off = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        ImageDraw.Draw(off).rounded_rectangle(box, radius=int(D * 0.22), outline=MUTED, width=ss * 2, fill=CARD_2)
        on = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        dr = ImageDraw.Draw(on)
        dr.rounded_rectangle(box, radius=int(D * 0.22), fill=BLUE)
        dr.line([(D * 0.27, D * 0.52), (D * 0.44, D * 0.68), (D * 0.74, D * 0.35)], fill="#FFFFFF",
                width=int(D * 0.11), joint="curve")
        _DOTS[key] = tuple(ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS)) for im in (off, on))
    return _DOTS[key]


class Gauge(tk.Canvas):
    """Ringmeter: dunne ring met kleurverloop en gloed (Pillow, overbemonsterd), grote waarde in het midden."""

    START, SWEEP = 135, 270     # graden met de klok mee vanaf rechts: van linksonder over boven naar rechtsonder

    def __init__(self, master, unit, color, size=168, bg=CARD):
        self.S = px(size)
        self.SS = 2 if self.S > 260 else 3
        super().__init__(master, width=self.S, height=self.S, bg=bg, highlightthickness=0)
        self.unit, self.color, self.bgc = unit, color, bg
        self.vmax, self.mark, self.redzone = 1.0, None, None
        self.target = self.pos = 0.0
        self.drawn = None
        self.photo = None
        self.w = max(px(5), round(self.S * 0.042))       # dikte van de ring
        self.r = self.S / 2 - px(12) - self.w / 2        # straal tot het midden van de ring
        c = self.S / 2
        self.img = self.create_image(0, 0, anchor="nw")
        self.val = self.create_text(c, c - px(size * 0.035), text="--", fill=color,
                                    font=(FONT_NUM, round(size * 0.178)))
        self.create_text(c, c + px(size * 0.15), text=unit, fill=MUTED, font=(FONT, round(size * 0.072)))
        ex, ey = self.r * 0.7071, c + self.r * 0.7071 + self.w + px(3)
        self.create_text(c - ex, ey, text="0", fill=DIM, font=(FONT, 8))
        self.hi = self.create_text(c + ex, ey, text="1", fill=DIM, font=(FONT, 8))
        self._prepare()
        self._render()

    def set_scale(self, vmax, mark=None, redzone=None):
        if (vmax, mark, redzone) != (self.vmax, self.mark, self.redzone):
            nieuw_vlak = (vmax, redzone) != (self.vmax, self.redzone)
            self.vmax, self.mark, self.redzone = vmax, mark, redzone
            self.itemconfigure(self.hi, text=nl(vmax))
            if nieuw_vlak:
                self._prepare()
            self._render()

    def show(self, text):
        self.itemconfigure(self.val, text=text)

    def _box(self, radius, width):       # Pillow tekent de lijndikte naar binnen vanaf de rand van het vak
        c = self.S * self.SS / 2
        o = radius + width / 2
        return (c - o, c - o, c + o, c + o)

    def _pt(self, frac, radius):
        c = self.S * self.SS / 2
        a = math.radians(self.START + self.SWEEP * frac)
        return c + radius * math.cos(a), c + radius * math.sin(a)

    def _kleur_op(self, frac):
        return blend(blend(self.bgc, self.color, 0.74), lighten(self.color, 0.14), max(0.0, min(1.0, frac)) ** 0.6)

    def _prepare(self):
        """Wat niet meebeweegt alvast tekenen: de lege ring met rode zone, en de volle ring met kleurverloop en gloed."""
        ss = self.SS
        size = self.S * ss
        r, w = self.r * ss, self.w * ss
        basis = Image.new("RGB", (size, size), self.bgc)
        d = ImageDraw.Draw(basis)
        spoor = blend(self.bgc, TEXT, 0.11)
        d.arc(self._box(r, w), self.START, self.START + self.SWEEP, fill=spoor, width=int(w))
        for f in (0, 1):
            x, y = self._pt(f, r)
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=spoor)
        if self.redzone and self.vmax:   # rode band buiten de ring: de grens van het project of de stroomgrens
            f1, f2 = (max(0.0, min(1.0, z / self.vmax)) for z in self.redzone)
            rw = max(ss * 2, int(w * 0.5))
            d.arc(self._box(r + w / 2 + px(3) * ss + rw / 2, rw), self.START + self.SWEEP * f1,
                  self.START + self.SWEEP * f2, fill=blend(self.bgc, LED_RED, 0.7), width=rw)
        ring = Image.new("RGB", (size, size), self.bgc)
        dr = ImageDraw.Draw(ring)
        stap = 3
        for hoek in range(0, self.SWEEP, stap):
            dr.arc(self._box(r, w), self.START + hoek, self.START + hoek + stap + 1,
                   fill=self._kleur_op(hoek / self.SWEEP), width=int(w))
        gloed = ring.filter(ImageFilter.GaussianBlur(w * 1.1))
        gloed = Image.blend(Image.new("RGB", (size, size), self.bgc), gloed, 0.8)
        self._basis = basis
        self._vol = ImageChops.lighter(ImageChops.lighter(basis, gloed), ring)

    def _render(self):
        ss = self.SS
        size = self.S * ss
        r, w = self.r * ss, self.w * ss
        frac = max(0.0, min(1.0, self.pos / self.vmax if self.vmax else 0.0))
        if frac > 0.002:
            masker = Image.new("L", (size, size), 0)
            ImageDraw.Draw(masker).pieslice((0, 0, size - 1, size - 1), self.START, self.START + self.SWEEP * frac, fill=255)
            im = Image.composite(self._vol, self._basis, masker)
            d = ImageDraw.Draw(im)
            for f, kl in ((0, self._kleur_op(0)), (frac, self._kleur_op(frac))):
                x, y = self._pt(f, r)
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=kl)
        else:
            im = self._basis.copy()
            d = ImageDraw.Draw(im)
        if self.mark is not None and self.vmax:   # streepje op de ingestelde waarde
            f = max(0.0, min(1.0, self.mark / self.vmax))
            d.line((*self._pt(f, r - w * 0.9), *self._pt(f, r + w * 0.9)), fill=TEXT, width=max(ss * 2, int(w * 0.34)))
        self.photo = ImageTk.PhotoImage(im.resize((self.S, self.S), Image.LANCZOS))
        self.itemconfigure(self.img, image=self.photo)
        self.drawn = self.pos

    def step(self):
        d = self.target - self.pos
        if abs(d) > self.vmax * 0.0005:
            self.pos += d * 0.25
        if self.drawn is None or abs(self.pos - self.drawn) > self.vmax * 0.002:
            self._render()


class Keuze(ttk.Combobox):
    """Keuzelijst die de vertaling toont maar de vaste waarde bewaart."""

    def __init__(self, ouder, waarden, **kw):
        self._waarden = list(waarden)
        super().__init__(ouder, values=[tr(w) for w in self._waarden], **kw)

    def get(self):
        k = self.current()
        return self._waarden[k] if k >= 0 else ""

    def set(self, waarde):
        super().set(tr(waarde))


class Knop(tk.Button):
    """Knop die de tekstkleur bij zijn achtergrond zoekt: wit op een gekleurde knop, anders de gewone tekstkleur."""

    @staticmethod
    def _voorgrond(bg):
        return "#FFFFFF" if bg in GEKLEURD else INK

    def configure(self, cnf=None, **kw):
        if "bg" in kw and "fg" not in kw:
            kw["fg"] = kw["activeforeground"] = self._voorgrond(kw["bg"])
        return super().configure(cnf, **kw)

    config = configure


class Lamp(tk.Frame):
    """Lampje met tekst; de tekst licht op als het lampje aan is."""

    def __init__(self, master, text, bg=CARD, size=11):
        super().__init__(master, bg=bg)
        self.d = px(11)
        self.dot = tk.Label(self, image=dot_image(LAMP_OFF, self.d), bg=bg)
        self.dot.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=bg, fg=MUTED, font=(FONT, size))
        self.lbl.pack(side="left", padx=(8, 0))

    def set(self, on, color=LED_GREEN):
        self.dot.config(image=dot_image(color if on else LAMP_OFF, self.d))
        self.lbl.config(fg=TEXT if on else MUTED)


class Spark(tk.Canvas):
    """Klein grafiekje van de laatste minuut, onder een meter."""

    def __init__(self, master, color, width, height, bg=CARD):
        super().__init__(master, width=width, height=height, bg=bg, highlightthickness=0)
        self.color, self.bgc, self.W, self.H = color, bg, width, height

    def teken(self, waarden):
        self.delete("all")
        if len(waarden) < 2:
            return
        lo, hi = min(waarden), max(waarden)
        marge = max(hi - lo, abs(hi) * 0.04, 1e-6)
        mid = (hi + lo) / 2
        rand = px(3)
        hoogte = self.H - 2 * rand
        xy = []
        for k, x in enumerate(waarden):
            xy += [self.W * k / (len(waarden) - 1), rand + hoogte * (0.5 - (x - mid) / marge * 0.5)]
        self.create_polygon(0, self.H, *xy, self.W, self.H, fill=blend(self.bgc, self.color, 0.16), outline="")
        self.create_line(*xy, fill=self.color, width=max(1, px(1.4)))


class _RechtsTekst:
    """Doet alsof het een Label is, maar schrijft rechts in de statusbalk."""

    def __init__(self, balk):
        self.balk, self.tekst = balk, ""

    def config(self, text=None, fg=None):
        if text is not None:
            self.tekst = text
        self.balk.zet_rechts(self.tekst, fg)

    def cget(self, _naam):
        return self.tekst


class StatusBar(tk.Canvas):
    """De brede balk bovenin: de kleur en het woord zeggen in een oogopslag wat de uitgang doet."""

    def __init__(self, master, hoogte=34):
        super().__init__(master, height=px(hoogte), bg=BG, highlightthickness=0)
        self.kleur, self.puls, self.fel, self._cache, self.photo = MUTED, False, True, {}, None
        self._f_links, self._f_rechts = tkfont.Font(family=FONT_NUM, size=13), tkfont.Font(family=FONT, size=10)
        self._volledig, self._t_rechts, self._gepast = "", "", None
        self.img = self.create_image(0, 0, anchor="nw")
        self.links = self.create_text(px(18), px(hoogte) / 2 + px(1), text="", anchor="w", fill=TEXT, font=(FONT_NUM, 13))
        self.r_id = self.create_text(0, px(hoogte) / 2 + px(1), text="", anchor="e", fill=MUTED, font=(FONT, 10))
        self.rechts = _RechtsTekst(self)
        self.bind("<Configure>", lambda e: self._teken())

    def _beeld(self, w, h, kleur, sterkte):
        key = (w, h, kleur, sterkte)
        if key not in self._cache:
            if len(self._cache) > 24:
                self._cache.clear()
            kl = [int(kleur[k:k + 2], 16) for k in (1, 3, 5)]
            ach = [int(BG[k:k + 2], 16) for k in (1, 3, 5)]
            klein = Image.new("RGB", (48, h))
            for x in range(48):
                breed = 0.45 + 0.55 * (1 - x / 47) ** 1.4
                for y in range(h):
                    f = (0.52 * (1 - y / max(h - 1, 1)) ** 1.25 + 0.05) * breed * sterkte
                    klein.putpixel((x, y), tuple(int(a + (b - a) * f) for a, b in zip(ach, kl)))
            groot = klein.resize((w, h), Image.BILINEAR)
            ImageDraw.Draw(groot).rectangle((0, 0, w, max(1, px(2)) - 1), fill=kleur)
            self._cache[key] = ImageTk.PhotoImage(groot)
        return self._cache[key]

    def _teken(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        self.photo = self._beeld(w, h, self.kleur, 1.0 if self.fel or not self.puls else 0.55)
        self.itemconfigure(self.img, image=self.photo)
        self.coords(self.r_id, w - px(18), h / 2 + px(1))
        self._pas_tekst()

    def _pas_tekst(self):
        """Linkertekst inkorten tot hij past; bij een alarm verdwijnt de rechtertekst zodat de melding ruimte heeft."""
        w = self.winfo_width()
        sleutel = (self._volledig, self._t_rechts, self.puls, w)
        if sleutel == self._gepast:
            return
        self._gepast = sleutel
        self.itemconfigure(self.r_id, state="hidden" if self.puls else "normal")
        tekst = self._volledig
        ruimte = w - px(36) - (0 if self.puls else self._f_rechts.measure(self._t_rechts) + px(24))
        if w > 10 and self._f_links.measure(tekst) > ruimte:
            while len(tekst) > 4 and self._f_links.measure(tekst + "...") > ruimte:
                tekst = tekst[:-1]
            tekst = tekst.rstrip() + "..."
        self.itemconfigure(self.links, text=tekst)

    def zet(self, kleur, tekst, puls=False):
        if (kleur, puls) != (self.kleur, self.puls):
            self.kleur, self.puls, self.fel = kleur, puls, True
            self._teken()
        self._volledig = tekst
        self.itemconfigure(self.links, fill=lighten(kleur, 0.25))
        self._pas_tekst()

    def zet_rechts(self, tekst, fg=None):
        self._t_rechts = tekst
        self.itemconfigure(self.r_id, text=tekst)
        self._pas_tekst()
        if fg:
            self.itemconfigure(self.r_id, fill=MUTED if fg == INK else fg)

    def tik(self):
        if self.puls:
            self.fel = not self.fel
            self._teken()


# ---------------------------------------------------------------- applicatie
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(NAAM)
        try:
            self.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        global UI_SCALE
        UI_SCALE = max(1.0, self.winfo_fpixels("1i") / 96)
        self.configure(bg=BG)
        self.geometry(f"{px(1440)}x{px(860)}+{px(30)}+{px(8)}")
        self.minsize(px(1200), px(760))
        self._style()
        self.after(50, self._fit_screen)

        self.dev = None
        self.running = False
        self.inq, self.cmdq = queue.Queue(), queue.Queue()
        self.hist = deque(maxlen=400000)   # ruim 20 uur bij ~5 metingen per seconde (nachttest)
        self.vset = self.iset = self.out = None
        self.log_file = self.log_writer = None
        self.log_rows = 0
        self.span = tk.IntVar(value=60)
        self.presets = load_presets()
        self.pending = None   # (geheugenplaats, tijdstip) na een RCL-commando
        # energieteller
        self.e_start = time.time()
        self.e_last = None
        self.charge_as = 0.0   # ampere-seconden
        self.energy_j = 0.0    # joule (watt-seconden)
        # markeringen en accusimulatie
        self.markers = []      # (tijdstip, tekst)
        self.pending_marker = ""
        self.sim = None        # dict met start, eind, duur, begintijd
        # grafiek: zoom en meetcursor
        self.view = None       # None = live, anders (t0, t1)
        # bewaking
        self.guards = load_guards()
        self.guard_state = [{"since": None, "fired": False} for _ in self.guards]
        self.alarm = None
        # testprogramma's
        self.program = load_last_program()
        self.run = None
        # bron van de grafiek: None = live, anders een geopend logbestand
        self.src = None
        self.idn = ""
        self._cmap = None
        self._mouse_x = None
        self._drag_x0 = None
        self.settings = load_settings()
        self.limit_t = self.ilimit_t = 0.0
        self.cc = False
        self.results = []                   # uitkomsten van verwachtingen in testprogramma's
        # gereedschap (06-10-2026)
        self.curve = None                   # lopende opstartcurve
        self.curves = []                    # afgeronde opstartcurves
        self._curve_cfg = {"v": 13.8, "i": 0.10, "stap": 0.2}
        self.night = self.night_result = None
        self._night_cfg = {"uren": 8.0, "v": 13.8, "i": 1.5, "piek": 1200.0, "log": True, "uit": False}
        self.cmp = {}
        self.cmp_what = tk.StringVar(value="stroom")
        self.mini = None
        self.web = None
        self._web_snap = None
        self._cc_since, self._cc_beeped = None, False
        # onderdelentester, rooktest, werkboek, spraak (06-10-2026)
        self.part = None                    # lopende onderdeelmeting
        self.parts = []                     # uitslagen van de onderdelentester
        self._parts_seq = 0
        self._pt_sel = "diode"
        self._pt_msg = ""
        self.wb = load_workbook()
        self._wb_log = None
        self.speaker = None
        self._said = ("", 0.0)
        self.xgauges = []                   # ringmeters in losse vensters (onderdelentester)
        # vernieuwing november 2026: herstartteller, stroomafdruk, vlaggetjes, werkbankstand, koppeling
        self.dips = ana.DipTeller()
        self._dip_mark_t = 0.0
        self._out_prev = self._out_on_t = self._out_off_t = None
        self.afdrukken = load_afdrukken()
        self.afdruk_controle = self._afdruk_laatste = None
        self._flags = []
        self._mouse_y = None
        self._tipfont = None
        self.bench = None
        self._spark_t = 0.0
        self._puls_n = 0
        self._api = None
        self.preset_eigen = set()
        self.kp = sys.modules[__name__]     # korad_acties.py gebruikt dezelfde module, ook bij starten als script
        self.acties_log = deque(maxlen=200)
        self.actie_nr = 0
        self.actie_loopt = None
        self._project_gegevens()
        if not self.settings.get("api_code"):
            self.settings["api_code"] = secrets.token_urlsafe(18)
            save_settings(self.settings)

        zet_bereik(*self.settings["bereik"])
        self._build()
        self._toon_model()
        self._refresh_ports()
        if korad_paden.DEMO:
            self.after(400, self._connect)
        self.after(50, self._pump)
        self.after(33, self._animate)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Escape>", lambda e: self._emergency_stop("Esc"))
        if self.settings.get("web_aan"):
            self.after(800, self._web_start)
        if self.settings.get("spraak_aan"):
            self.after(1500, self._speech_ensure)
        if self.settings.get("api_aan"):
            self.after(700, self._api_start)
        self.bind_all("<F11>", lambda e: self._toggle_bench())
        if not self.settings.get("welkom_gezien") and not korad_paden.DEMO:
            self.after(600, self._open_welkom)

    # ---------- opbouw
    def _btn(self, parent, text, cmd, width=None, bg=PANEL_DARK, fg=None, size=10):
        fg = fg or Knop._voorgrond(bg)
        b = Knop(parent, text=text, command=cmd, width=width, bg=bg, fg=fg, activebackground=lighten(bg, 0.2),
                      activeforeground=fg, relief="flat", bd=0, padx=px(12), pady=px(5), font=(FONT, size),
                      cursor="hand2", highlightthickness=0, disabledforeground=DIM)
        b.bind("<Enter>", lambda e: self._hover(b, True))
        b.bind("<Leave>", lambda e: self._hover(b, False))
        return b

    @staticmethod
    def _hover(b, on):
        """Knop iets lichter onder de muis; als de code intussen de kleur veranderde, die laten staan."""
        if on:
            b._rest = b.cget("bg")
            b._hov = lighten(b._rest, 0.12)
            tk.Button.configure(b, bg=b._hov)
        elif getattr(b, "_hov", None) == b.cget("bg"):
            tk.Button.configure(b, bg=b._rest)

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD_2, bordercolor=LINE,
                     lightcolor=CARD_2, darkcolor=CARD_2, troughcolor=CARD, arrowcolor=TEXT, font=(FONT, 10))
        st.configure("TCombobox", fieldbackground=CARD_2, background=CARD_2, foreground=TEXT, arrowcolor=TEXT,
                     padding=px(4), arrowsize=px(12))
        st.map("TCombobox", fieldbackground=[("readonly", CARD_2)], foreground=[("readonly", TEXT)],
               background=[("active", CARD_3), ("readonly", CARD_2)], selectbackground=[("readonly", CARD_2)],
               selectforeground=[("readonly", TEXT)], bordercolor=[("focus", BLUE)], arrowcolor=[("disabled", DIM)])
        st.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, bordercolor=LINE,
                     rowheight=px(28))
        st.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", "#FFFFFF")])
        st.configure("Treeview.Heading", background=CARD_2, foreground=MUTED, relief="flat", font=(FONT, 10, "bold"))
        st.map("Treeview.Heading", background=[("active", CARD_3)])
        for k, v in (("*TCombobox*Listbox.background", CARD_2), ("*TCombobox*Listbox.foreground", TEXT),
                     ("*TCombobox*Listbox.selectBackground", BLUE), ("*TCombobox*Listbox.selectForeground", "#FFFFFF"),
                     ("*TCombobox*Listbox.font", f"{{{FONT}}} 10"),
                     ("*Entry.background", CARD_2), ("*Entry.foreground", TEXT), ("*Entry.insertBackground", TEXT),
                     ("*Entry.highlightColor", BLUE), ("*Text.background", CARD_2), ("*Text.foreground", TEXT),
                     ("*Text.insertBackground", TEXT), ("*Checkbutton.foreground", TEXT),
                     ("*Checkbutton.selectColor", CARD_2), ("*Checkbutton.activeForeground", TEXT),
                     ("*Radiobutton.foreground", TEXT), ("*Radiobutton.selectColor", CARD_2)):
            self.option_add(k, v)

    @staticmethod
    def _workarea():
        """Bruikbaar deel van het scherm (zonder taakbalk), in echte beeldpunten."""
        try:
            r = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
            return r.left, r.top, r.right, r.bottom
        except Exception:
            return 0, 0, 1280, 860

    def _fit_screen(self):
        """Hoofdvenster binnen het werkgebied houden: Windows zet een nieuw venster soms half buiten beeld."""
        wl, wt, wr, wb = self._workarea()
        self.update_idletasks()
        side = max(0, self.winfo_rootx() - self.winfo_x())      # rand links en rechts
        title = max(0, self.winfo_rooty() - self.winfo_y())     # titelbalk
        w = min(self.winfo_width(), wr - wl - 2 * side)
        h = min(self.winfo_height(), wb - wt - title - side)
        x = max(wl, min(self.winfo_x(), wr - w - 2 * side))
        y = max(wt, min(self.winfo_y(), wb - h - title - side))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _center(self, win):
        """Een venster midden boven het paneel zetten, binnen het scherm."""
        try:
            win.update_idletasks()
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            wl, wt, wr, wb = self._workarea()
            x = self.winfo_rootx() + (self.winfo_width() - w) // 2
            y = self.winfo_rooty() + (self.winfo_height() - h) // 3
            x = max(wl, min(x, wr - w - px(8)))
            y = max(wt, min(y, wb - h - px(40)))
            win.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _check(self, parent, text, var, bg=PANEL, size=10):
        off, on = check_images(px(17))
        return tk.Checkbutton(parent, text="  " + text, variable=var, image=off, selectimage=on, compound="left",
                              indicatoron=False, bg=bg, activebackground=bg, selectcolor=bg, fg=TEXT,
                              activeforeground=TEXT, relief="flat", offrelief="flat", overrelief="flat", bd=0,
                              highlightthickness=0, font=(FONT, size), cursor="hand2")

    def _card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE)

    def _caption(self, parent, text, bg=CARD):
        return tk.Label(parent, text=text.upper(), bg=bg, fg=MUTED, font=(FONT, 9, "bold"))

    def _entry(self, parent, width, size=12, justify="right"):
        return tk.Entry(parent, width=width, font=(FONT, size), justify=justify, relief="flat", bg=CARD_2, fg=TEXT,
                        insertbackground=TEXT, highlightthickness=1, highlightbackground=LINE, highlightcolor=BLUE)

    def _build(self):
        G = 16

        # ---- statusbalk over de hele breedte, daaronder de kolom met icoontjes
        self.statusbar = StatusBar(self)
        self.statusbar.pack(side="top", fill="x")
        self._bouw_kolom()

        # ---- kop: naam, project, verbinding
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=G, pady=(12, 10))
        tk.Label(top, text=NAAM, bg=BG, fg=TEXT, font=(FONT_NUM, 18)).pack(side="left")
        self.model_lbl = tk.Label(top, text="", bg=BG, fg=MUTED, font=(FONT, 12))
        self.model_lbl.pack(side="left", padx=(6, 20), pady=(5, 0))
        self.proj_pill = tk.Canvas(top, bg=BG, highlightthickness=0, cursor="hand2", width=px(10), height=px(30))
        self.proj_pill.pack(side="left", padx=(0, 18))
        self.proj_pill.bind("<Button-1>", self._project_menu)
        self.conn_lamp = Lamp(top, tr("Niet verbonden"), bg=BG, size=10)
        self.conn_lamp.pack(side="left")
        self.status_lbl = self.conn_lamp.lbl
        self.conn_btn = self._btn(top, tr("Verbinden"), self._connect, bg=BLUE)
        self.conn_btn.pack(side="right")
        ververs = self._btn(top, ICONEN["ververs"], self._refresh_ports)
        ververs.config(font=(FONT_ICON, 11))
        ververs.pack(side="right", padx=6)
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=24, state="readonly")
        self.port_box.pack(side="right", padx=6)
        self._teken_pill()

        # ---- meters, status, verbruik
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=G)
        self.gauges, self.setlbls, self.sparks = {}, {}, {}
        for key, label, unit, color in (("v", tr("Spanning"), "V", LED_RED), ("i", tr("Stroom"), "A", LED_AMBER),
                                         ("w", tr("Vermogen"), "W", LED_GREEN)):
            card = self._card(row)
            card.pack(side="left", fill="y", padx=(0, 12))
            self._caption(card, label).pack(anchor="w", padx=14, pady=(10, 0))
            g = Gauge(card, unit, color)
            g.pack(padx=14, pady=(0, 0))
            sl = tk.Label(card, text="", bg=CARD, fg=MUTED, font=(FONT, 10))
            sl.pack(pady=(0, 4))
            sp = Spark(card, color, px(168), px(30))
            sp.pack(padx=14, pady=(0, 10), side="bottom")
            self.gauges[key], self.setlbls[key], self.sparks[key] = g, sl, sp

        st = self._card(row)
        st.pack(side="left", fill="y", padx=(0, 12))
        self._caption(st, tr("Status")).pack(anchor="w", padx=14, pady=(10, 6))
        self.lamp_cv = Lamp(st, tr("CV  vaste spanning"))
        self.lamp_cc = Lamp(st, tr("CC  stroom begrensd"))
        self.lamp_out = Lamp(st, tr("Uitgang aan"))
        self.lamp_guard = Lamp(st, tr("Bewaking actief"))
        for l in (self.lamp_cv, self.lamp_cc, self.lamp_out, self.lamp_guard):
            l.pack(anchor="w", padx=14, pady=4)
        self._btn(st, tr("Bewaking instellen"), self._open_guards, size=9).pack(anchor="w", padx=14, pady=(8, 10))
        self.alarm_lbl = tk.Label(st, text="", bg=CARD, fg=BAD, font=(FONT, 10, "bold"), wraplength=px(220),
                                  justify="left", anchor="w")
        self.alarm_lbl.pack(anchor="w", fill="x", padx=14)
        self.alarm_btn = self._btn(st, tr("Alarm wissen"), self._clear_alarm, bg=BTN_RED, size=9)
        self.after(100, self._update_guard_lamp)

        en = self._card(row)
        en.pack(side="left", fill="both", expand=True)
        self.e_title = self._caption(en, tr("Verbruik"))
        self.e_title.pack(anchor="w", padx=14, pady=(10, 0))
        self.e_mah = tk.Label(en, text="0,0 mAh", bg=CARD, fg=LED_AMBER, font=(FONT_NUM, 22), anchor="w")
        self.e_mah.pack(anchor="w", padx=14, pady=(2, 0))
        line = tk.Frame(en, bg=CARD)
        line.pack(fill="x", padx=14)
        self.e_wh = tk.Label(line, text="0,000 Wh", bg=CARD, fg=LED_GREEN, font=(FONT_NUM, 13), anchor="w")
        self.e_wh.pack(side="left")
        self.e_time = tk.Label(line, text="00:00:00", bg=CARD, fg=MUTED, font=(FONT, 10))
        self.e_time.pack(side="left", padx=(12, 0))
        self._btn(line, tr("Op nul"), self._reset_energy, size=9).pack(side="right")
        tk.Frame(en, bg=LINE, height=1).pack(fill="x", padx=14, pady=(10, 8))
        self.s_title = self._caption(en, tr("Stroom in beeld"))
        self.s_title.pack(anchor="w", padx=14)
        grid = tk.Frame(en, bg=CARD)
        grid.pack(fill="x", padx=14, pady=(4, 10))
        self.s_vals = {}
        for n, (key, txt) in enumerate((("max", tr("hoogste")), ("avg", tr("gemiddeld")), ("min", tr("laagste")),
                                        ("q", tr("lading")))):
            cell = tk.Frame(grid, bg=CARD)
            cell.grid(row=n // 2, column=n % 2, sticky="w", padx=(0, 22), pady=2)
            tk.Label(cell, text=txt, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
            lbl = tk.Label(cell, text="--", bg=CARD, fg=LED_AMBER, font=(FONT_NUM, 13), anchor="w")
            lbl.pack(anchor="w")
            self.s_vals[key] = lbl
        self.x_vals = {}
        for n, (key, txt) in enumerate((("dips", tr("herstarts")), ("afdruk", tr("stroomafdruk")))):
            cell = tk.Frame(grid, bg=CARD)
            cell.grid(row=n, column=2, sticky="w", padx=(0, 22), pady=2)
            tk.Label(cell, text=txt, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
            lbl = tk.Label(cell, text="--", bg=CARD, fg=ACCENT, font=(FONT_NUM, 13), anchor="w")
            lbl.pack(anchor="w")
            self.x_vals[key] = lbl

        # ---- bediening (onderaan; eerst ingepakt, zodat de grafiek de rest van de hoogte krijgt)
        ctl = self._card(self)
        ctl.pack(side="bottom", fill="x", padx=G, pady=(12, 14))

        def lab(parent, t, bold=False, muted=False, padx=(0, 0)):
            tk.Label(parent, text=t, bg=CARD, fg=MUTED if muted else TEXT,
                     font=(FONT, 10, "bold" if bold else "normal")).pack(side="left", padx=padx)

        def sep():
            lijn = tk.Frame(ctl, bg=LINE, height=1)
            lijn.pack(fill="x", padx=14)
            return lijn

        r1 = tk.Frame(ctl, bg=CARD)
        r1.pack(fill="x", padx=14, pady=10)
        lab(r1, tr("Spanning"))
        self.v_entry = self._entry(r1, 7, size=13)
        self.v_entry.pack(side="left", padx=(8, 4), ipady=2)
        lab(r1, "V", muted=True, padx=(0, 18))
        lab(r1, tr("Stroomgrens"))
        self.i_entry = self._entry(r1, 7, size=13)
        self.i_entry.pack(side="left", padx=(8, 4), ipady=2)
        lab(r1, "A", muted=True, padx=(0, 14))
        self._btn(r1, tr("Instellen"), self._apply, bg=BLUE).pack(side="left")
        for e in (self.v_entry, self.i_entry):
            e.bind("<Return>", lambda ev: self._apply())
        self.out_btn = self._btn(r1, tr("Uitgang aanzetten"), self._toggle_out, width=17, size=11)
        self.out_btn.config(font=(FONT_NUM, 11), pady=px(7))
        self.out_btn.pack(side="left", padx=18)
        lab(r1, tr("Geheugen"), muted=True, padx=(4, 8))
        self.preset_btns = {}
        for n in (1, 2, 3, 4):
            b = self._btn(r1, "", lambda n=n: self._recall(n), width=6, size=8)
            b.config(pady=px(2))
            b.pack(side="left", padx=3)
            self.preset_btns[n] = b
            self._label_preset(n)
        tk.Label(r1, text=tr("Esc = noodstop"), bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="right")
        self.bediening_btn = self._btn(r1, "", self._wissel_bediening, size=9)
        self.bediening_btn.pack(side="right", padx=(0, 14))

        s2 = sep()
        r2 = tk.Frame(ctl, bg=CARD)
        r2.pack(fill="x", padx=14, pady=10)
        lab(r2, tr("Accu nabootsen"), bold=True, padx=(0, 12))
        lab(r2, tr("van"))
        self.sim_from = self._entry(r2, 5, size=11)
        self.sim_from.insert(0, dec("13.8"))
        self.sim_from.pack(side="left", padx=(6, 4), ipady=1)
        lab(r2, tr("V  naar"))
        self.sim_to = self._entry(r2, 5, size=11)
        self.sim_to.insert(0, dec("11.0"))
        self.sim_to.pack(side="left", padx=(6, 4), ipady=1)
        lab(r2, tr("V  in"))
        self.sim_min = self._entry(r2, 4, size=11)
        self.sim_min.insert(0, "10")
        self.sim_min.pack(side="left", padx=(6, 4), ipady=1)
        lab(r2, tr("min,  R"))
        self.sim_r = self._entry(r2, 4, size=11)
        self.sim_r.insert(0, "0")
        self.sim_r.pack(side="left", padx=(6, 4), ipady=1)
        lab(r2, "m\u03a9", padx=(0, 12))
        self.sim_btn = self._btn(r2, tr("Start"), self._toggle_sim, width=7)
        self.sim_btn.pack(side="left")
        self.sim_lbl = tk.Label(r2, text="", bg=CARD, fg=MUTED, font=(FONT, 10), width=24, anchor="w")
        self.sim_lbl.pack(side="left", padx=10)
        self._btn(r2, tr("Testprogramma's"), self._open_programs).pack(side="right")
        self.prog_lbl = tk.Label(r2, text="", bg=CARD, fg=MUTED, font=(FONT, 10), anchor="e")
        self.prog_lbl.pack(side="right", padx=8)
        self.prog_stop_btn = self._btn(r2, tr("Stop programma"), lambda: self._stop_program(tr("Gestopt"), off=True),
                                       bg=BTN_RED)

        s3 = sep()
        r3 = tk.Frame(ctl, bg=CARD)
        r3.pack(fill="x", padx=14, pady=10)
        lab(r3, tr("Notitie"), bold=True, padx=(0, 12))
        self.mark_entry = self._entry(r3, 34, size=11, justify="left")
        self.mark_entry.pack(side="left", padx=(0, 8), ipady=2)
        self.mark_entry.bind("<Return>", lambda ev: self._add_marker())
        self._btn(r3, tr("Markering plaatsen"), self._add_marker).pack(side="left")
        self.log_btn = self._btn(r3, tr("Log starten"), self._toggle_log)
        self.log_btn.pack(side="right")
        self.log_lbl = tk.Label(r3, text="", bg=CARD, fg=MUTED, font=(FONT, 10))
        self.log_lbl.pack(side="right", padx=8)

        # ---- grafiek
        cc = self._card(self)
        cc.pack(fill="both", expand=True, padx=G, pady=(12, 0))
        head = tk.Frame(cc, bg=CARD)
        head.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(head, text=tr("Spanning en stroom"), bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(side="left")
        for txt, col in ((tr("spanning"), LED_RED), (tr("stroom"), LED_AMBER)):
            tk.Label(head, image=dot_image(col, px(9)), bg=CARD).pack(side="left", padx=(16, 5))
            tk.Label(head, text=txt, bg=CARD, fg=MUTED, font=(FONT, 10)).pack(side="left")
        self.live_btn = self._btn(head, tr("Terug naar live"), self._back_to_live, bg=BTN_AMBER, size=9)
        seg = tk.Frame(head, bg=CARD_2)
        seg.pack(side="right")
        for secs, txt in ((60, tr("1 min")), (300, tr("5 min")), (1800, tr("30 min"))):
            tk.Radiobutton(seg, text=txt, value=secs, variable=self.span, indicatoron=0, bg=CARD_2, fg=TEXT,
                           selectcolor=KEUZE_AAN, activebackground=CARD_3, activeforeground=TEXT, relief="flat", bd=0,
                           padx=px(10), pady=px(3), font=(FONT, 9), cursor="hand2", highlightthickness=0,
                           command=self._go_live).pack(side="left")
        knop_log = self._btn(head, tr("Log openen"), self._open_log, size=9)
        knop_log.pack(side="right", padx=(0, 12))
        knop_rapport = self._btn(head, tr("Rapport maken"), self._report_dialog, size=9)
        knop_rapport.pack(side="right", padx=(0, 6))
        self.chart = tk.Canvas(cc, bg=GLASS, highlightthickness=0, height=px(160))
        self.chart.bind("<Configure>", lambda e: self._draw_chart())
        self.chart.bind("<Motion>", self._on_motion)
        self.chart.bind("<Leave>", self._on_leave)
        self.chart.bind("<ButtonPress-1>", self._on_press)
        self.chart.bind("<B1-Motion>", self._on_motion)
        self.chart.bind("<ButtonRelease-1>", self._on_release)
        self.chart.bind("<Double-Button-1>", lambda e: self._go_live())
        self.chart.bind("<MouseWheel>", self._on_wheel)
        self.chart.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        # eenvoudige bediening: deze delen staan dan niet in beeld (ze bestaan wel, dus alles blijft werken)
        rij = {"fill": "x", "padx": 14, "pady": 10}       # dezelfde opties als bij het opbouwen hierboven
        self._extra_delen = [(en, {"side": "left", "fill": "both", "expand": True}), (s2, {"fill": "x", "padx": 14}),
                             (r2, rij), (s3, {"fill": "x", "padx": 14}), (r3, rij),
                             (knop_log, {"side": "right", "padx": (0, 12)}),
                             (knop_rapport, {"side": "right", "padx": (0, 6)})]
        self._extra_zichtbaar = True
        self._zet_bediening(bool(self.settings.get("uitgebreid")))

    # ---------- eenvoudige of uitgebreide bediening
    def _zet_bediening(self, uitgebreid):
        """Toon of verberg de extra delen van het hoofdvenster. Verbergen kan altijd; de functies zelf blijven
        bereikbaar onder Gereedschap."""
        if uitgebreid != self._extra_zichtbaar:
            for w, info in self._extra_delen:
                if uitgebreid:
                    w.pack(**info)
                else:
                    w.pack_forget()
            self._extra_zichtbaar = uitgebreid
        self.bediening_btn.config(text=tr("Eenvoudig") if uitgebreid else tr("Uitgebreid"))

    def _wissel_bediening(self):
        self.settings["uitgebreid"] = not self._extra_zichtbaar
        save_settings(self.settings)
        self._zet_bediening(self.settings["uitgebreid"])

    def _extra_in_beeld(self):
        """Start er iets dat zijn knoppen in de extra regels heeft (testprogramma, accu, log), dan komen die regels
        in beeld, ook in de eenvoudige stand. De keuze van de gebruiker blijft bewaard zoals hij was."""
        if not self._extra_zichtbaar:
            self._zet_bediening(True)

    # ---------- verbinding
    def _refresh_ports(self):
        ports = [] if korad_paden.DEMO else list(serial.tools.list_ports.comports())
        items = [f"{p.device}  ({p.description})" for p in ports] + [f"{DEMO_POORT}  ({tr('nagebootste voeding')})"]
        self.port_box["values"] = items
        pick = next((i for i, p in zip(items, ports) if "Bluetooth" not in p.description), None)
        if items and not self.port_var.get():
            self.port_var.set(pick or items[0])

    def _connect(self):
        if self.dev:
            self._disconnect(tr("Verbinding verbroken"))
            return
        port = self.port_var.get().split()[0] if self.port_var.get() else ""
        if not port:
            messagebox.showinfo(tr("Geen poort"), tr("Kies eerst een COM-poort."))
            return
        if port == DEMO_POORT and not korad_paden.DEMO:
            self._start_demo()
            return
        try:
            dev = DemoVoeding() if port == DEMO_POORT else Korad(port)
        except serial.SerialException as e:
            messagebox.showerror(tr("Kan poort niet openen"),
                                 tr("{0} kon niet worden geopend.\n\nIs een ander programma (of een "
                                    "Python-venster) er nog mee verbonden?\n\n{1}", port, e))
            return
        herkend = self._herken_model(dev, port)
        if not herkend:
            dev.close()
            return
        idn, model = herkend
        st = dev.status()
        if st and st["out"]:   # bv. na een vastgelopen of gesloten paneel tijdens een proef
            v, i = dev.number("VOUT1?"), dev.number("IOUT1?")
            if messagebox.askyesno(tr("Uitgang stond aan"),
                                   tr("De uitgang van de voeding stond al aan ({0} V, {1} A) toen het paneel "
                                      "verbond. Misschien is het paneel eerder gesloten of vastgelopen terwijl "
                                      "er een proef liep.\n\nUitgang nu uitzetten?", nlf(v or 0, 2), nlf(i or 0, 3)), icon="warning"):
                dev.write("OUT0")
        self.dev, self.running = dev, True
        self.idn = tr("Demo: nagebootste voeding, geen echte meting") if port == DEMO_POORT else idn
        self._zet_model(model)
        self.hist.clear()
        self.status_lbl.config(text=self.idn if port == DEMO_POORT else tr("Verbonden met {0} op {1}", idn, port))
        self.conn_lamp.set(True)
        self.conn_btn.config(text=tr("Verbreken"), bg=CARD_2)
        self._out_prev = None
        self._update_status()
        threading.Thread(target=self._worker, args=(dev,), daemon=True).start()

    def _herken_model(self, dev, port):
        """(idn, model) van wat er op deze poort hangt, of None als het paneel er niet mee moet verbinden."""
        try:
            idn = schoon_idn(dev.query("*IDN?"))
            model = herken(idn)
            eigen = self.settings["bereik_per_idn"].get(sleutel(idn))
            if not model and eigen:
                model = Model(sleutel(idn), *eigen)
            begrijpt = bool(model) or (bool(idn) and begrijpt_opdrachten(dev))
        except (serial.SerialException, OSError) as e:
            messagebox.showerror(tr("Kan poort niet openen"), str(e))
            return None
        if not begrijpt:
            messagebox.showerror(tr("Geen Korad gevonden"),
                                 tr("Op {0} antwoordt geen Korad-voeding.\nControleer de poort en of de voeding "
                                    "aanstaat.", port))
            return None
        if model:
            return idn, model
        if not messagebox.askyesno(tr("Onbekend model"),
                                   tr("Op {0} antwoordt een apparaat dat op een Korad-voeding lijkt, maar dit model kent "
                                      "het paneel niet:\n\n{1}\n\nHet paneel is alleen getest op de KA3005PS. Bij een "
                                      "ander model kunnen metingen en bediening afwijken. Stel eerst een lage stroomgrens "
                                      "in en houd de klemmen leeg.\n\nToch verbinden?", port, idn), icon="warning"):
            return None
        bereik = self._vraag_bereik(sleutel(idn))
        if not bereik:
            return None
        self.settings["bereik_per_idn"] = {**self.settings["bereik_per_idn"], sleutel(idn): list(bereik)}
        return idn, Model(sleutel(idn), *bereik)

    def _vraag_bereik(self, naam):
        """Het bereik van een onbekend model, zoals de gebruiker het van het typeplaatje overneemt. None bij annuleren."""
        win = tk.Toplevel(self, bg=PANEL)
        win.title(tr("Bereik van de voeding"))
        win.transient(self)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        uit = {}
        tk.Label(win, text=naam, bg=PANEL, fg=TEXT, font=(FONT_NUM, 13)).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 4))
        tk.Label(win, text=tr("Vul het maximum in dat op het typeplaatje van de voeding staat. Het paneel gaat daar nooit "
                              "boven."), bg=PANEL, fg=MUTED, wraplength=px(360), justify="left").grid(
            row=1, column=0, columnspan=2, padx=16, pady=(0, 10))
        velden = []
        for rij, tekst in enumerate((tr("Hoogste spanning (V)"), tr("Hoogste stroom (A)")), start=2):
            tk.Label(win, text=tekst, bg=PANEL, fg=TEXT).grid(row=rij, column=0, sticky="w", padx=(16, 8), pady=3)
            veld = tk.Entry(win, width=8, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat")
            veld.grid(row=rij, column=1, sticky="w", padx=(0, 16), pady=3)
            velden.append(veld)
        melding = tk.Label(win, text="", bg=PANEL, fg=BAD)
        melding.grid(row=4, column=0, columnspan=2, padx=16)

        def bewaar():
            try:
                vmax, imax = (float(v.get().replace(",", ".")) for v in velden)
            except ValueError:
                vmax = imax = 0.0
            if not geldig_bereik(vmax, imax):
                melding.config(text=tr("Vul een spanning tot {0} V en een stroom tot {1} A in.", nl(PLAFOND_V), nl(PLAFOND_A)))
                return
            uit["bereik"] = (vmax, imax)
            win.destroy()

        bar = tk.Frame(win, bg=PANEL)
        bar.grid(row=5, column=0, columnspan=2, sticky="e", padx=16, pady=12)
        self._btn(bar, tr("Annuleren"), win.destroy).pack(side="right", padx=(8, 0))
        self._btn(bar, tr("Opslaan"), bewaar, bg=BTN_GREEN).pack(side="right")
        win.invul = (velden, bewaar)     # voor de proef
        velden[0].focus_set()
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        return uit.get("bereik")

    def _zet_model(self, model):
        zet_bereik(model.vmax, model.imax)
        self.settings.update(model=model.naam, bereik=[model.vmax, model.imax])
        save_settings(self.settings)
        self._teken_pill()
        self._toon_model()

    def _toon_model(self):
        naam = "DEMO" if korad_paden.DEMO else self.settings["model"]
        self.title(f"{NAAM} - {naam}" if naam else NAAM)
        self.model_lbl.config(text=naam, fg=LED_AMBER if korad_paden.DEMO else MUTED)

    def _disconnect(self, msg, verloren=False):
        busy = bool(self.run or self.sim)
        if self.dev and verloren and (self.out or busy):
            self._notify(tr("Voeding niet meer bereikbaar"),
                         tr("{0}. De uitgang stond {1}; het paneel kan hem niet meer bedienen. De stroomgrens "
                            "van de voeding zelf blijft werken.", msg, tr('aan') if self.out else tr('uit')), priority=5, tags=("warning",))
            self._say(tr("Voeding niet meer bereikbaar."))
        self._stop_program(tr("Gestopt: verbinding weg"))
        self._stop_sim(tr("Gestopt: verbinding weg"))
        self._stop_new(tr("Gestopt: verbinding weg"))
        self._night_stop(tr("gestopt: verbinding met de voeding weg"))
        self.e_last = None
        self.running = False
        if self.dev:
            time.sleep(0.15)
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None
        self.conn_lamp.set(False)
        self.status_lbl.config(text=msg)
        self.conn_btn.config(text=tr("Verbinden"), bg=BLUE)
        for l in (self.lamp_cv, self.lamp_cc, self.lamp_out):
            l.set(False)
        self.conn_lamp.set(False)
        self._out_prev = None
        self.afdruk_controle = None
        self._mini_update()
        self._update_status()
        self._bench_update()
        self._draw_chart()

    def _worker(self, dev):
        n = 0
        while self.running:
            try:
                while not self.cmdq.empty():
                    dev.write(self.cmdq.get_nowait())
                    n = 0
                if n % 8 == 0:   # ingestelde waarden af en toe opnieuw lezen (draaiknop)
                    self.inq.put(("set", time.time(), dev.number("VSET1?"), dev.number("ISET1?")))
                v, i, st = dev.number("VOUT1?"), dev.number("IOUT1?"), dev.status()
                if v is not None and i is not None:
                    self.inq.put(("meas", time.time(), v, i, st))
                n += 1
            except (serial.SerialException, OSError) as e:
                self.inq.put(("error", str(e)))
                return
            time.sleep(0.05)

    # ---------- verwerking (hoofdthread)
    def _pump(self):
        # De pomp moet zichzelf ALTIJD opnieuw inplannen. Een fout in een van de handlers (22-10-2026: KeyError
        # 'popdown' in _on_set) liet hem anders voorgoed stilstaan: de voeding reageerde nog, het scherm niet meer.
        try:
            changed = False
            while not self.inq.empty():
                msg = self.inq.get_nowait()
                if msg[0] == "set":
                    self._on_set(*msg[1:])
                elif msg[0] == "meas":
                    self._on_meas(*msg[1:])
                    changed = True
                elif msg[0] == "error":
                    self._disconnect(tr("Verbinding verloren: {0}", msg[1]), verloren=True)
                elif msg[0] == "call":          # functie uit een andere thread, hier uitvoeren
                    msg[1]()
            if changed:
                self._draw_chart()
        except Exception as e:  # noqa: BLE001 - loggen zoals elke andere fout, maar de pomp blijft lopen
            self.report_callback_exception(type(e), e, e.__traceback__)
        finally:
            self.after(50, self._pump)

    def _on_set(self, t, vs, is_):
        if vs is None or is_ is None:
            return
        if self.pending and t > self.pending[1]:
            # na een geheugenknop: onthoud wat er echt in die plaats zit
            n = self.pending[0]
            self.pending = None
            self.presets[str(n)] = [vs, is_]
            self._label_preset(n)
            try:
                PRESET_FILE.write_text(json.dumps(self.presets, indent=2), encoding="utf-8")
            except OSError:
                pass
        self.vset, self.iset = vs, is_
        self._enforce_limits(vs, is_)
        gi, gw = self.gauges["i"], self.gauges["w"]
        imax = nice_ceil(max(is_, 0.001) * 1.15)
        gi.set_scale(imax, mark=is_, redzone=(is_ * 0.95, imax))
        gw.set_scale(nice_ceil(max(vs * is_, 0.01) * 1.1))
        self._schaal_spanning(vs)
        self.setlbls["v"].config(text=tr("ingesteld {0} V", nlf(vs, 2)))
        self.setlbls["i"].config(text=tr("grens {0} A", nlf(is_, 3)))
        self.setlbls["w"].config(text=tr("maximaal {0} W", nlf(vs * is_, 1)))
        # focus_get() kan omvallen (KeyError 'popdown') zolang de keuzelijst Grens open staat; dat gebeurde
        # op 22-10-2026 en legde via _pump de hele verwerking stil. Geen focus bekend = velden gewoon bijwerken.
        try:
            focus = self.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        for e, val in ((self.v_entry, nlf(vs, 2)), (self.i_entry, nlf(is_, 3))):
            if focus is not e:
                e.delete(0, "end")
                e.insert(0, val)

    def _on_meas(self, t, v, i, st):
        w = v * i
        self.hist.append((t, v, i))
        self.gauges["v"].target, self.gauges["i"].target, self.gauges["w"].target = v, i, w
        self.gauges["v"].show(nlf(v, 2))
        self.gauges["i"].show(nlf(i, 3))
        self.gauges["w"].show(nlf(w, 2))
        if st:
            self.out = st["out"]
            self.lamp_out.set(st["out"])
            self.lamp_cv.set(st["out"] and st["cv"])
            self.lamp_cc.set(st["out"] and not st["cv"], LED_AMBER)
            self.out_btn.config(text=tr("Uitgang uitzetten") if st["out"] else tr("Uitgang aanzetten"),
                                bg=BTN_GREEN if st["out"] else PANEL_DARK)
        self._check_guards(t, v, i, w, st)
        self.cc = bool(st and st["out"] and not st["cv"])
        if self.curve is not None:
            self.curve["ccs"].append((t, self.cc))
        if self.part is not None:
            self.part["ccs"].append((t, self.cc))
        if self.cc:
            if self._cc_since is None:
                self._cc_since = t
            elif not self._cc_beeped and t - self._cc_since >= 0.6 and self.part is None:
                self._cc_beeped = True
                self._beep("cc")
                self._say(tr("Stroom begrensd"))
        else:
            self._cc_since, self._cc_beeped = None, False
        self._mini_update(v, i)
        self._na_meting(t, v, i, st)
        if st and st["out"] and v > self._limits()[0] + 0.3:
            self._limit_trip(tr("Gemeten spanning {0} V, boven de grens van {1} V", nlf(v, 2), nl(self._limits()[0])))
        if self.sim and self.sim["r"] > 0:   # accu met inwendige weerstand: spanning zakt mee met de stroom
            self.sim["i_f"] = i if self.sim["i_f"] is None else 0.6 * self.sim["i_f"] + 0.4 * i
            self._sim_apply()
        # energieteller: stroom x tijd optellen (gaten > 2 s tellen niet mee)
        if self.e_last is not None:
            dt = t - self.e_last
            if 0 < dt < 2:
                self.charge_as += i * dt
                self.energy_j += w * dt
        self.e_last = t
        self._show_energy()
        if self.log_writer:
            mode = "" if not st else ("CV" if st["cv"] else "CC")
            outs = "" if not st else ("aan" if st["out"] else "uit")
            self.log_writer.writerow([datetime.fromtimestamp(t).isoformat(timespec="milliseconds"),
                                      f"{v:.2f}", f"{i:.3f}", f"{w:.3f}", mode, outs,
                                      f"{self.charge_as / 3.6:.2f}", f"{self.energy_j / 3600:.4f}",
                                      self.pending_marker])
            self.pending_marker = ""
            self.log_rows += 1
            if self.log_rows % 20 == 0:
                self.log_file.flush()
            self.log_lbl.config(text=tr("{0} metingen gelogd", self.log_rows))

    def _animate(self):
        for g in self.gauges.values():
            g.step()
        for g in list(self.xgauges):
            try:
                if g.winfo_exists():
                    g.step()
                    continue
            except tk.TclError:
                pass
            self.xgauges.remove(g)
        self._puls_n = (self._puls_n + 1) % 15
        if self._puls_n == 0:
            self.statusbar.tik()
        self.after(33, self._animate)

    # ---------- kolom met icoontjes, project, statusbalk (november 2026)
    def _bouw_kolom(self):
        kolom = tk.Frame(self, bg=CARD, width=px(86))
        self.kolomknoppen = {}
        kolom.pack(side="left", fill="y")
        kolom.pack_propagate(False)
        tk.Frame(kolom, bg=CARD, height=px(10)).pack()
        for icoon, tekst, cmd in (("werkbank", tr("Werkbank"), self._toggle_bench), ("mini", tr("Mini"), self._toggle_mini),
                                  ("projecten", tr("Projecten"), self._open_projecten),
                                  ("afdruk", tr("Afdruk"), self._open_afdruk),
                                  ("gereedschap", tr("Gereedschap"), self._open_tools),
                                  ("werkboek", tr("Werkboek"), self._open_workbook)):
            self._kolomknop(kolom, icoon, tekst, cmd).pack(fill="x", padx=3, pady=2)
        self._kolomknop(kolom, "instellingen", tr("Instellingen"), self._open_settings).pack(
            side="bottom", fill="x", padx=3, pady=(2, 12))

    def _kolomknop(self, ouder, icoon, tekst, cmd):
        f = tk.Frame(ouder, bg=CARD, cursor="hand2")
        self.kolomknoppen[icoon] = f
        ic = tk.Label(f, text=ICONEN[icoon], bg=CARD, fg=TEXT, font=(FONT_ICON, 17), cursor="hand2")
        ic.pack(pady=(9, 2))
        tx = tk.Label(f, text=tekst, bg=CARD, fg=MUTED, font=(FONT, 8), cursor="hand2")
        tx.pack(pady=(0, 8))
        delen = (f, ic, tx)

        def kleur(aan):
            for d in delen:
                d.config(bg=CARD_3 if aan else CARD)
            tx.config(fg=TEXT if aan else MUTED)

        for d in delen:
            d.bind("<Enter>", lambda e: kleur(True))
            d.bind("<Leave>", lambda e: kleur(False))
            d.bind("<Button-1>", lambda e: cmd())
        return f

    def _kop(self, ouder, titel, bg=PANEL):
        """Dezelfde kop boven elk venster: streepje in de kleur van het project, daarnaast de titel."""
        f = tk.Frame(ouder, bg=bg)
        tk.Frame(f, bg=PROJECTS[self.settings["project"]]["kleur"], width=px(4), height=px(24)).pack(
            side="left", padx=(0, 10))
        tk.Label(f, text=titel, bg=bg, fg=INK, font=(FONT_NUM, 16)).pack(side="left")
        return f

    def _teken_pill(self):
        p = PROJECTS[self.settings["project"]]
        vmax, imax = self._limits()
        tekst = f"{p['kort']}   {nl(vmax)} V  ·  {nl(imax)} A"
        font = tkfont.Font(family=FONT_NUM, size=10)
        w, h = font.measure(tekst) + px(58), px(30)
        ss = 3
        im = Image.new("RGB", (w * ss, h * ss), BG)
        ImageDraw.Draw(im).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=h * ss // 2,
                                             fill=blend(BG, p["kleur"], 0.2), outline=p["kleur"], width=ss)
        self._pill_foto = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
        c = self.proj_pill
        c.config(width=w, height=h)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._pill_foto)
        c.create_oval(px(13), h / 2 - px(4), px(21), h / 2 + px(4), fill=p["kleur"], outline="")
        c.create_text(px(29), h / 2, text=tekst, anchor="w", fill=TEXT, font=font)
        c.create_text(w - px(15), h / 2, text=ICONEN["omlaag"], fill=MUTED, font=(FONT_ICON, 8))

    def _project_menu(self, e=None):
        m = tk.Menu(self, tearoff=0, bg=CARD_2, fg=TEXT, activebackground=BLUE, activeforeground="#FFFFFF", bd=0,
                    font=(FONT, 10))
        for key, p in PROJECTS.items():
            m.add_command(label=("✓  " if key == self.settings["project"] else "     ") + p["naam"],
                          command=lambda k=key: self._kies_project(k))
        m.add_separator()
        m.add_command(label=tr("     Projecten beheren"), command=self._open_projecten)
        m.tk_popup(self.proj_pill.winfo_rootx(), self.proj_pill.winfo_rooty() + self.proj_pill.winfo_height() + px(2))

    def _project_gegevens(self):
        """Wat bij het gekozen project hoort: geheugenknoppen en bewakingsregels. Zonder eigen waarden blijft alles
        zoals het in de gewone bestanden staat."""
        p = PROJECTS[self.settings["project"]]
        eigen = p.get("geheugens") or {}
        self.presets = {**load_presets(), **eigen}
        self.preset_eigen = set(eigen)
        self.guards = json.loads(json.dumps(p["bewaking"])) if p.get("bewaking") else load_guards()
        self.guard_state = [{"since": None, "fired": False} for _ in self.guards]

    def _schaal_spanning(self, vs):
        """Ring van de spanning: loopt door tot boven de projectgrens, met de grens als rode zone."""
        vmax = self._limits()[0]
        if vmax >= MAX_V:
            self.gauges["v"].set_scale(nice_ceil(max(vs, 0.1) * 1.15), mark=vs)
        else:
            schaal = nice_ceil(vmax * 1.15)
            self.gauges["v"].set_scale(schaal, mark=vs, redzone=(vmax, schaal))

    def _toestand(self):
        """(kleur, tekst, knipperen): de toestand voor de statusbalk en de werkbankstand."""
        if self.alarm:
            return LED_RED, tr("ALARM  ·  ") + self.alarm.split("  ", 1)[-1], True
        if not self.dev:
            return DIM, tr("NIET VERBONDEN"), False
        if self.cc:
            return LED_AMBER, tr("STROOM BEGRENST"), False
        if self.out:
            return LED_GREEN, tr("UITGANG AAN  ·  VASTE SPANNING"), False
        return MUTED, tr("UITGANG UIT"), False

    def _update_status(self):
        self.statusbar.zet(*self._toestand())
        self._bench_update()

    def _bezig(self):
        """Naam van de proef die nu zelf de voeding bedient, of None."""
        for attr, naam in (("run", "testprogramma"), ("sim", tr("accu nabootsen")), ("curve", "opstartcurve"),
                           ("part", "onderdelentester")):
            if getattr(self, attr, None):
                return naam
        return None

    def _na_meting(self, t, v, i, st):
        self._update_status()
        self._bench_update(v, i)
        if st:
            uit, vorig = st["out"], self._out_prev
            self._out_prev = uit
            if vorig is False and uit:
                self._afdruk_start(t)
            elif vorig and not uit:
                self._afdruk_uit(t)
            self._afdruk_volg(t, i)
            d = self.dips.voeg(t, i, uit, self._bezig() is not None)
            if d:
                self._dip_gevonden(d)
        if t - self._spark_t >= 0.5:
            self._spark_t = t
            self._sparks_bij(t)

    def _sparks_bij(self, nu):
        k = len(self.hist)
        rij = []
        while k > 0 and self.hist[k - 1][0] >= nu - 60:      # deque: alleen het einde bekijken
            k -= 1
            rij.append(self.hist[k])
            if len(rij) > 400:
                break
        rij.reverse()
        stap = max(1, len(rij) // 90)
        rij = rij[::stap]
        self.sparks["v"].teken([p[1] for p in rij])
        self.sparks["i"].teken([p[2] for p in rij])
        self.sparks["w"].teken([p[1] * p[2] for p in rij])

    # ---------- herstartteller
    def _dip_gevonden(self, d):
        n, gem, _reg = self.dips.patroon()
        if d[0] - self._dip_mark_t >= 5:         # bij een onrustige belasting de grafiek niet volzetten
            self._dip_mark_t = d[0]
            self.markers.append((d[0], tr("stroomdip {0}: {1} s, van {2} mA", n, nlf(d[1], 1), nlf(d[2] * 1000, 0))))
        self._toon_dips()

    def _toon_dips(self):
        n, gem, reg = self.dips.patroon()
        if not n:
            self.x_vals["dips"].config(text="--", fg=ACCENT)
            return
        tekst = f"{n}x" + (tr(", elke {0} s", nlf(gem, 0)) if reg else (tr(", gem. {0} s", nlf(gem, 0)) if gem else ""))
        self.x_vals["dips"].config(text=tekst, fg=LED_AMBER if reg else ACCENT)

    # ---------- stroomafdruk
    def _afdruk_actief(self):
        naam = self.settings.get("afdruk_actief")
        if not naam:
            return None
        return next((a for a in self.afdrukken
                     if a["naam"] == naam and a.get("project") == self.settings["project"]), None)

    def _toon_afdruk(self, tekst, fg=ACCENT):
        self.x_vals["afdruk"].config(text=tekst, fg=fg)

    def _afdruk_start(self, t):
        self._out_on_t, self._out_off_t = t, None
        self.afdruk_controle = self._afdruk_laatste = None
        a = self._afdruk_actief()
        if a and self._bezig() is None:
            laag, hoog = ana.maak_band(a["starts"])
            if laag:
                self.afdruk_controle = ana.BandControle(laag, hoog, t)
                self._toon_afdruk(tr("loopt..."))

    def _afdruk_uit(self, t):
        self._out_off_t = t
        c = self.afdruk_controle
        if c and t - c.t_aan >= ana.AFDRUK_MIN_DUUR:
            self._afdruk_klaar()
        else:
            self.afdruk_controle = None

    def _afdruk_volg(self, t, i):
        c = self.afdruk_controle
        if not c:
            return
        if not c.voeg(t, i):
            self._afdruk_klaar()
            return
        if not c.laatste_ok:
            self._toon_afdruk(tr("buiten de band"), LED_AMBER)
        elif (c.binnen + c.buiten) % 5 == 0:
            self._toon_afdruk(tr("{0} % binnen", nlf(c.procent(), 0)))

    def _afdruk_klaar(self):
        c, self.afdruk_controle = self.afdruk_controle, None
        a = self._afdruk_actief()
        naam = a["naam"] if a else "afdruk"
        pct = c.procent()
        goed = pct >= 95
        self._afdruk_laatste = (c, goed)
        tekst = (tr("afdruk {0}: {1} % binnen de band", naam, nlf(pct, 0)) if goed
                 else tr("afdruk {0}: {1} % buiten de band", naam, nlf(100 - pct, 0)))
        self._toon_afdruk(tr("{0} % binnen", nlf(pct, 0)), GOOD if goed else BAD)
        self._add_marker(tekst)
        self._wb_add("controle", tekst, about=tr("Project {0}.", PROJECTS[self.settings['project']]['kort']))
        self._say(tr("Stroomafdruk klopt.") if goed else tr("Stroomafdruk wijkt af."))

    def _afdruk_band_nu(self, t0, t1):
        """(t_aan, laag, hoog, ok, stap) als er een band te tekenen valt in dit stuk van de grafiek."""
        c, ok = self.afdruk_controle, True
        if c:
            ok = c.laatste_ok
        elif self._afdruk_laatste:
            c, ok = self._afdruk_laatste
        if not c or c.t_aan + c.duur < t0 or c.t_aan > t1:
            return None
        return c.t_aan, c.laag, c.hoog, ok, c.stap

    def _afdruk_laatste_start(self):
        """Stroomverloop van de laatste keer dat de uitgang aanging, op het vaste raster. Leeg als die te kort was."""
        t_aan = self._out_on_t
        if t_aan is None:
            return []
        eind = min(self._out_off_t or time.time(), t_aan + ana.AFDRUK_MAX_DUUR)
        if eind - t_aan < ana.AFDRUK_MIN_DUUR:
            return []
        return ana.bemonster([p for p in self.hist if t_aan <= p[0] <= eind], t_aan)

    def _open_afdruk(self):
        win = self._toplevel("_afwin", tr("Stroomafdruk"))
        if not win:
            return
        p = PROJECTS[self.settings["project"]]
        self._kop(win, tr("Stroomafdruk")).pack(anchor="w", padx=22, pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(860),
                 text=tr("Bewaar hoe een werkend bordje opstart. Bij elke volgende keer dat de uitgang aangaat "
                         "tekent het paneel die afdruk als band in de grafiek en meldt het of de stroom erbinnen "
                         "blijft. Meer starts toevoegen maakt de band realistischer. Het paneel waarschuwt "
                         "alleen; de uitgang blijft zoals hij staat. Project: {0}.", p['kort'])).pack(anchor="w", padx=22, pady=(0, 10))
        kaart = self._card(win)
        kaart.pack(fill="both", padx=22)
        links = tk.Frame(kaart, bg=CARD)
        links.pack(side="left", fill="y", padx=14, pady=12)
        boom = ttk.Treeview(links, columns=("naam", "starts", "duur", "aan"), show="headings", height=7, selectmode="browse")
        for k, kop_, br in (("naam", tr("Afdruk"), 190), ("starts", tr("Starts"), 60), ("duur", tr("Duur"), 60), ("aan", tr("In gebruik"), 90)):
            boom.heading(k, text=kop_)
            boom.column(k, width=px(br), anchor="w" if k == "naam" else "center")
        boom.pack()
        rechts = tk.Frame(kaart, bg=CARD)
        rechts.pack(side="left", fill="both", expand=True, padx=(0, 14), pady=12)
        vlak = tk.Canvas(rechts, width=px(430), height=px(210), bg=GLASS, highlightthickness=0)
        vlak.pack()
        info = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=(FONT, 10), anchor="w", justify="left", wraplength=px(860))
        info.pack(fill="x", padx=22, pady=(10, 0))
        rij = tk.Frame(win, bg=PANEL)
        rij.pack(fill="x", padx=22, pady=(10, 0))
        tk.Label(rij, text=tr("Naam"), bg=PANEL, fg=INK, font=(FONT, 11)).pack(side="left")
        naam_e = self._entry(rij, 24, size=11, justify="left")
        naam_e.pack(side="left", padx=(8, 8), ipady=2)

        def eigen():
            return [a for a in self.afdrukken if a.get("project") == self.settings["project"]]

        def gekozen():
            sel = boom.selection()
            return next((a for a in eigen() if a["naam"] == sel[0]), None) if sel else None

        def teken(_e=None):
            vlak.delete("all")
            a = gekozen()
            start = self._afdruk_laatste_start()
            laag, hoog = ana.maak_band(a["starts"]) if a else ([], [])
            if not laag and not start:
                vlak.create_text(px(215), px(105), fill=MUTED, font=(FONT, 10),
                                 text=tr("Zet de uitgang aan en wacht tot het bordje is opgestart."))
                return
            w, h, m = px(430), px(210), px(8)
            top = max(hoog + start + [0.001]) * 1.1
            n = max(len(laag), len(start), 2)
            X, Y = (lambda k: m + (w - 2 * m) * k / (n - 1)), (lambda x: h - m - (h - 2 * m) * min(x / top, 1))
            if laag:
                vlak.create_polygon(*[c for k, x in enumerate(hoog) for c in (X(k), Y(x))],
                                    *[c for k, x in reversed(list(enumerate(laag))) for c in (X(k), Y(x))],
                                    fill=blend(GLASS, LED_AMBER, 0.28), outline="")
            if len(start) >= 2:
                vlak.create_line(*[c for k, x in enumerate(start) for c in (X(k), Y(x))], fill=LED_AMBER, width=px(2))
            vlak.create_text(w - m, m, anchor="ne", fill=MUTED, font=(FONT, 9),
                             text=f"{nlf(top * 1000, 0)} mA, {nlf((n - 1) * ana.AFDRUK_STAP, 0)} s")
            vlak.create_text(m, m, anchor="nw", fill=MUTED, font=(FONT, 9), text=tr("band: afdruk   lijn: laatste start"))

        def ververs(kies=None):
            boom.delete(*boom.get_children())
            for a in eigen():
                n = max((len(x) for x in a["starts"]), default=0)
                boom.insert("", "end", iid=a["naam"], values=(a["naam"], len(a["starts"]), f"{nlf(n * ana.AFDRUK_STAP, 0)} s",
                                                              "ja" if a["naam"] == self.settings.get("afdruk_actief") else ""))
            if kies and boom.exists(kies):
                boom.selection_set(kies)
            start = self._afdruk_laatste_start()
            info.config(text=(tr("Laatste start: {0} s beschikbaar.", nlf(len(start) * ana.AFDRUK_STAP, 0)) if start else
                              tr("Nog geen bruikbare start: zet de uitgang aan en wacht minstens 3 seconden.")))
            teken()

        def bewaar():
            save_afdrukken(self.afdrukken)

        def nieuw():
            naam = naam_e.get().strip()
            start = self._afdruk_laatste_start()
            if not naam or not start:
                info.config(text=tr("Vul een naam in en zorg voor een start van minstens 3 seconden."), fg=BAD)
                return
            if any(a["naam"] == naam for a in eigen()):
                info.config(text=tr("Die naam bestaat al in dit project."), fg=BAD)
                return
            self.afdrukken.append({"naam": naam, "project": self.settings["project"], "starts": [start],
                                   "gemaakt": time.time()})
            bewaar()
            info.config(fg=MUTED)
            ververs(naam)

        def erbij():
            a, start = gekozen(), self._afdruk_laatste_start()
            if not a or not start:
                info.config(text=tr("Kies een afdruk en zorg voor een nieuwe start van minstens 3 seconden."), fg=BAD)
                return
            a["starts"] = (a["starts"] + [start])[-ana.AFDRUK_MAX_STARTS:]
            bewaar()
            info.config(fg=MUTED)
            ververs(a["naam"])

        def gebruik():
            a = gekozen()
            nu = self.settings.get("afdruk_actief")
            self.settings["afdruk_actief"] = "" if not a or a["naam"] == nu else a["naam"]
            save_settings(self.settings)
            ververs(a["naam"] if a else None)

        def weg():
            a = gekozen()
            if a and messagebox.askyesno(tr("Afdruk verwijderen"), tr("\"{0}\" verwijderen?", a['naam']), parent=win):
                self.afdrukken.remove(a)
                if self.settings.get("afdruk_actief") == a["naam"]:
                    self.settings["afdruk_actief"] = ""
                    save_settings(self.settings)
                bewaar()
                ververs()

        boom.bind("<<TreeviewSelect>>", teken)
        self._btn(rij, tr("Laatste start bewaren als nieuwe afdruk"), nieuw, bg=BLUE).pack(side="left", padx=(0, 6))
        self._btn(rij, tr("Laatste start toevoegen aan gekozen afdruk"), erbij).pack(side="left")
        balk = tk.Frame(win, bg=PANEL)
        balk.pack(fill="x", padx=22, pady=14)
        self._btn(balk, tr("Gebruiken of uitzetten"), gebruik, bg=BTN_GREEN).pack(side="left")
        self._btn(balk, tr("Verwijderen"), weg).pack(side="left", padx=6)
        self._btn(balk, tr("Sluiten"), win.destroy).pack(side="right")
        actief = self.settings.get("afdruk_actief")
        ververs(actief if actief else None)

    # ---------- vlaggetjes in de grafiek
    @staticmethod
    def _rond(c, x0, y0, x1, y1, r, **kw):
        return c.create_polygon(x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
                                x0, y1, x0, y1 - r, x0, y0 + r, x0, y0, smooth=True, **kw)

    def _teken_vlaggen(self, c, marks, X, T, ph, L, pw):
        self._flags = []
        y0, y1 = T - px(23), T - px(5)
        for v in ana.vlaggen(marks, X, px(6.5), px(11), px(3)):
            kl = SOORT_KLEUR.get(v["soort"], MUTED)
            v["xs"] = [X(i[1]) for i in v["items"]]
            for x in v["xs"]:
                c.create_line(x, y1, x, T + px(5), fill=kl)
            self._rond(c, v["x0"], y0, v["x1"], y1, px(4), fill=blend(GLASS, kl, 0.24), outline=kl)
            c.create_text((v["x0"] + v["x1"]) / 2, (y0 + y1) / 2, text=v["label"], fill=lighten(kl, 0.25),
                          font=(FONT, 8, "bold"))
            self._flags.append((v["x0"], y0, v["x1"], y1, v, T, ph))

    def _vlag_tip(self):
        """Onder de muis een vlaggetje: de tekst erbij tonen en de lijn over de hele hoogte. True als dat zo is."""
        mx, my = self._mouse_x, self._mouse_y
        if mx is None or my is None or self._drag_x0 is not None:
            return False
        m = px(2)
        treffer = next((f for f in self._flags if f[0] - m <= mx <= f[2] + m and f[1] - m <= my <= f[3] + m), None)
        if not treffer:
            return False
        c = self.chart
        x0, y0, x1, y1, v, T, ph = treffer
        if self._tipfont is None:
            self._tipfont = tkfont.Font(family=FONT, size=10)
        kl = SOORT_KLEUR.get(v["soort"], MUTED)
        for x in v["xs"]:
            c.create_line(x, y1, x, T + ph, fill=kl, dash=(px(3), px(3)), tags="overlay")
        regels = [(f"{nr}   {datetime.fromtimestamp(t):%H:%M:%S}   {tx}", SOORT_KLEUR.get(ana.soort_markering(tx), MUTED))
                  for nr, t, tx in v["items"][:14]]
        if len(v["items"]) > 14:
            regels.append((tr("en nog {0}", len(v['items']) - 14), MUTED))
        bw = max(self._tipfont.measure(r[0]) for r in regels) + px(22)
        bh = px(19) * len(regels) + px(12)
        w = c.winfo_width()
        bx = max(px(4), min(x0, w - bw - px(4)))
        by = y1 + px(5)
        c.create_rectangle(bx, by, bx + bw, by + bh, fill=CARD_2, outline=LINE, tags="overlay")
        for n, (tx, rk) in enumerate(regels):
            c.create_text(bx + px(11), by + px(15) + px(19) * n, text=tx, anchor="w", font=self._tipfont,
                          fill=TEXT if rk in (MUTED, TEXT) else lighten(rk, 0.2), tags="overlay")
        return True

    # ---------- werkbankstand
    def _toggle_bench(self):
        if self.bench:
            self._bench_sluit()
            return
        win = tk.Toplevel(self)
        win.title(tr("CurrentBench werkbank"))
        win.configure(bg=BG)
        win.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty()}")
        H = self.winfo_screenheight()
        strook = tk.Frame(win, bg=MUTED, height=int(H * 0.018))
        strook.pack(fill="x", side="top")
        stand = tk.Label(win, text="", bg=BG, fg=TEXT, font=(FONT_NUM, -int(H * 0.05)))
        stand.pack(pady=(int(H * 0.018), 0))
        def regel(kleur, eenheid):
            rij = tk.Frame(win, bg=BG)
            rij.pack(expand=True)
            g = tk.Label(rij, text="--", bg=BG, fg=kleur, font=(FONT_NUM, -int(H * 0.27)))
            g.pack(side="left")
            tk.Label(rij, text=eenheid, bg=BG, fg=MUTED, font=(FONT, -int(H * 0.08))).pack(side="left", anchor="s",
                                                                                          pady=(0, int(H * 0.05)))
            return g
        v, i = regel(LED_RED, "V"), regel(LED_AMBER, "A")
        onder = tk.Frame(win, bg=BG)
        onder.pack(fill="x", side="bottom", padx=int(H * 0.03), pady=int(H * 0.025))
        ingesteld = tk.Label(onder, text="", bg=BG, fg=MUTED, font=(FONT, -int(H * 0.03)))
        ingesteld.pack(side="left")
        sluit = self._btn(onder, tr("Sluiten (F11)"), self._bench_sluit)
        sluit.config(font=(FONT, -int(H * 0.024)), padx=int(H * 0.02), pady=int(H * 0.012))
        sluit.pack(side="right", padx=(int(H * 0.012), 0))
        knop = self._btn(onder, tr("Uitgang uit"), lambda: self._toggle_out() if self.out else None, bg=BTN_RED)
        knop.config(font=(FONT_NUM, -int(H * 0.03)), padx=int(H * 0.04), pady=int(H * 0.012))
        knop.pack(side="right")
        win.protocol("WM_DELETE_WINDOW", self._bench_sluit)
        self.bench = {"win": win, "strook": strook, "stand": stand, "v": v, "i": i, "ingesteld": ingesteld, "knop": knop}
        try:
            win.attributes("-fullscreen", True)
        except tk.TclError:
            pass
        win.focus_force()
        self._bench_update()

    def _bench_sluit(self):
        b, self.bench = self.bench, None
        if b:
            try:
                b["win"].destroy()
            except tk.TclError:
                pass

    def _bench_update(self, v=None, i=None):
        b = self.bench
        if not b:
            return
        try:
            kleur, tekst, _p = self._toestand()
            b["strook"].config(bg=kleur)
            b["stand"].config(text=tekst[:60], fg=lighten(kleur, 0.2))
            if not self.dev:
                b["v"].config(text="--")
                b["i"].config(text="--")
            elif v is not None:
                b["v"].config(text=nlf(v, 2))
                b["i"].config(text=nlf(i, 3))
            b["ingesteld"].config(text="" if self.vset is None else
                                  tr("ingesteld {0} V, grens {1} A", nlf(self.vset, 2), nlf(self.iset or 0, 3)))
            b["knop"].config(bg=BTN_RED if self.out else CARD_2)
        except tk.TclError:
            self.bench = None

    # ---------- lokale koppeling voor scripts
    def _api_start(self):
        if self._api:
            return
        try:
            srv = ThreadingHTTPServer((korad_koppeling.HOST, int(self.settings["api_poort"])),
                                      korad_koppeling.maak_handler(self))
        except OSError as e:
            self._api_fout = str(e)
            return
        srv.daemon_threads = True
        self._api, self._api_fout = srv, ""
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def _api_stop(self):
        srv, self._api = self._api, None
        if srv:
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()

    def _api_uitvoeren(self, functie, wacht=3.0):
        """Uit de thread van de webserver: de functie in de hoofdthread laten lopen en op het antwoord wachten."""
        klaar, verlopen, uit = threading.Event(), threading.Event(), {}

        def doe():
            if verlopen.is_set():      # te laat: een opdracht die de aanvrager al heeft opgegeven niet meer uitvoeren
                return
            try:
                uit["r"] = functie()
            except Exception as e:  # noqa: BLE001 - de fout hoort bij de aanvrager, niet bij de pomp van het paneel
                uit["r"] = (500, {"fout": f"{type(e).__name__}: {e}"})
            finally:
                klaar.set()

        self.inq.put(("call", doe))
        if not klaar.wait(wacht):
            verlopen.set()
            return 503, {"fout": tr("het paneel antwoordt niet op tijd (staat er een dialoogvenster open?)")}
        return uit["r"]

    def _api_project(self):
        k = self.settings["project"]
        p = PROJECTS[k]
        return {"sleutel": k, "naam": p["naam"], "kort": p["kort"], "vmax": min(p["vmax"], MAX_V), "imax": min(p["imax"], MAX_A)}

    def _api_stand(self):
        if not self.dev:
            return 200, {"verbonden": False, "project": self._api_project(), "alarm": self.alarm}
        t, v, i = self.hist[-1] if self.hist else (None, None, None)
        return 200, {"verbonden": True, "idn": self.idn, "t": t, "v": v, "i": i, "w": (v or 0) * (i or 0),
                     "vset": self.vset, "iset": self.iset, "uit": bool(self.out),
                     "modus": "uit" if not self.out else ("CC" if self.cc else "CV"),
                     "alarm": self.alarm, "bezig": self._bezig() or ("nachttest" if self.night else None),
                     "logt": bool(self.log_file), "project": self._api_project()}

    def _api_metingen(self, sec):
        sec = max(0.0, min(float(sec), 7200.0))
        grens, rij, k = time.time() - sec, [], len(self.hist)
        while k > 0 and self.hist[k - 1][0] >= grens and len(rij) < 40000:
            k -= 1
            rij.append(self.hist[k])
        rij.reverse()
        return 200, {"metingen": [[round(p[0], 3), p[1], p[2]] for p in rij]}

    def _api_weiger_bezig(self):
        if not self.dev:
            return 409, {"fout": tr("de voeding is niet verbonden")}
        b = self._bezig() or ("nachttest" if self.night else None)
        return (409, {"fout": tr("er loopt een proef ({0})", b)}) if b else None

    def _api_zet(self, d):
        w = self._api_weiger_bezig()
        if w:
            return w
        try:
            v, i = float(d["v"]), float(d["i"])
        except (KeyError, TypeError, ValueError):
            return 400, {"fout": tr("geef v en i als getal")}
        vmax, imax = self._limits()
        if not (0 <= v <= vmax and 0 <= i <= imax):
            return 422, {"fout": self._limit_text()}
        if self.out and self.vset is not None and v > self.vset + 0.05 and d.get("akkoord") is not True:
            return 409, {"fout": tr("de uitgang staat aan en de spanning zou stijgen van {0} naar {1} V; dat kan "
                                    "alleen met akkoord", nl(self.vset), nl(v))}
        self.cmdq.put(f"ISET1:{i:.3f}")
        self.cmdq.put(f"VSET1:{v:.2f}")
        self._add_marker(tr("koppeling: {0} V, grens {1} A", nl(v), nl(i)))
        return 200, {"ok": 1}

    def _api_aan(self, d):
        w = self._api_weiger_bezig()
        if w:
            return w
        if d.get("akkoord") is not True:
            return 409, {"fout": tr("de uitgang aanzetten kan alleen met akkoord")}
        vmax, imax = self._limits()
        if self.vset is None or self.iset is None:
            return 409, {"fout": tr("de ingestelde waarden zijn nog niet gelezen")}
        if self.vset > vmax + 0.005 or self.iset > imax + 0.0005:
            return 422, {"fout": self._limit_text()}
        self.cmdq.put("OUT1")
        self._add_marker(tr("koppeling: uitgang aan"))
        return 200, {"ok": 1}

    def _api_uit(self):
        if not self.dev:
            return 409, {"fout": tr("de voeding is niet verbonden")}
        msg = tr("Gestopt: uitgang via koppeling")
        self._stop_program(msg)
        self._stop_sim(msg)
        self._stop_new(msg)
        self.cmdq.put("OUT0")
        self._add_marker(tr("koppeling: uitgang uit"))
        return 200, {"ok": 1}

    def _api_markering(self, d):
        tekst = " ".join(str(d.get("tekst") or "").split())[:120]
        if not tekst:
            return 400, {"fout": tr("geen tekst")}
        self._add_marker(tr("koppeling: {0}", tekst))
        return 200, {"ok": 1}

    # ---------- projecten beheren
    def _open_projecten(self):
        win = self._toplevel("_pjwin", tr("Projecten"))
        if not win:
            return
        self._kop(win, tr("Projecten")).pack(anchor="w", padx=22, pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(820),
                 text=tr("Per project: de grens die het paneel bewaakt, en desgewenst eigen geheugenknoppen en "
                         "bewakingsregels. Alles staat in korad_projecten.json. Een beschadigd bestand verhoogt "
                         "nooit een grens: wat niet klopt wordt genegeerd.")).pack(anchor="w", padx=22, pady=(0, 10))
        kaart = self._card(win)
        kaart.pack(fill="x", padx=22)
        boom = ttk.Treeview(kaart, columns=("kort", "grens"), show="headings", height=8, selectmode="browse")
        boom.heading("kort", text=tr("Project"))
        boom.heading("grens", text=tr("Grens"))
        boom.column("kort", width=px(170))
        boom.column("grens", width=px(120), anchor="center")
        boom.pack(side="left", padx=14, pady=12)
        vorm = tk.Frame(kaart, bg=CARD)
        vorm.pack(side="left", fill="both", expand=True, padx=(4, 14), pady=12)
        velden = {}
        for r, (key, tekst, br) in enumerate((("kort", tr("Naam"), 26), ("vmax", tr("Hoogste spanning (V)"), 8),
                                              ("imax", tr("Hoogste stroom (A)"), 8), ("reden", tr("Waarom deze grens"), 42),
                                              ("programmas", tr("Testprogramma's die beginnen met"), 26))):
            tk.Label(vorm, text=tekst, bg=CARD, fg=TEXT, font=(FONT, 10)).grid(row=r, column=0, sticky="w", pady=3)
            e = self._entry(vorm, br, size=11, justify="left")
            e.grid(row=r, column=1, sticky="w", padx=(10, 0), pady=3, ipady=2)
            velden[key] = e
        tk.Label(vorm, text=tr("Kleur"), bg=CARD, fg=TEXT, font=(FONT, 10)).grid(row=5, column=0, sticky="w", pady=3)
        palet = tk.Frame(vorm, bg=CARD)
        palet.grid(row=5, column=1, sticky="w", padx=(10, 0), pady=3)
        kleur_var = tk.StringVar(value=PROJECT_KLEUREN[0])
        stalen = {}

        def toon_kleur():
            for kl, wd in stalen.items():
                wd.config(highlightbackground=TEXT if kl == kleur_var.get() else CARD)

        for kl in PROJECT_KLEUREN:
            st_ = tk.Frame(palet, bg=kl, width=px(24), height=px(24), highlightthickness=px(2), highlightbackground=CARD,
                           cursor="hand2")
            st_.pack(side="left", padx=(0, 6))
            st_.bind("<Button-1>", lambda e, k=kl: (kleur_var.set(k), toon_kleur()))
            stalen[kl] = st_
        extra = tk.Label(vorm, text="", bg=CARD, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(480))
        extra.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        melding = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=(FONT, 10), anchor="w")
        melding.pack(fill="x", padx=22, pady=(8, 0))

        def gekozen():
            sel = boom.selection()
            return sel[0] if sel else None

        def ververs(kies=None):
            boom.delete(*boom.get_children())
            for k, p in PROJECTS.items():
                boom.insert("", "end", iid=k, values=(p["kort"], f"{nl(p['vmax'])} V, {nl(p['imax'])} A"))
            if kies in PROJECTS:
                boom.selection_set(kies)

        def toon(_e=None):
            k = gekozen()
            if not k:
                return
            p = PROJECTS[k]
            vast = k == "vrij"
            for key, e in velden.items():
                e.config(state="normal")
                e.delete(0, "end")
                e.insert(0, nl(p[key]) if key in ("vmax", "imax") else p[key])
                e.config(state="disabled" if vast else "normal", disabledbackground=CARD_2, disabledforeground=MUTED)
            kleur_var.set(p["kleur"])
            toon_kleur()
            extra.config(text=(tr("Eigen geheugens: {0}.  Eigen bewaking: {1}.", len(p.get('geheugens') or {}), tr('ja') if p.get('bewaking') else tr('nee'))
                               + (tr("  Vrij kan niet worden gewijzigd.") if vast else "")))

        def waarden():
            try:
                vmax, imax = (float(velden[k].get().replace(",", ".")) for k in ("vmax", "imax"))
            except ValueError:
                melding.config(text=tr("Vul bij spanning en stroom getallen in."), fg=BAD)
                return None
            kort = velden["kort"].get().strip()
            uit = schoon_project({"naam": tr("{0}: max {1} V, {2} A", kort, nl(vmax), nl(imax)), "kort": kort, "kleur": kleur_var.get(),
                                  "vmax": vmax, "imax": imax, "reden": velden["reden"].get().strip(),
                                  "programmas": velden["programmas"].get()})
            if uit and (uit["vmax"] > MAX_V or uit["imax"] > MAX_A):
                uit = None
            if not uit:
                melding.config(text=tr("Vul een naam in, en een grens tussen 0 en {0} V en {1} A.", nl(MAX_V), nl(MAX_A)), fg=BAD)
            return uit

        def schrijf():
            try:
                save_projects()
                return True
            except OSError as e:
                melding.config(text=tr("Niet opgeslagen: {0}", e), fg=BAD)
                return False

        def opslaan():
            k = gekozen()
            if not k or k == "vrij":
                return
            uit = waarden()
            if not uit:
                return
            if naam_bezet(uit["kort"], behalve=k):
                melding.config(text=tr("Er is al een project met de naam {0}. Kies een andere naam.", uit["kort"]), fg=BAD)
                return
            oud = PROJECTS[k]
            if (uit["vmax"] > oud["vmax"] or uit["imax"] > oud["imax"]) and not messagebox.askyesno(
                    tr("Hogere grens"), tr("De grens van {0} gaat omhoog naar {1} V en {2} A.\n\nWeet je zeker dat dit "
                                       "project dat aankan?", oud['kort'], nl(uit['vmax']), nl(uit['imax'])), icon="warning", parent=win):
                return
            for extra_veld in ("geheugens", "bewaking"):
                if oud.get(extra_veld):
                    uit[extra_veld] = oud[extra_veld]
            PROJECTS[k] = schoon_project(uit) or oud
            if schrijf():
                melding.config(text=tr("Opgeslagen."), fg=GOOD)
            na_wijziging(k)

        def na_wijziging(k):
            ververs(k)
            toon()
            self._project_gegevens()
            for n in (1, 2, 3, 4):
                self._label_preset(n)
            self._update_guard_lamp()
            self._teken_pill()
            if self.vset is not None:
                self._spanning_binnen_grens()
                self._schaal_spanning(self.vset)
                self._enforce_limits(self.vset, self.iset or 0)

        def naam_bezet(kort, behalve=None):
            return any(k != behalve and p["kort"].strip().lower() == kort.strip().lower() for k, p in PROJECTS.items())

        def nieuw():
            """Een leeg project met een voorzichtige grens; de gebruiker vult daarna naam en grens in."""
            basis = tr("Nieuw project")
            kort, n = basis, 2
            while naam_bezet(kort):
                kort, n = f"{basis} {n}", n + 1
            vmax, imax = min(5.0, MAX_V), min(0.5, MAX_A)
            uit = schoon_project({"naam": tr("{0}: max {1} V, {2} A", kort, nl(vmax), nl(imax)), "kort": kort,
                                  "kleur": kleur_var.get(), "vmax": vmax, "imax": imax, "reden": "", "programmas": ""})
            k = re.sub(r"[^a-z0-9]+", "-", kort.lower()).strip("-") or "project"
            while k in PROJECTS:
                k += "-2"
            PROJECTS[k] = uit
            if schrijf():
                melding.config(text=tr("Nieuw project gemaakt. Vul de naam en de grens in en klik op Opslaan."), fg=GOOD)
            ververs(k)
            toon()
            velden["kort"].focus_set()
            velden["kort"].selection_range(0, "end")

        def weg():
            k = gekozen()
            if not k or k in BASIS_PROJECTEN:
                melding.config(text=tr("De drie vaste projecten kunnen niet weg."), fg=BAD)
                return
            if k == self.settings["project"]:
                melding.config(text=tr("Kies eerst een ander project."), fg=BAD)
                return
            if messagebox.askyesno(tr("Project verwijderen"), tr("{0} verwijderen?", PROJECTS[k]['kort']), parent=win):
                del PROJECTS[k]
                schrijf()
                ververs("vrij")
                toon()

        def huidige_bewaren():
            k = gekozen()
            if not k or k == "vrij":
                return
            p = PROJECTS[k]
            buiten = [n for n, (v, i) in self.presets.items() if v > p["vmax"] or i > p["imax"]]
            p["geheugens"] = {n: list(w) for n, w in self.presets.items() if n not in buiten}
            p["bewaking"] = json.loads(json.dumps(self.guards))
            if schrijf():
                melding.config(text=tr("Geheugens en bewaking van nu bewaard in dit project")
                                    + (tr(" (buiten de grens en overgeslagen: M{0}).", ', M'.join(buiten)) if buiten else "."),
                               fg=GOOD)
            na_wijziging(k)

        def eigen_wissen():
            k = gekozen()
            if not k or k == "vrij":
                return
            PROJECTS[k].pop("geheugens", None)
            PROJECTS[k].pop("bewaking", None)
            if schrijf():
                melding.config(text=tr("Dit project gebruikt weer de gewone geheugens en bewaking."), fg=GOOD)
            na_wijziging(k)

        boom.bind("<<TreeviewSelect>>", toon)
        balk = tk.Frame(win, bg=PANEL)
        balk.pack(fill="x", padx=22, pady=(10, 4))
        self._btn(balk, tr("Opslaan"), opslaan, bg=BTN_GREEN).pack(side="left")
        self._btn(balk, tr("Nieuw project maken"), nieuw).pack(side="left", padx=6)
        self._btn(balk, tr("Verwijderen"), weg).pack(side="left")
        balk2 = tk.Frame(win, bg=PANEL)
        balk2.pack(fill="x", padx=22, pady=(4, 14))
        self._btn(balk2, tr("Geheugens en bewaking van nu bewaren"), huidige_bewaren).pack(side="left")
        self._btn(balk2, tr("Eigen geheugens en bewaking wissen"), eigen_wissen).pack(side="left", padx=6)
        self._btn(balk2, tr("Dit project kiezen"), lambda: gekozen() and self._kies_project(gekozen()), bg=BLUE).pack(
            side="right", padx=(6, 0))
        self._btn(balk2, tr("Sluiten"), win.destroy).pack(side="right")
        ververs(self.settings["project"])
        toon()

    # ---------- grens per project
    def _limits(self):
        p = PROJECTS[self.settings["project"]]
        return min(p["vmax"], MAX_V), min(p["imax"], MAX_A)

    def _limit_text(self):
        p = PROJECTS[self.settings["project"]]
        vmax, imax = self._limits()
        return (tr("De grens staat op \"{0}\": spanning hooguit {1} V en stroomgrens hooguit {2} A ({3}). Een "
                   "andere grens kies je met de projectknop bovenin.", p['naam'], nl(vmax), nl(imax), p['reden']))

    def _kies_project(self, key):
        huidig = self.settings["project"]
        if key == huidig:
            return
        nieuw, oud = PROJECTS[key], PROJECTS[huidig]
        if key == "vrij":
            if not messagebox.askyesno(
                    tr("Grens loslaten"),
                    tr("Met de grens Vrij gaat het paneel tot {0} V en {1} A, het volledige bereik van de voeding.\n\n"
                       "Kan alles wat nu is aangesloten dat aan?", nl(MAX_V), nl(MAX_A)),
                    icon="warning"):
                return
        elif nieuw["vmax"] > oud["vmax"] or nieuw["imax"] > oud["imax"]:
            if not messagebox.askyesno(
                    tr("Hogere grens"),
                    tr("{0} mag hoger dan {1}: {2} V en {3} A.\n\nKan alles wat nu is aangesloten dat aan?", nieuw['kort'], oud['kort'], nl(nieuw['vmax']), nl(nieuw['imax'])), icon="warning"):
                return
        self.settings["project"] = key
        save_settings(self.settings)
        self._project_gegevens()
        for n in (1, 2, 3, 4):
            self._label_preset(n)
        self._update_guard_lamp()
        self._teken_pill()
        self.afdruk_controle = self._afdruk_laatste = None
        self._toon_afdruk("--")
        self._add_marker(tr("grens: {0}", PROJECTS[key]['naam']))
        if self.vset is not None:
            self._spanning_binnen_grens()
            self._schaal_spanning(self.vset)
            self._enforce_limits(self.vset, self.iset or 0)

    def _spanning_binnen_grens(self):
        """Na het kiezen of wijzigen van een project: staat de voeding hoger ingesteld dan de nieuwe grens en is de
        uitgang uit, dan gaat de ingestelde spanning mee omlaag. Omlaag is altijd veilig; met de uitgang aan grijpt
        _enforce_limits in."""
        vmax = self._limits()[0]
        if self.dev and not self.out and self.vset is not None and self.vset > vmax + 0.005:
            self.cmdq.put(f"VSET1:{vmax:.2f}")
            self._add_marker(tr("spanning teruggezet naar {0} V (grens)", nl(vmax)))

    def _limit_trip(self, why):
        now = time.time()
        if now - self.limit_t < 3:
            return
        self.limit_t = now
        self.cmdq.put("OUT0")
        self._stop_program(tr("Gestopt: boven de grens"))
        self._stop_sim(tr("Gestopt: boven de grens"))
        self._stop_new(tr("Gestopt: boven de grens"))
        self._night_event("grens", tr("boven de grens: uitgang uit"))
        self._raise_alarm(tr("{0}. Uitgang uitgezet.", why), tr("grens: uitgang uit"))

    def _enforce_limits(self, vs, is_):
        """De voeding kan ook aan de voorkant (draaiknop, M-knoppen) hoger worden gezet: dan grijpt het paneel in."""
        vmax, imax = self._limits()
        if vs > vmax + 0.005 and self.out:
            self._limit_trip(tr("Spanning ingesteld op {0} V, boven de grens van {1} V (draaiknop of "
                                "geheugenknop op de voeding?)", nlf(vs, 2), nl(vmax)))
        if is_ > imax + 0.0005 and time.time() - self.ilimit_t > 3:
            self.ilimit_t = time.time()
            self.cmdq.put(f"ISET1:{imax:.3f}")
            self._add_marker(tr("stroomgrens teruggezet naar {0} A (grens)", nl(imax)))

    # ---------- bediening
    def _send(self, cmd):
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."))
            return False
        self.cmdq.put(cmd)
        return True

    def _label_preset(self, n):
        v, i = self.presets[str(n)]
        self.preset_btns[n].config(text=f"{nl(v)} V\n{nl(i)} A")

    def _recall(self, n):
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."))
            return
        target = self.presets[str(n)][0]
        vmax, imax = self._limits()
        if target > vmax + 0.005 or self.presets[str(n)][1] > imax + 0.0005:
            messagebox.showerror(tr("Buiten de grens"), tr("Geheugen M{0} staat op {1} V en {2} A.\n\n", n, nl(target), nl(self.presets[str(n)][1])) + self._limit_text())
            return
        if self.out and self.vset is not None and target > self.vset + 0.05:
            if not messagebox.askyesno(
                    tr("Hogere spanning op de uitgang"),
                    tr("De uitgang staat aan.\n\nDeze knop verhoogt de spanning van {0} V naar {1} V, direct op "
                       "wat er nu is aangesloten.\n\nDoorgaan?", nl(self.vset), nl(target)), icon="warning"):
                return
        self._stop_sim(tr("Gestopt: geheugenknop gebruikt"))
        self._stop_new(tr("Gestopt: geheugenknop gebruikt"))
        self._stop_program(tr("Gestopt: geheugenknop gebruikt"))
        if str(n) in self.preset_eigen:      # geheugen van dit project: de geheugens in de voeding blijven zoals ze zijn
            self.cmdq.put(f"ISET1:{self.presets[str(n)][1]:.3f}")
            self.cmdq.put(f"VSET1:{target:.2f}")
            return
        self.pending = (n, time.time())
        self.cmdq.put(f"RCL{n}")

    def _apply(self):
        self._stop_sim(tr("Gestopt: handmatig ingesteld"))
        self._stop_new(tr("Gestopt: handmatig ingesteld"))
        self._stop_program(tr("Gestopt: handmatig ingesteld"))
        try:
            v = float(self.v_entry.get().replace(",", "."))
            i = float(self.i_entry.get().replace(",", "."))
        except ValueError:
            messagebox.showerror(tr("Ongeldige waarde"), tr("Vul getallen in, bijvoorbeeld 5,00 en 0,500."))
            return
        vmax, imax = self._limits()
        if not (0 <= v <= vmax and 0 <= i <= imax):
            messagebox.showerror(tr("Buiten de grens"), self._limit_text())
            return
        if self.out and self.vset is not None and v > self.vset + 0.05:
            if not messagebox.askyesno(
                    tr("Hogere spanning op de uitgang"),
                    tr("De uitgang staat aan.\n\nDe spanning gaat van {0} V naar {1} V, direct op wat er nu is "
                       "aangesloten.\n\nDoorgaan?", nl(self.vset), nl(v)), icon="warning"):
                return
        if self._send(f"ISET1:{i:.3f}"):     # eerst de stroomgrens, dan de spanning
            self._send(f"VSET1:{v:.2f}")
            self.focus_set()

    def _toggle_out(self):
        if not self.out:
            vmax, imax = self._limits()
            if (self.vset or 0) > vmax + 0.005 or (self.iset or 0) > imax + 0.0005:
                messagebox.showerror(tr("Buiten de grens"), tr("De voeding staat op {0} V en {1} A.\n\n", nl(self.vset or 0), nl(self.iset or 0)) + self._limit_text())
                return
        self._stop_program(tr("Gestopt: uitgang handmatig bediend"))
        self._stop_new(tr("Gestopt: uitgang handmatig bediend"))
        self._send("OUT0" if self.out else "OUT1")

    def _toggle_log(self):
        if self.log_file:
            self._log_close()
            return
        path = filedialog.asksaveasfilename(
            title=tr("Log opslaan als"), defaultextension=".csv",
            initialfile=f"korad_{datetime.now():%Y%m%d_%H%M}.csv",
            filetypes=[(tr("CSV-bestand"), "*.csv")])
        if not path:
            return
        self._log_open(path)

    def _log_close(self):
        if not self.log_file:
            return
        self.log_file.close()
        self.log_file = self.log_writer = None
        self.log_btn.config(text=tr("Log starten"), bg=PANEL_DARK)
        self.log_lbl.config(text=tr("Log gestopt na {0} metingen", self.log_rows))
        e, self._wb_log = self._wb_log, None
        if e is not None:
            e["uitleg"] = (tr("{0} metingen, {1:%H:%M} tot {2:%H:%M}", self.log_rows, datetime.fromtimestamp(e['t']), datetime.now()))
            save_workbook(self.wb)
            self._wb_refresh()

    def _log_open(self, path):
        self.log_file = open(path, "w", newline="", encoding="utf-8")
        self._extra_in_beeld()
        self.log_writer = csv.writer(self.log_file)
        self.log_writer.writerow(["tijd", "spanning_V", "stroom_A", "vermogen_W", "modus", "uitgang",
                                  "lading_mAh", "energie_Wh", "markering"])
        self.log_rows = 0
        self.log_btn.config(text=tr("Log stoppen"), bg=BTN_RED)
        self.log_lbl.config(text=tr("Loggen gestart"))
        self._wb_log = self._wb_add("log", Path(path).name, path, tr("loggen loopt"))

    # ---------- energieteller
    def _reset_energy(self):
        self.e_start, self.e_last = time.time(), None
        self.charge_as = self.energy_j = 0.0
        self._show_energy()
        self.dips.nul()
        self._toon_dips()

    def _show_energy(self):
        secs = int(time.time() - self.e_start)
        self.e_title.config(text=tr("VERBRUIK SINDS {0:%H:%M}", datetime.fromtimestamp(self.e_start)))
        mah = self.charge_as / 3.6
        self.e_mah.config(text=dec(f"{mah:,.1f} mAh".replace(",", " ")))
        self.e_wh.config(text=dec(f"{self.energy_j / 3600:.3f} Wh"))
        self.e_time.config(text=f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")

    def _show_stats(self, pts, title):
        self.s_title.config(text=title.upper())
        if not pts:
            for l in self.s_vals.values():
                l.config(text="--")
            return
        cur = [p[2] for p in pts]
        q = sum((b[0] - a[0]) * (a[2] + b[2]) / 2
                for a, b in zip(pts, pts[1:]) if 0 < b[0] - a[0] < 2)
        for key, val in (("max", max(cur)), ("avg", sum(cur) / len(cur)), ("min", min(cur))):
            self.s_vals[key].config(text=dec(f"{val * 1000:.1f} mA"))
        self.s_vals["q"].config(text=dec(f"{q / 3.6:.2f} mAh"))

    # ---------- bewaking
    def _update_guard_lamp(self):
        if self.alarm:
            self.lamp_guard.set(True, LED_RED)
        else:
            self.lamp_guard.set(any(g["aan"] for g in self.guards))
        self._update_status()

    def _check_guards(self, t, v, i, w, st):
        if not st or not st["out"] or self.part is not None:
            for gs in self.guard_state:
                gs["since"], gs["fired"] = None, False
            return
        vals = {"stroom": i * 1000, "spanning": v, "vermogen": w}
        for g, gs in zip(self.guards, self.guard_state):
            if not g["aan"]:
                continue
            x = vals[g["wat"]]
            hit = x > g["waarde"] if g["richting"] == "boven" else x < g["waarde"]
            if not hit:
                gs["since"], gs["fired"] = None, False
                continue
            if gs["since"] is None:
                gs["since"] = t
            if not gs["fired"] and t - gs["since"] >= g["duur"]:
                gs["fired"] = True
                self._fire_guard(g, x, t)

    def _fire_guard(self, g, x, t):
        unit = UNITS[g["wat"]]
        shown = f"{x:.0f}" if unit == "mA" else dec(f"{x:.2f}")
        txt = (tr("{0} {1} {2}, {3} de {4} {5} langer dan {6} s", tr(g['wat']).capitalize(), shown, unit, tr(g['richting']), nl(g['waarde']), unit, nl(g['duur'])))
        if g["actie"] == "uitgang uit":
            self.cmdq.put("OUT0")
            self._stop_sim(tr("Gestopt: alarm"))
            self._stop_program(tr("Gestopt: alarm"))
            self._stop_new(tr("Gestopt: alarm"))
            self._night_event("bewaking", tr("bewaking: uitgang uit"))
            txt += tr(". Uitgang uitgezet.")
        else:
            txt += "."
        self._raise_alarm(txt, tr("alarm: {0} {1} {2} {3}", tr(g['wat']), tr(g['richting']), nl(g['waarde']), unit), t)

    def _raise_alarm(self, txt, marker, t=None):
        t = t or time.time()
        self.alarm = f"{datetime.fromtimestamp(t):%H:%M:%S}  {txt}"
        self.alarm_lbl.config(text=tr("Alarm om {0}", self.alarm[:8]))
        self.alarm_btn.pack(anchor="w", padx=14, pady=(4, 10))
        self._update_guard_lamp()
        self._add_marker(marker)
        beep()
        self._say(tr("Alarm. ") + txt.split(". ")[0])
        self._notify(tr("Alarm"), txt, priority=5, tags=("warning",))

    def _clear_alarm(self):
        self.alarm = None
        self.alarm_lbl.config(text="")
        self.alarm_btn.pack_forget()
        self._update_guard_lamp()

    def _open_guards(self):
        if getattr(self, "_gwin", None) and self._gwin.winfo_exists():
            self._gwin.lift()
            return
        win = tk.Toplevel(self)
        self.after(10, lambda w=win: self._center(w))
        self._gwin = win
        win.title(tr("Bewaking"))
        win.configure(bg=PANEL)
        win.transient(self)
        win.resizable(False, False)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        self._kop(win, tr("Bewaking")).grid(
            row=0, column=0, columnspan=9, sticky="w", padx=16, pady=(14, 2))
        tk.Label(win, bg=PANEL, fg=INK, font=(FONT, 10), wraplength=px(680), justify="left",
                 text=tr("Regels werken alleen als de uitgang aan staat. Het programma reageert binnen ongeveer "
                         "een halve seconde. De stroomgrens van de voeding zelf blijft de echte beveiliging; dit "
                         "is een extra laag daarbovenop.")).grid(
            row=1, column=0, columnspan=9, sticky="w", padx=16, pady=(0, 12))
        body = self._card(win)
        body.grid(row=2, column=0, columnspan=9, sticky="ew", padx=16)
        rows = []
        for n, g in enumerate(self.guards):
            r = n
            on = tk.BooleanVar(value=g["aan"])
            self._check(body, tr("Regel {0}", n + 1), on, bg=CARD, size=11).grid(row=r, column=0, padx=(14, 8), pady=(10 if n == 0 else 4, 10 if n == 2 else 4))
            wat = Keuze(body, list(UNITS), width=9, state="readonly")
            wat.set(g["wat"])
            wat.grid(row=r, column=1, padx=3)
            rich = Keuze(body, ["boven", "onder"], width=8, state="readonly")
            rich.set(g["richting"])
            rich.grid(row=r, column=2, padx=3)
            val = tk.Entry(body, width=7, font=(FONT, 11), justify="right", relief="flat",
                           highlightthickness=1, highlightbackground=PANEL_DARK)
            val.insert(0, nl(g["waarde"]))
            val.grid(row=r, column=3, padx=3)
            unit = tk.Label(body, text=UNITS[g["wat"]], bg=CARD, fg=INK, width=3, anchor="w", font=(FONT, 11))
            unit.grid(row=r, column=4)
            wat.bind("<<ComboboxSelected>>", lambda e, w=wat, u=unit: u.config(text=UNITS[w.get()]))
            tk.Label(body, text=tr("langer dan"), bg=CARD, fg=INK, font=(FONT, 11)).grid(row=r, column=5, padx=(6, 3))
            dur = tk.Entry(body, width=5, font=(FONT, 11), justify="right", relief="flat",
                           highlightthickness=1, highlightbackground=PANEL_DARK)
            dur.insert(0, nl(g["duur"]))
            dur.grid(row=r, column=6)
            tk.Label(body, text=tr("s, dan"), bg=CARD, fg=INK, font=(FONT, 11)).grid(row=r, column=7, padx=3)
            act = Keuze(body, ["uitgang uit", "waarschuwen"], width=14, state="readonly")
            act.set(g["actie"])
            act.grid(row=r, column=8, padx=(3, 14))
            rows.append((on, wat, rich, val, dur, act))

        def save():
            new = []
            for n, (on, wat, rich, val, dur, act) in enumerate(rows):
                try:
                    x = float(val.get().replace(",", "."))
                    d = float(dur.get().replace(",", "."))
                except ValueError:
                    messagebox.showerror(tr("Ongeldige waarde"), tr("Regel {0}: vul getallen in.", n + 1), parent=win)
                    return
                if x < 0 or d < 0:
                    messagebox.showerror(tr("Ongeldige waarde"), tr("Regel {0}: geen negatieve getallen.", n + 1), parent=win)
                    return
                new.append({"aan": on.get(), "wat": wat.get(), "richting": rich.get(),
                            "waarde": x, "duur": d, "actie": act.get()})
            self._bewaking_bewaar(new)
            win.destroy()

        bar = tk.Frame(win, bg=PANEL)
        bar.grid(row=10, column=0, columnspan=9, sticky="e", padx=16, pady=(14, 14))
        self._btn(bar, tr("Annuleren"), win.destroy).pack(side="right", padx=(8, 0))
        self._btn(bar, tr("Opslaan"), save, bg=BTN_GREEN).pack(side="right")

    def _bewaking_bewaar(self, new):
        self.guards = new
        self.guard_state = [{"since": None, "fired": False} for _ in new]
        project = PROJECTS[self.settings["project"]]
        try:
            if project.get("bewaking"):      # dit project heeft eigen regels: daar horen de wijzigingen thuis
                project["bewaking"] = json.loads(json.dumps(new))
                save_projects()
            else:
                GUARD_FILE.write_text(json.dumps(new, indent=2), encoding="utf-8")
        except OSError:
            pass
        self._update_guard_lamp()

    # ---------- testprogramma's: uitvoeren
    def _start_program(self, prog):
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."))
            return False
        steps = prog["stappen"]
        if not steps:
            messagebox.showerror(tr("Leeg programma"), tr("Voeg eerst een of meer stappen toe."))
            return False
        vmax, imax = self._limits()
        bad = [n + 1 for n, st in enumerate(steps) if st["v"] > vmax + 0.005 or st["i"] > imax + 0.0005]
        if bad:
            messagebox.showerror(tr("Buiten de grens"), tr("\"{0}\": stap {1} gaat boven de grens en kan dus niet "
                                                       "starten.\n\n", prog['naam'], ', '.join(map(str, bad))) + self._limit_text())
            return False
        on = [st["v"] for st in steps if st["uit"] == "aan"]
        total = sum(st["duur"] for st in steps) * prog["herhalen"]
        reps = tr(", {0} keer", prog['herhalen']) if prog["herhalen"] > 1 else ""
        about = f"{prog['omschrijving']}\n\n" if prog.get("omschrijving") else ""
        checks = sum(1 for st in steps if st.get("verwacht"))
        about += tr("{0} stappen hebben een verwachting (goed of fout in het rapport).\n\n", checks) if checks else ""
        if not messagebox.askyesno(
                tr("Testprogramma starten"),
                tr("\"{0}\": {1} stappen{2}, totaal {3}.\n\n{4}Hoogste spanning: {5} V. Controleer of alles wat is "
                   "aangesloten dat aankan.\n\nStarten?", prog['naam'], len(steps), reps, fmt_duur(total), about, nl(max(on) if on else 0)), icon="warning"):
            return False
        self._stop_sim(tr("Gestopt: testprogramma gestart"))
        self._stop_new(tr("Gestopt: testprogramma gestart"))
        self._extra_in_beeld()
        self.run = {"prog": json.loads(json.dumps(prog)), "idx": -1, "rep": 1,
                    "t_step": None, "v_from": self.vset or 0.0, "last_v": None, "results": []}
        self.prog_stop_btn.pack(side="right", padx=6, before=self.prog_lbl)
        self._add_marker(tr("testprogramma: {0}", prog['naam']))
        self._next_step()
        if self.run:
            self._prog_tick()
        return True

    def _prog_setv(self, v):
        v = round(max(0.0, min(self._limits()[0], v)), 2)
        if v != self.run["last_v"]:
            self.cmdq.put(f"VSET1:{v:.2f}")
            self.run["last_v"] = v

    def _next_step(self):
        r = self.run
        steps = r["prog"]["stappen"]
        r["idx"] += 1
        if r["idx"] >= len(steps):
            if r["rep"] < r["prog"]["herhalen"]:
                r["rep"] += 1
                r["idx"] = 0
            else:
                self._stop_program(tr("Klaar"), off=r["prog"].get("uit_na_afloop", True))
                return
        st = steps[r["idx"]]
        r["t_step"] = time.time()
        r["v_from"] = r["last_v"] if r["last_v"] is not None else (self.vset or 0.0)
        self.cmdq.put(f"ISET1:{min(st['i'], self._limits()[1]):.3f}")
        ramp = st["overgang"] == "helling" and st["uit"] == "aan" and st["duur"] > 0
        self._prog_setv(r["v_from"] if ramp else st["v"])
        self.cmdq.put("OUT1" if st["uit"] == "aan" else "OUT0")
        n = r["idx"] + 1
        if st["uit"] == "uit":
            self._add_marker(tr("stap {0}: uitgang uit", n))
        else:
            self._add_marker(tr("stap {0}: {1}{2} V", n, tr('helling naar ') if ramp else '', nl(st['v'])))

    def _prog_tick(self):
        r = self.run
        if not r:
            return
        steps = r["prog"]["stappen"]
        st = steps[r["idx"]]
        el = time.time() - r["t_step"]
        if st["overgang"] == "helling" and st["uit"] == "aan" and st["duur"] > 0:
            frac = min(1.0, el / st["duur"])
            self._prog_setv(r["v_from"] + (st["v"] - r["v_from"]) * frac)
        if el >= st["duur"]:
            self._eval_step(st, r["idx"] + 1, r["rep"], r["t_step"], time.time(), r["results"])
            self._next_step()
            if not self.run:
                return
            st, el = steps[r["idx"]], 0.0
        left_step = max(0.0, st["duur"] - el)
        rest = sum(x["duur"] for x in steps[r["idx"] + 1:])
        rest += sum(x["duur"] for x in steps) * (r["prog"]["herhalen"] - r["rep"])
        reps = tr(", ronde {0}/{1}", r['rep'], r['prog']['herhalen']) if r["prog"]["herhalen"] > 1 else ""
        self.prog_lbl.config(text=tr("Stap {0}/{1}{2}: nog {3}, totaal nog {4}", r['idx'] + 1, len(steps), reps, fmt_duur(left_step), fmt_duur(left_step + rest)))
        self.after(200, self._prog_tick)

    def _stop_program(self, msg, off=False):
        if not self.run:
            return
        name = self.run["prog"]["naam"]
        results = self.run.get("results", [])
        self.run = None
        if off:
            self.cmdq.put("OUT0")
        self.prog_stop_btn.pack_forget()
        self.prog_lbl.config(text=f"{name}: {msg.lower()}" + (tr(", uitgang uit") if off else ""))
        self._add_marker(tr("testprogramma: {0}", msg[0].lower() + msg[1:]))
        self.after(500, lambda: self._program_summary(name, msg, results))

    def _program_summary(self, name, msg, results):
        fails = [x for x in results if not x["ok"]]
        body = f"{name}: {msg[0].lower() + msg[1:]}."
        if results:
            txt = tr("{0} van {1} controles goed", len(results) - len(fails), len(results))
            if not self.run:
                self.prog_lbl.config(text=f"{msg}: {txt}")
            self._add_marker(f"{name}: {txt}")
            body += f" {txt}."
            if fails:
                body += tr(" Fout: ") + "; ".join(f"{x['stap']} {x['wat']} ({x['gemeten']})" for x in fails[:5])
        if msg == tr("Klaar") or any(tr(w).lower() in msg.lower() for w in ("alarm", "verbinding", "grens", "fout")):
            self._notify(tr("Testprogramma"), body, priority=4 if fails or msg != tr("Klaar") else 3,
                         tags=("x",) if fails else ("white_check_mark",) if results else ())
        self._wb_add("programma", name, about=body)
        if msg == tr("Klaar"):
            self._say(tr("Testprogramma klaar.") + (tr(" {0} van {1} controles goed.", len(results) - len(fails), len(results))
                                                if results else ""))

    # ---------- verwachtingen per stap
    def _eval_step(self, st, n, rep, ta, tb, bucket):
        exp = st.get("verwacht") or {}
        if not exp:
            return
        reps = self.run["prog"]["herhalen"] if self.run else 1
        label = tr("stap {0}", n) + (tr(" (ronde {0})", rep) if reps > 1 else "")
        na = float(exp.get("na") or 0)
        lo, hi = exp.get("i_min"), exp.get("i_max")
        if lo is not None or hi is not None:
            pts = [p for p in self.hist if ta + na <= p[0] <= tb]
            if lo is not None and hi is not None:
                want = tr("stroom {0} tot {1} mA", nl(lo), nl(hi))
            else:
                want = tr("stroom minstens {0} mA", nl(lo)) if lo is not None else tr("stroom hooguit {0} mA", nl(hi))
            if not pts:
                self._add_result(bucket, tb, label, want, tr("geen metingen"), False)
            else:
                avg = sum(p[2] for p in pts) / len(pts) * 1000
                ok = (lo is None or avg >= lo) and (hi is None or avg <= hi)
                self._add_result(bucket, tb, label, want, tr("gemiddeld {0} mA", nlf(avg, 0)), ok)

    def _add_result(self, bucket, t, label, want, got, ok):
        res = {"t": t, "stap": label, "wat": want, "gemeten": got, "ok": ok}
        bucket.append(res)
        self.results.append(res)
        self._add_marker(f"{label} {tr("GOED") if ok else tr("FOUT")}: {got}")

    # ---------- testprogramma's: bewerken
    def _open_programs(self):
        if getattr(self, "_pwin", None) and self._pwin.winfo_exists():
            self._pwin.lift()
            return
        win = tk.Toplevel(self)
        self.after(10, lambda w=win: self._center(w))
        self._pwin = win
        win.title(tr("Testprogramma's"))
        win.configure(bg=PANEL)
        win.transient(self)
        win.resizable(False, False)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        prog = json.loads(json.dumps(self.program))

        def label(parent, text, bold=False, **kw):
            return tk.Label(parent, text=text, bg=PANEL, fg=INK, font=(FONT, 11, "bold" if bold else "normal"), **kw)

        def entry(parent, width, val=""):
            e = tk.Entry(parent, width=width, font=(FONT, 11), justify="right", relief="flat",
                         highlightthickness=1, highlightbackground=PANEL_DARK)
            e.insert(0, val)
            return e

        self._kop(win, tr("Testprogramma's")).pack(
            anchor="w", padx=16, pady=(14, 2))
        label(win, tr("Een reeks stappen die de voeding automatisch doorloopt. Sprong: de spanning gaat direct "
                      "naar de waarde. Helling: de spanning loopt geleidelijk vanaf de vorige stap."),
              wraplength=px(720), justify="left").pack(anchor="w", padx=16, pady=(0, 10))

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=16)
        label(head, tr("Naam")).pack(side="left")
        name_e = tk.Entry(head, width=28, font=(FONT, 11), relief="flat",
                          highlightthickness=1, highlightbackground=PANEL_DARK)
        name_e.insert(0, prog["naam"])
        name_e.pack(side="left", padx=(6, 18))
        label(head, tr("Herhalen")).pack(side="left")
        rep_e = entry(head, 4, str(prog["herhalen"]))
        rep_e.pack(side="left", padx=(6, 4))
        label(head, tr("keer")).pack(side="left", padx=(0, 18))
        off_var = tk.BooleanVar(value=prog.get("uit_na_afloop", True))
        self._check(head, tr("Uitgang uit na afloop"), off_var, size=11).pack(side="left")

        style = ttk.Style(win)
        style.configure("Prog.Treeview", font=(FONT, 11), rowheight=px(28))
        style.configure("Prog.Treeview.Heading", font=(FONT, 10, "bold"))
        cols = ("nr", "overgang", "v", "i", "uit", "duur", "verwacht")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=10, style="Prog.Treeview",
                            selectmode="browse")
        for col, txt, wdt in zip(cols, (tr("Stap"), tr("Overgang"), tr("Spanning"), tr("Stroomgrens"), tr("Uitgang"), tr("Duur"),
                                        tr("Verwachting")),
                                 (50, 95, 95, 110, 75, 80, 250)):
            tree.heading(col, text=txt)
            tree.column(col, width=px(wdt), anchor="center")
        tree.pack(fill="x", padx=16, pady=10)
        total_lbl = label(win, "")
        total_lbl.pack(anchor="e", padx=16)

        edit = tk.Frame(win, bg=PANEL)
        edit.pack(fill="x", padx=16, pady=(8, 4))
        label(edit, tr("Overgang")).pack(side="left")
        ov = Keuze(edit, ["sprong", "helling"], width=9, state="readonly")
        ov.set("sprong")
        ov.pack(side="left", padx=(6, 12))
        label(edit, tr("Spanning")).pack(side="left")
        v_e = entry(edit, 6, dec("5.00"))
        v_e.pack(side="left", padx=(6, 2))
        label(edit, "V").pack(side="left", padx=(0, 12))
        label(edit, tr("Stroomgrens")).pack(side="left")
        i_e = entry(edit, 6, dec("0.500"))
        i_e.pack(side="left", padx=(6, 2))
        label(edit, "A").pack(side="left", padx=(0, 12))
        label(edit, tr("Uitgang")).pack(side="left")
        out_cb = Keuze(edit, ["aan", "uit"], width=5, state="readonly")
        out_cb.set("aan")
        out_cb.pack(side="left", padx=(6, 12))
        label(edit, tr("Duur")).pack(side="left")
        d_e = entry(edit, 7, "1:00")
        d_e.pack(side="left", padx=(6, 2))
        label(edit, "m:ss").pack(side="left")

        edit2 = tk.Frame(win, bg=PANEL)
        edit2.pack(fill="x", padx=16, pady=(2, 4))
        label(edit2, tr("Verwachting: stroom van")).pack(side="left")
        lo_e = entry(edit2, 6)
        lo_e.pack(side="left", padx=(6, 2))
        label(edit2, tr("tot")).pack(side="left", padx=4)
        hi_e = entry(edit2, 6)
        hi_e.pack(side="left", padx=(0, 2))
        label(edit2, tr("mA vanaf")).pack(side="left", padx=(2, 4))
        na_e = entry(edit2, 4, "2")
        na_e.pack(side="left")
        label(edit2, "s").pack(side="left", padx=(4, 4))
        tk.Label(edit2, text=tr("leeg = geen controle"), bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=8)

        def refresh(select=None):
            tree.delete(*tree.get_children())
            for n, st in enumerate(prog["stappen"]):
                tree.insert("", "end", iid=str(n), values=(
                    n + 1, tr(st["overgang"]), f"{nl(st['v'])} V", dec(f"{st['i']:.3f} A"),
                    tr(st["uit"]), fmt_duur(st["duur"]), expect_text(st)))
            try:
                reps = max(1, int(rep_e.get()))
            except ValueError:
                reps = 1
            total_lbl.config(text=tr("Totale duur: {0}", fmt_duur(sum((st['duur'] for st in prog['stappen'])) * reps)))
            if select is not None and 0 <= select < len(prog["stappen"]):
                tree.selection_set(str(select))
                tree.see(str(select))

        def selected():
            sel = tree.selection()
            return int(sel[0]) if sel else None

        def on_select(_e=None):
            n = selected()
            if n is None:
                return
            st = prog["stappen"][n]
            ov.set(st["overgang"])
            out_cb.set(st["uit"])
            ex = st.get("verwacht") or {}
            for e, val in ((v_e, nl(st["v"])), (i_e, dec(f"{st['i']:.3f}")),
                           (d_e, fmt_duur(st["duur"])),
                           (lo_e, "" if ex.get("i_min") is None else nl(ex["i_min"])),
                           (hi_e, "" if ex.get("i_max") is None else nl(ex["i_max"])),
                           (na_e, nl(ex.get("na", 2)))):
                e.delete(0, "end")
                e.insert(0, val)

        tree.bind("<<TreeviewSelect>>", on_select)

        def read_fields():
            vals = {}
            for key, e, what, conv in (("v", v_e, tr("Spanning"), lambda x: float(x.replace(",", "."))),
                                       ("i", i_e, tr("Stroomgrens"), lambda x: float(x.replace(",", "."))),
                                       ("d", d_e, tr("Duur"), parse_duur)):
                try:
                    vals[key] = conv(e.get().strip())
                except ValueError:
                    messagebox.showerror(tr("Ongeldige waarde"), tr("{0}: \"{1}\" kan ik niet lezen.\n\nVoorbeelden: "
                                                                "spanning 13,8, stroomgrens 1,5, duur 1:30 "
                                                                "(minuten:seconden), :30 of 30 (seconden), "
                                                                "1:00:00 (een uur).", what, e.get().strip()), parent=win)
                    e.focus_set()
                    return None
            v, i, d = vals["v"], vals["i"], vals["d"]
            if not (0 <= v <= MAX_V and 0 <= i <= MAX_A and d > 0):
                messagebox.showerror(tr("Buiten bereik"), tr("Spanning 0 tot {0} V, stroomgrens 0 tot {1} A, duur "
                                                         "langer dan 0 seconden.", nl(MAX_V), nl(MAX_A)), parent=win)
                return None
            step = {"overgang": ov.get(), "v": v, "i": i, "uit": out_cb.get(), "duur": d}
            try:
                opt = lambda e: None if not e.get().strip() else float(e.get().replace(",", "."))
                lo, hi, na = opt(lo_e), opt(hi_e), opt(na_e) or 0.0
            except ValueError:
                messagebox.showerror(tr("Ongeldige verwachting"), tr("Vul bij de verwachting getallen in, of laat "
                                                                 "het vakje leeg."), parent=win)
                return None
            if (lo is not None and hi is not None and lo > hi) or na < 0 or (na >= d and (lo or hi) is not None):
                messagebox.showerror(tr("Ongeldige verwachting"), tr("De ondergrens moet onder de bovengrens liggen, "
                                                                 "en 'vanaf' moet korter zijn dan de duur van de "
                                                                 "stap."),
                                     parent=win)
                return None
            if lo is not None or hi is not None:
                step["verwacht"] = {"i_min": lo, "i_max": hi, "na": na}
            return step

        def add():
            st = read_fields()
            if st:
                n = selected()
                pos = len(prog["stappen"]) if n is None else n + 1
                prog["stappen"].insert(pos, st)
                refresh(pos)

        def update():
            n, st = selected(), read_fields()
            if n is not None and st:
                prog["stappen"][n] = st
                refresh(n)

        def delete():
            n = selected()
            if n is not None:
                del prog["stappen"][n]
                refresh(min(n, len(prog["stappen"]) - 1))

        def move(d):
            n = selected()
            if n is None or not (0 <= n + d < len(prog["stappen"])):
                return
            s_ = prog["stappen"]
            s_[n], s_[n + d] = s_[n + d], s_[n]
            refresh(n + d)

        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=16, pady=(4, 6))
        self._btn(btns, tr("Stap toevoegen"), add).pack(side="left")
        self._btn(btns, tr("Stap bijwerken"), update).pack(side="left", padx=6)
        self._btn(btns, tr("Stap verwijderen"), delete).pack(side="left")
        self._btn(btns, tr("Omlaag"), lambda: move(1)).pack(side="right")
        self._btn(btns, tr("Omhoog"), lambda: move(-1)).pack(side="right", padx=6)

        def collect():
            try:
                reps = int(rep_e.get())
            except ValueError:
                messagebox.showerror(tr("Ongeldige waarde"), tr("Herhalen moet een heel getal zijn."), parent=win)
                return None
            prog["naam"] = name_e.get().strip() or tr("Testprogramma")
            prog["herhalen"] = max(1, reps)
            prog["uit_na_afloop"] = off_var.get()
            self.program = json.loads(json.dumps(prog))
            try:
                save_program(self.program, PROG_DIR / "laatste.json")
            except OSError:
                pass
            return self.program

        def save_as():
            if collect() is None:
                return
            PROG_DIR.mkdir(parents=True, exist_ok=True)
            path = filedialog.asksaveasfilename(parent=win, title=tr("Testprogramma opslaan"),
                                                initialdir=str(PROG_DIR), initialfile=f"{prog['naam']}.json",
                                                defaultextension=".json", filetypes=[(tr("Testprogramma"), "*.json")])
            if path:
                save_program(self.program, Path(path))

        def open_file():
            PROG_DIR.mkdir(parents=True, exist_ok=True)
            path = filedialog.askopenfilename(parent=win, title=tr("Testprogramma openen"),
                                              initialdir=str(PROG_DIR), filetypes=[(tr("Testprogramma"), "*.json")])
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                assert isinstance(data.get("stappen"), list)
            except (OSError, ValueError, AssertionError, AttributeError):
                messagebox.showerror(tr("Kan niet openen"), tr("Dit bestand is geen testprogramma."), parent=win)
                return
            laad_data(data)

        def laad_data(data):
            prog.clear()
            prog.update(data)
            name_e.delete(0, "end")
            name_e.insert(0, prog.get("naam", ""))
            rep_e.delete(0, "end")
            rep_e.insert(0, str(prog.get("herhalen", 1)))
            off_var.set(prog.get("uit_na_afloop", True))
            refresh(0)

        def nieuw_programma():
            if prog["stappen"] and not messagebox.askyesno(
                    tr("Nieuw programma"), tr("De stappen die er nu staan verdwijnen uit dit venster. Een programma "
                                              "dat je hebt opgeslagen blijft bewaard.\n\nNieuw programma beginnen?"),
                    parent=win):
                return
            laad_data({"naam": "", "herhalen": 1, "uit_na_afloop": True, "stappen": []})
            name_e.focus_set()

        def close():
            if collect() is not None:
                win.destroy()

        def start():
            if collect() is None:
                return
            if not self.program["stappen"]:
                messagebox.showinfo(tr("Geen stappen"), tr("Dit programma heeft nog geen stappen. Vul onderaan een "
                                                           "stap in en klik op Stap toevoegen."), parent=win)
                return
            if self.run:
                messagebox.showinfo(tr("Programma loopt al"), tr("Stop eerst het programma dat nu loopt."), parent=win)
                return
            win.destroy()
            self._start_program(self.program)

        rep_e.bind("<KeyRelease>", lambda e: refresh(selected()))
        tk.Frame(win, bg=PANEL_DARK, height=1).pack(fill="x", padx=16, pady=(8, 0))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=16, pady=12)
        self._btn(bar, tr("Nieuw programma"), nieuw_programma).pack(side="left")
        self._btn(bar, tr("Openen"), open_file).pack(side="left", padx=(6, 0))
        self._btn(bar, tr("Opslaan als"), save_as).pack(side="left", padx=6)
        prefix = PROJECTS[self.settings["project"]].get("programmas") or ""
        eigen_prog = sorted(PROG_DIR.glob(prefix + "*.json")) if prefix else []
        if eigen_prog:
            keuze = ttk.Combobox(bar, values=[f.stem[len(prefix):] for f in eigen_prog], width=26, state="readonly")
            keuze.set(tr("Proeven van dit project"))

            def kies_proef(_e=None):
                try:
                    data = json.loads(eigen_prog[keuze.current()].read_text(encoding="utf-8"))
                    assert isinstance(data.get("stappen"), list)
                except (OSError, ValueError, AssertionError, AttributeError, IndexError):
                    messagebox.showerror(tr("Kan niet openen"), tr("Dit bestand is geen testprogramma."), parent=win)
                    return
                laad_data(data)

            keuze.bind("<<ComboboxSelected>>", kies_proef)
            keuze.pack(side="left", padx=(6, 0))
        self._btn(bar, tr("Starten"), start, bg=BTN_GREEN).pack(side="right")
        self._btn(bar, tr("Sluiten"), close).pack(side="right", padx=6)
        win.protocol("WM_DELETE_WINDOW", close)
        refresh(0 if prog["stappen"] else None)

    # ---------- markeringen
    def _add_marker(self, text=None):
        from_user = text is None
        if from_user:
            text = self.mark_entry.get().strip() or tr("markering {0}", len(self.markers) + 1)
            self.mark_entry.delete(0, "end")
        self.markers.append((time.time(), text))
        self.pending_marker = (self.pending_marker + " | " if self.pending_marker else "") + text
        self._draw_chart()

    # ---------- accusimulatie
    def _num(self, entry):
        return float(entry.get().replace(",", ".").strip())

    def _toggle_sim(self):
        if self.sim:
            self._stop_sim(tr("Gestopt"))
            return
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."))
            return
        try:
            v0, v1, mins = self._num(self.sim_from), self._num(self.sim_to), self._num(self.sim_min)
            r_mohm = self._num(self.sim_r) if self.sim_r.get().strip() else 0.0
        except ValueError:
            messagebox.showerror(tr("Ongeldige waarde"), tr("Vul getallen in, bijvoorbeeld 13,8 en 11,0 en 10, en 0 "
                                                        "voor de inwendige weerstand."))
            return
        vmax = self._limits()[0]
        if not (0 <= v0 <= vmax and 0 <= v1 <= vmax and mins > 0 and 0 <= r_mohm <= 1000):
            messagebox.showerror(tr("Buiten bereik"), tr("Spanningen 0 tot {0} V (grens), tijd groter dan 0 minuten, "
                                                     "inwendige weerstand 0 tot 1000 mΩ.", nl(vmax)))
            return
        if self.out and self.vset is not None and v0 > self.vset + 0.05:
            if not messagebox.askyesno(
                    tr("Hogere spanning op de uitgang"),
                    tr("De uitgang staat aan.\n\nDe simulatie begint op {0} V, hoger dan de huidige {1} V, direct "
                       "op wat er nu is aangesloten.\n\nDoorgaan?", nl(v0), nl(self.vset)), icon="warning"):
                return
        self._stop_program(tr("Gestopt: accusimulatie gestart"))
        self._stop_new(tr("Gestopt: accusimulatie gestart"))
        self._extra_in_beeld()
        self.sim = {"v0": v0, "v1": v1, "dur": mins * 60, "t0": time.time(), "last": None,
                    "r": r_mohm / 1000, "i_f": None, "voc": v0, "t_send": 0.0}
        self.sim_btn.config(text=tr("Stop"), bg=BTN_RED)
        self._add_marker(tr("accu-simulatie start {0} V", nl(v0)) + (f", R {nl(r_mohm)} m\u03a9" if r_mohm else ""))
        self._sim_tick()

    def _sim_tick(self):
        sim = self.sim
        if not sim:
            return
        frac = min(1.0, (time.time() - sim["t0"]) / sim["dur"])
        sim["voc"] = sim["v0"] + (sim["v1"] - sim["v0"]) * frac
        v = self._sim_apply(force=True)
        left = int(sim["dur"] * (1 - frac))
        drop = sim["voc"] - v
        extra = f" (-{nlf(drop, 2)})" if sim["r"] > 0 and drop >= 0.005 else ""
        self.sim_lbl.config(text=tr("nu {0} V{1}, nog {2}:{3:02d}", nl(v), extra, left // 60, left % 60))
        if frac >= 1.0:
            self._stop_sim(tr("Klaar op {0} V", nl(v)))
            return
        self.after(1000, self._sim_tick)

    def _sim_apply(self, force=False):
        """Spanning van de nagebootste accu: bronspanning min stroom x inwendige weerstand (hooguit 4x per s)."""
        sim = self.sim
        v = round(max(0.0, min(self._limits()[0], sim["voc"] - (sim["i_f"] or 0.0) * sim["r"])), 2)
        now = time.time()
        if v != sim["last"] and (force or now - sim["t_send"] >= 0.25):
            self.cmdq.put(f"VSET1:{v:.2f}")
            sim["last"], sim["t_send"] = v, now
        return v

    def _stop_sim(self, msg):
        if not self.sim:
            return
        self.sim = None
        self.sim_btn.config(text=tr("Start"), bg=PANEL_DARK)
        self.sim_lbl.config(text=msg)
        self._add_marker(tr("accu-simulatie: {0}", msg[0].lower() + msg[1:]))

    # ---------- grafiek
    def _go_live(self):
        self.view = None
        self._draw_chart()

    def _data(self):
        return (self.src["pts"], self.src["markers"]) if self.src else (self.hist, self.markers)

    def _view_range(self):
        if self.view:
            return self.view
        if self.src:
            return self.src["pts"][0][0], self.src["pts"][-1][0]
        now = time.time()
        return now - self.span.get(), now

    @staticmethod
    def _trace(pts, X, Y, idx, pw):
        """Lijnpunten; bij veel metingen per pixel blijven pieken en dalen zichtbaar."""
        if len(pts) <= pw * 2:
            out = []
            for p in pts:
                out += [X(p[0]), Y(p[idx])]
            return out
        out, col, lo, hi = [], None, None, None
        for p in pts:
            c = int(X(p[0]))
            if c != col:
                if col is not None:
                    a, b = (lo, hi) if lo[0] <= hi[0] else (hi, lo)
                    out += [col, Y(a[1]), col, Y(b[1])]
                col, lo, hi = c, (p[0], p[idx]), (p[0], p[idx])
            else:
                if p[idx] < lo[1]:
                    lo = (p[0], p[idx])
                if p[idx] > hi[1]:
                    hi = (p[0], p[idx])
        a, b = (lo, hi) if lo[0] <= hi[0] else (hi, lo)
        out += [col, Y(a[1]), col, Y(b[1])]
        return out

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        self._cmap = None
        w, h = c.winfo_width(), c.winfo_height()
        if w < px(100) or h < px(80):
            return
        L, Rm, T, B = px(52), px(60), px(50), px(28)
        pw, ph = w - L - Rm, h - T - B
        t0, t1 = self._view_range()
        live = self.view is None and self.src is None
        dur = max(t1 - t0, 1e-6)
        data, marks = self._data()
        pts = in_window(data, t0, t1)

        vmax = nice_ceil(max([p[1] for p in pts] + [(self.vset or 0) if live else 0, 0.1]) * 1.1)
        band = self._afdruk_band_nu(t0, t1) if self.src is None else None
        imax = nice_ceil(max([p[2] for p in pts] + [0.005] + ([max(band[2])] if band else [])) * 1.2)

        def X(t):
            return L + pw * (t - t0) / dur

        def Yv(v):
            return T + ph * (1 - min(v / vmax, 1))

        def Yi(i):
            return T + ph * (1 - min(i / imax, 1))

        # stappen van een testprogramma als rustige banden: groen goed, rood fout
        for nr, b in enumerate(ana.stap_banden(marks, t1)):
            xa, xb = max(X(b["t0"]), L), min(X(b["t1"]), L + pw)
            if xb - xa < 1:
                continue
            kl = {"goed": blend(GLASS, LED_GREEN, 0.13), "fout": blend(GLASS, LED_RED, 0.17)}.get(
                b["uitslag"], blend(GLASS, TEXT, 0.035 if nr % 2 else 0.07))
            c.create_rectangle(xa, T, xb, T + ph, fill=kl, outline="")
            if xb - xa > px(46):
                c.create_text((xa + xb) / 2, T + ph - px(9), text=tr("stap {0}", b['nr']), fill=DIM, font=(FONT, 8))
        if band:     # stroomafdruk: de band waar een goed bordje in hoort te blijven
            t_aan, laag, hoog, ok, stap = band
            boven, onder = [], []
            for k, (lo, hi) in enumerate(zip(laag, hoog)):
                t_k = t_aan + k * stap
                if t0 <= t_k <= t1:
                    boven += [X(t_k), Yi(hi)]
                    onder = [X(t_k), Yi(lo)] + onder
            if len(boven) >= 4:
                c.create_polygon(*boven, *onder, fill=blend(GLASS, LED_AMBER if ok else LED_RED, 0.22), outline="")

        for k in range(6):
            y = T + ph * k / 5
            c.create_line(L, y, L + pw, y, fill=GRID)
            c.create_text(L - px(8), y, text=nl(vmax * (1 - k / 5)), fill=LED_RED, anchor="e", font=(FONT, 9))
            c.create_text(L + pw + px(8), y, text=nl(imax * (1 - k / 5)), fill=LED_AMBER, anchor="w", font=(FONT, 9))
        for k in range(7):
            x = L + pw * k / 6
            c.create_line(x, T, x, T + ph, fill=GRID)
            if live:
                secs = dur * (1 - k / 6)
                label = f"-{fmt_span(secs)}" if k < 6 else tr("nu")
            else:
                label = datetime.fromtimestamp(t0 + dur * k / 6).strftime("%H:%M:%S")
            c.create_text(x, T + ph + px(15), text=label, fill=MUTED, font=(FONT, 9))
        c.create_text(L - px(8), px(12), text="V", fill=LED_RED, anchor="e", font=(FONT, 10, "bold"))
        c.create_text(L + pw + px(8), px(12), text="A", fill=LED_AMBER, anchor="w", font=(FONT, 10, "bold"))
        back = tr("het hele log") if self.src else tr("live")
        if live:
            banner, col, wt = tr("Sleep of scroll in de grafiek om in te zoomen"), MUTED, "normal"
            title = tr("Stroom in beeld ({0})", fmt_span(self.span.get()))
        elif self.view is None:
            banner = (tr("Log {0}, {1}. Sleep of scroll om in te zoomen.", self.src['name'], nl_date(t0)))
            col, wt, title = LED_AMBER, "bold", tr("Stroom in log")
        else:
            banner = (tr("Ingezoomd op {0:%H:%M:%S} tot {1:%H:%M:%S}. Dubbelklik om terug te gaan naar {2}.", datetime.fromtimestamp(t0), datetime.fromtimestamp(t1), back))
            col, wt, title = LED_AMBER, "bold", tr("Stroom in selectie")
        c.create_text(L + pw / 2, px(12), fill=col, font=(FONT, 10 if wt == "bold" else 9, wt), text=banner)

        self._show_stats(pts, title)
        self._teken_vlaggen(c, [(mt, tx) for mt, tx in marks if t0 <= mt <= t1], X, T, ph, L, pw)

        if len(pts) < 2:
            if not live:
                msg = tr("Geen metingen in deze selectie.")
            else:
                msg = (tr("Wachten op metingen...") if self.dev else
                       tr("Kies de COM-poort van de voeding en klik op Verbinden."))
            c.create_text(L + pw / 2, T + ph / 2, text=msg, fill=MUTED, font=(FONT, 12))
            return

        il = self._trace(pts, X, Yi, 2, pw)
        vl = self._trace(pts, X, Yv, 1, pw)
        c.create_line(*il, fill=LED_AMBER, width=px(2))
        c.create_line(*vl, fill=LED_RED, width=px(2))
        self._cmap = (L, T, pw, ph, t0, dur, vmax, imax, pts, [p[0] for p in pts])

        if live:   # actuele waarde aan het eind van elke lijn
            _, v_now, i_now = pts[-1]
            top, bot = T + px(8), T + ph - px(8)
            ys = [min(max(vl[-1] - px(12), top), bot), min(max(il[-1] + px(12), top), bot)]
            if abs(ys[0] - ys[1]) < px(17):          # labels uit elkaar houden
                up, down = (0, 1) if ys[0] <= ys[1] else (1, 0)
                mid = (ys[0] + ys[1]) / 2
                ys[up], ys[down] = mid - px(9), mid + px(9)
                shift = max(0, ys[down] - bot) - max(0, top - ys[up])
                ys[up] -= shift
                ys[down] -= shift
            for (x, y), ty, txt, col in (((vl[-2], vl[-1]), ys[0], f"{nlf(v_now, 2)} V", LED_RED),
                                         ((il[-2], il[-1]), ys[1], f"{nlf(i_now, 3)} A", LED_AMBER)):
                c.create_oval(x - px(4), y - px(4), x + px(4), y + px(4), fill=col, outline=GLASS, width=px(2))
                label = c.create_text(x - px(10), ty, text=txt, fill=col, anchor="e", font=(FONT, 10, "bold"))
                x0, y0, x1, y1 = c.bbox(label)     # donker vlak eronder: de lijnen lopen niet door de cijfers
                c.tag_lower(c.create_rectangle(x0 - px(3), y0 - px(1), x1 + px(3), y1 + px(1), fill=GLASS, outline=""),
                            label)
        self._draw_overlay()

    def _draw_overlay(self):
        """Selectievak en meetcursor, boven op de grafiek."""
        c = self.chart
        c.delete("overlay")
        if self._vlag_tip():
            return
        if not self._cmap:
            return
        L, T, pw, ph, t0, dur, vmax, imax, pts, times = self._cmap
        if self._drag_x0 is not None and self._mouse_x is not None:
            xa, xb = sorted((self._drag_x0, self._mouse_x))
            xa, xb = max(xa, L), min(xb, L + pw)
            c.create_rectangle(xa, T, xb, T + ph, outline=LED_AMBER, dash=(3, 3), tags="overlay")
        x = self._mouse_x
        if x is None or not (L <= x <= L + pw):
            return
        t = t0 + dur * (x - L) / pw
        k = bisect_left(times, t)
        if k >= len(pts) or (k > 0 and t - times[k - 1] < times[k] - t):
            k -= 1
        pt, v, i = pts[k]
        cx = L + pw * (pt - t0) / dur
        yv = T + ph * (1 - min(v / vmax, 1))
        yi = T + ph * (1 - min(i / imax, 1))
        c.create_line(cx, T, cx, T + ph, fill=MUTED, tags="overlay")
        for y, col in ((yv, LED_RED), (yi, LED_AMBER)):
            c.create_oval(cx - px(5), y - px(5), cx + px(5), y + px(5), fill=col, outline=TEXT, width=px(2), tags="overlay")
        lines = [(datetime.fromtimestamp(pt).strftime("%H:%M:%S.") + f"{int(pt % 1 * 10)}", TEXT),
                 (dec(f"{v:.2f} V"), LED_RED),
                 (dec(f"{i * 1000:.1f} mA"), LED_AMBER),
                 (dec(f"{v * i:.2f} W"), LED_GREEN)]
        bw, bh = px(150), px(18 * len(lines) + 12)
        bx = cx + px(14) if cx + px(14) + bw < L + pw else cx - px(14) - bw
        by = T + px(10)
        c.create_rectangle(bx, by, bx + bw, by + bh, fill=CARD_2, outline=LINE, tags="overlay")
        for n, (txt, col) in enumerate(lines):
            c.create_text(bx + px(10), by + px(15 + 18 * n), text=txt, fill=col, anchor="w",
                          font=(FONT, 10, "bold" if n else "normal"), tags="overlay")

    def _on_motion(self, e):
        self._mouse_x, self._mouse_y = e.x, e.y
        self._draw_overlay()

    def _on_leave(self, e):
        self._mouse_x = self._mouse_y = None
        self.chart.delete("overlay")

    def _on_press(self, e):
        self._drag_x0 = e.x if self._cmap else None

    def _on_release(self, e):
        x0, self._drag_x0 = self._drag_x0, None
        self.chart.delete("overlay")
        if x0 is None or abs(e.x - x0) < px(6) or not self._cmap:
            self._draw_overlay()
            return
        L, T, pw, ph, t0, dur = self._cmap[:6]
        xa, xb = sorted((max(min(x0, L + pw), L), max(min(e.x, L + pw), L)))
        ta, tb = t0 + dur * (xa - L) / pw, t0 + dur * (xb - L) / pw
        if tb - ta >= 1:
            self.view = (ta, tb)
        self._draw_chart()

    def _on_wheel(self, e):
        if not self._cmap:
            return
        L, T, pw, ph, t0, dur = self._cmap[:6]
        x = min(max(e.x, L), L + pw)
        tc = t0 + dur * (x - L) / pw
        nd = max(2.0, dur * (0.8 if e.delta > 0 else 1.25))
        a = tc - (tc - t0) * nd / dur
        b = a + nd
        end = self.src["pts"][-1][0] if self.src else time.time()
        if b > end:
            a, b = a - (b - end), end
        self.view = (a, b)
        self._draw_chart()

    # ---------- oude logs bekijken
    def _open_log(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(title=tr("Log openen"), filetypes=[(tr("CSV-bestand"), "*.csv")])
        if not path:
            return
        try:
            pts, marks = read_log(path)
        except (OSError, KeyError, ValueError, TypeError):
            messagebox.showerror(tr("Kan log niet openen"),
                                 tr("Dit bestand is geen log van CurrentBench, of het is beschadigd."))
            return
        if len(pts) < 2:
            messagebox.showerror(tr("Te weinig metingen"), tr("Dit log bevat minder dan twee metingen."))
            return
        self.src = {"name": Path(path).name, "pts": pts, "markers": marks}
        self.view = None
        self.live_btn.pack(side="left", padx=4)
        self._draw_chart()

    def _back_to_live(self):
        self.src = None
        self.view = None
        self.live_btn.pack_forget()
        self._draw_chart()

    # ---------- testrapport
    def _report_dialog(self):
        t0, t1 = self._view_range()
        data, _ = self._data()
        if sum(1 for p in data if t0 <= p[0] <= t1) < 2:
            messagebox.showinfo(tr("Geen metingen"), tr("Er staan nog geen metingen in de grafiek om een rapport van "
                                                    "te maken."))
            return
        if getattr(self, "_rwin", None) and self._rwin.winfo_exists():
            self._rwin.lift()
            return
        win = tk.Toplevel(self)
        self.after(10, lambda w=win: self._center(w))
        self._rwin = win
        win.title(tr("Testrapport maken"))
        win.configure(bg=PANEL)
        win.transient(self)
        win.resizable(False, False)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        self._kop(win, tr("Testrapport maken")).pack(
            anchor="w", padx=16, pady=(14, 2))
        tk.Label(win, bg=PANEL, fg=INK, font=(FONT, 10), justify="left", wraplength=px(520),
                 text=tr("Het rapport beschrijft wat nu in de grafiek staat: {0:%H:%M:%S} tot {1:%H:%M:%S}. Zoom "
                         "eerst in als je alleen een deel wilt.", datetime.fromtimestamp(t0), datetime.fromtimestamp(t1))).pack(anchor="w", padx=16, pady=(0, 12))
        tk.Label(win, text=tr("Titel"), bg=PANEL, fg=INK, font=(FONT, 11)).pack(anchor="w", padx=16)
        title_e = tk.Entry(win, width=52, font=(FONT, 12), relief="flat",
                           highlightthickness=1, highlightbackground=PANEL_DARK)
        title_e.insert(0, self.src["name"].rsplit(".", 1)[0] if self.src else tr("Testrapport"))
        title_e.pack(anchor="w", padx=16, pady=(2, 10))
        tk.Label(win, text=tr("Opmerking (optioneel)"), bg=PANEL, fg=INK, font=(FONT, 11)).pack(anchor="w", padx=16)
        note = tk.Text(win, width=58, height=5, font=(FONT, 11), relief="flat", wrap="word",
                       highlightthickness=1, highlightbackground=PANEL_DARK)
        note.pack(anchor="w", padx=16, pady=(2, 10))

        def make():
            title = title_e.get().strip() or tr("Testrapport")
            text = note.get("1.0", "end").strip()
            win.destroy()
            self._make_report(title, text, t0, t1)

        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=16, pady=(4, 14))
        self._btn(bar, tr("Rapport maken"), make, bg=BTN_GREEN).pack(side="right")
        self._btn(bar, tr("Annuleren"), win.destroy).pack(side="right", padx=6)
        title_e.focus_set()
        title_e.select_range(0, "end")

    def _report_svg(self, pts, marks, t0, t1, genummerd=False):
        W, H, L, R, T, B = 1000, 380, 62, 70, 26, 40
        pw, ph = W - L - R, H - T - B
        dur = max(t1 - t0, 1e-6)
        vmax = nice_ceil(max(p[1] for p in pts) * 1.1 or 0.1)
        imax = nice_ceil(max(max(p[2] for p in pts) * 1.2, 0.005))

        def X(t):
            return L + pw * (t - t0) / dur

        def Yv(v):
            return T + ph * (1 - min(v / vmax, 1))

        def Yi(i):
            return T + ph * (1 - min(i / imax, 1))

        out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
               f'aria-label="Spanning en stroom over tijd">',
               f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="#F3EEDF"/>']
        for k in range(6):
            y = T + ph * k / 5
            out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="#DDD5C1"/>')
            out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end" class="v">{nl(vmax * (1 - k / 5))}</text>')
            out.append(f'<text x="{L + pw + 8}" y="{y + 4:.1f}" class="a">{nl(imax * 1000 * (1 - k / 5))}</text>')
        for k in range(7):
            x = L + pw * k / 6
            out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T + ph}" stroke="#DDD5C1"/>')
            out.append(f'<text x="{x:.1f}" y="{T + ph + 22}" text-anchor="middle" class="t">'
                       f'{datetime.fromtimestamp(t0 + dur * k / 6):%H:%M:%S}</text>')
        out.append(f'<text x="{L - 8}" y="{T - 10}" text-anchor="end" class="v b">V</text>')
        out.append(f'<text x="{L + pw + 8}" y="{T - 10}" class="a b">mA</text>')
        if genummerd:     # zelfde nummers als de tabel Markeringen onder de grafiek
            for v in ana.vlaggen(marks, X, 6.2, 12, 3):
                for _nr, mt, _tx in v["items"]:
                    out.append(f'<line x1="{X(mt):.1f}" y1="{T}" x2="{X(mt):.1f}" y2="{T + ph}" stroke="#8A8F98" '
                               f'stroke-dasharray="3 4"/>')
                kl = {"fout": "#D9301F", "alarm": "#D9301F", "goed": "#2E7D3A"}.get(v["soort"], "#6E6A60")
                out.append(f'<rect x="{v["x0"]:.1f}" y="{T + 3}" width="{v["w"]:.1f}" height="15" rx="4" fill="#FBF8F1" '
                           f'stroke="{kl}"/>')
                out.append(f'<text x="{v["x0"] + v["w"] / 2:.1f}" y="{T + 14}" text-anchor="middle" class="m" '
                           f'style="fill:{kl}">{v["label"]}</text>')
        else:
            lanes = []
            for mt, txt in marks:
                x = X(mt)
                out.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T + ph}" stroke="#8A8F98" '
                           f'stroke-dasharray="3 4"/>')
                right = x > L + pw - 170
                tw = 6.2 * len(txt) + 10
                span_ = (x - tw, x) if right else (x, x + tw)
                lane = next((k for k, e in enumerate(lanes) if span_[0] > e), len(lanes))
                if lane == len(lanes):
                    lanes.append(0)
                lanes[lane] = span_[1]
                if lane < 6:
                    out.append(f'<text x="{x - 4 if right else x + 4:.1f}" y="{T + 14 + 14 * lane}" '
                               f'text-anchor="{"end" if right else "start"}" class="m">{html.escape(txt)}</text>')
        for idx, Y, col in ((2, Yi, "#C98400"), (1, Yv, "#D9301F")):
            flat = self._trace(pts, X, Y, idx, pw)
            pairs = " ".join(f"{flat[k]:.1f},{flat[k + 1]:.1f}" for k in range(0, len(flat), 2))
            out.append(f'<polyline points="{pairs}" fill="none" stroke="{col}" stroke-width="2" '
                       f'stroke-linejoin="round"/>')
        out.append("</svg>")
        return "\n".join(out)

    def _make_report(self, title, note, t0, t1, path=None, open_browser=True, wb_kind="rapport"):
        data, allmarks = self._data()
        pts = [p for p in data if t0 <= p[0] <= t1]
        marks = sorted(((t, x) for t, x in allmarks if t0 <= t <= t1), key=lambda m: m[0])
        if len(pts) < 2:
            messagebox.showinfo(tr("Geen metingen"), tr("Er zijn te weinig metingen in dit stuk."))
            return
        ta, tb = pts[0][0], pts[-1][0]
        vs, cs = [p[1] for p in pts], [p[2] for p in pts]
        ws = [p[1] * p[2] for p in pts]
        q = e = 0.0
        for a, b in zip(pts, pts[1:]):
            dt = b[0] - a[0]
            if 0 < dt < 2:
                q += dt * (a[2] + b[2]) / 2
                e += dt * (a[1] * a[2] + b[1] * b[2]) / 2
        avg = lambda xs: sum(xs) / len(xs)

        if self.src:
            source = tr("Logbestand {0}", html.escape(self.src['name']))
        elif korad_paden.DEMO:
            source = html.escape(self.idn)
        else:
            source = tr("Live gemeten met {0}", html.escape(self.idn or self.settings["model"] or "Korad"))
        when = (tr("{0}, {1:%H:%M:%S} tot {2:%H:%M:%S}", nl_date(ta), datetime.fromtimestamp(ta), datetime.fromtimestamp(tb)))
        if nl_date(ta) != nl_date(tb):
            when = (tr("{0} {1:%H:%M:%S} tot {2} {3:%H:%M:%S}", nl_date(ta), datetime.fromtimestamp(ta), nl_date(tb), datetime.fromtimestamp(tb)))

        settings = []
        if not self.src and self.vset is not None:
            settings.append(tr("Ingesteld bij het maken van dit rapport: {0} V, stroomgrens {1} A.", nlf(self.vset, 2), nlf(self.iset or 0, 3)))
        if not self.src:
            settings.append(tr("Grens: {0}.", html.escape(PROJECTS[self.settings['project']]['naam'])))
        rules = [g for g in self.guards if g["aan"]]
        if rules and not self.src:
            settings.append(tr("Bewaking: ") + "; ".join(
                tr("{0} {1} {2} {3} langer dan {4} s, dan {5}", tr(g['wat']), tr(g['richting']), nl(g['waarde']), UNITS[g['wat']], nl(g['duur']), tr(g['actie'])) for g in rules) + ".")

        table = [(tr("Spanning"), f"{nlf(min(vs), 2)} V", f"{nlf(avg(vs), 2)} V", f"{nlf(max(vs), 2)} V"),
                 (tr("Stroom"), f"{nlf(min(cs) * 1000, 1)} mA", f"{nlf(avg(cs) * 1000, 1)} mA",
                  f"{nlf(max(cs) * 1000, 1)} mA"),
                 (tr("Vermogen"), f"{nlf(min(ws), 2)} W", f"{nlf(avg(ws), 2)} W", f"{nlf(max(ws), 2)} W")]
        rows = "".join(f"<tr><td>{name}</td><td>{lo}</td><td>{mid}</td><td>{hi}</td></tr>"
                       for name, lo, mid, hi in table)
        mrows = "".join(f"<tr><td>{nr}</td><td>{datetime.fromtimestamp(t):%H:%M:%S}</td><td>{html.escape(x)}</td></tr>"
                        for nr, (t, x) in enumerate(marks, start=1))
        marks_html = (tr("<h2>Markeringen</h2><table "
                         "class='marks'><tr><th>Nr</th><th>Tijd</th><th>Gebeurtenis</th></tr>{0}</table>", mrows)) if marks else ""
        note_html = (tr("<h2>Opmerking</h2><p class='note'>{0}</p>", html.escape(note))) if note else ""
        settings_html = "".join(f"<p class='meta'>{x}</p>" for x in settings)

        page = f"""<!DOCTYPE html>
<html lang="{korad_taal.huidig()}"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ margin: 0; background: #E6E0D2; color: #2B2A27;
         font-family: "Bahnschrift", "Segoe UI", sans-serif; }}
  .page {{ max-width: 1040px; margin: 32px auto; background: #FBF8F1; padding: 40px 52px 32px;
          border: 1px solid #CFC8B6; }}
  .kind {{ color: #7A7466; font-size: 15px; margin: 0; }}
  h1 {{ font-size: 34px; margin: 2px 0 6px; font-weight: 700; }}
  .meta {{ margin: 2px 0; color: #4A4740; font-size: 15px; }}
  .tiles {{ display: flex; gap: 12px; margin: 26px 0 22px; }}
  .tile {{ flex: 1; background: #1A1D22; border: 2px solid #4A4740; padding: 12px 16px; }}
  .tile span {{ display: block; color: #8A8F98; font-size: 13px; }}
  .tile b {{ display: block; font-size: 26px; margin-top: 2px; }}
  .chart {{ border: 1px solid #CFC8B6; background: #FBF8F1; padding: 8px 4px 0; }}
  svg {{ width: 100%; height: auto; font-family: inherit; font-size: 12px; }}
  svg .v {{ fill: #D9301F; }} svg .a {{ fill: #A86E00; }} svg .t {{ fill: #6E6A60; }}
  svg .m {{ fill: #4A4740; font-size: 11px; }} svg .b {{ font-weight: 700; }}
  .legend {{ font-size: 14px; margin: 8px 4px 10px; }}
  .legend i {{ display: inline-block; width: 22px; height: 3px; vertical-align: middle; margin: 0 6px 0 14px; }}
  h2 {{ font-size: 19px; margin: 28px 0 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 15px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #DDD5C1; }}
  th {{ color: #7A7466; font-weight: 600; font-size: 13px; }}
  .stats td:not(:first-child), .stats th:not(:first-child) {{ text-align: right; }}
  .marks td:first-child {{ width: 110px; font-variant-numeric: tabular-nums; }}
  .note {{ white-space: pre-wrap; font-size: 15px; line-height: 1.5; max-width: 75ch; }}
  .goed {{ color: #2E7D3A; font-weight: 700; }} .fout {{ color: #C62828; font-weight: 700; }}
  .legend .dash {{ margin-left: 18px; color: #6E6A60; }}
  .result {{ font-size: 15px; margin: 6px 0; }}
  footer {{ margin-top: 34px; padding-top: 12px; border-top: 1px solid #DDD5C1; color: #7A7466; font-size: 12.5px; }}
  @media print {{
    body {{ background: white; }}
    .page {{ margin: 0; border: none; padding: 0; max-width: none; }}
    .tile {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style></head>
<body><div class="page">
  <p class="kind">{tr("Testrapport")}</p>
  <h1>{html.escape(title)}</h1>
  <p class="meta">{source}</p>
  <p class="meta">{when}</p>
  {settings_html}
  <div class="tiles">
    <div class="tile"><span>{tr("Duur")}</span><b style="color:#E8E2D0">{fmt_duur(tb - ta)}</b></div>
    <div class="tile"><span>{tr("Lading")}</span><b style="color:#FFB000">{nlf(q / 3.6, 2)} mAh</b></div>
    <div class="tile"><span>{tr("Energie")}</span><b style="color:#3DBE5A">{nlf(e / 3600, 3)} Wh</b></div>
    <div class="tile"><span>{tr("Gemiddelde stroom")}</span><b style="color:#FFB000">{nlf(avg(cs) * 1000, 1)} mA</b></div>
  </div>
  <div class="chart">
    <div class="legend"><i style="background:#D9301F;margin-left:4px"></i>{tr("Spanning (V)")}
      <i style="background:#C98400"></i>{tr("Stroom (mA)")}</div>
    {self._report_svg(pts, marks, ta, tb, genummerd=True)}
  </div>
  <h2>{tr("Samenvatting")}</h2>
  <table class="stats"><tr><th></th><th>{tr("Laagste")}</th><th>{tr("Gemiddeld")}</th><th>{tr("Hoogste")}</th></tr>{rows}</table>
  {marks_html}
  {note_html}
  <footer>
    {tr("{0} metingen. De voeding wordt ongeveer vijf keer per seconde uitgelezen, dus zeer korte pieken van enkele milliseconden kunnen tussen twee metingen vallen. Lading en energie zijn berekend uit stroom en spanning over de tijd.", len(pts))}
    {tr("Gemaakt met CurrentBench op {0} om {1}.", nl_date(time.time()), f"{datetime.now():%H:%M}")}
  </footer>
</div></body></html>
"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        if path is None:
            path = filedialog.asksaveasfilename(
                title=tr("Rapport opslaan als"), initialdir=str(REPORT_DIR), defaultextension=".html",
                initialfile=f"rapport_{datetime.fromtimestamp(ta):%Y%m%d_%H%M}.html",
                filetypes=[(tr("HTML-rapport"), "*.html")])
            if not path:
                return None
        try:
            Path(path).write_text(page, encoding="utf-8")
        except OSError as err:
            messagebox.showerror(tr("Kan rapport niet opslaan"), str(err))
            return None
        self._wb_add(wb_kind, title, path, about=note)
        if open_browser:
            webbrowser.open(Path(path).resolve().as_uri())
        return Path(path)

    # ---------- meldingen (ntfy)
    def _notify(self, title, message, priority=3, tags=()):
        st = self.settings
        if st["ntfy_aan"] and st["ntfy_topic"].strip():
            ntfy_send(st["ntfy_server"] or "https://ntfy.sh", st["ntfy_topic"].strip(), tr("CurrentBench: {0}", title),
                      message, priority, tags)

    # ---------- venster instellingen
    def _toplevel(self, attr, title):
        old = getattr(self, attr, None)
        if old is not None and old.winfo_exists():
            old.lift()
            return None
        win = tk.Toplevel(self)
        self.after(10, lambda w=win: self._center(w))
        setattr(self, attr, win)
        win.title(title)
        win.configure(bg=PANEL)
        win.transient(self)
        win.resizable(False, False)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        return win

    def _open_settings(self):
        win = self._toplevel("_swin", tr("Instellingen"))
        if not win:
            return
        kop_ = tk.Frame(win, bg=PANEL)
        kop_.grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 2))
        self._kop(kop_, tr("Instellingen")).pack(anchor="w")
        taalrij = tk.Frame(kop_, bg=PANEL)
        taalrij.pack(anchor="w", pady=(10, 0))
        tk.Label(taalrij, text="Taal / Language / Sprache", bg=PANEL, fg=INK, font=(FONT, 11)).pack(side="left")
        self._taal_box = taal_box = ttk.Combobox(taalrij, values=list(korad_taal.TALEN.values()), width=14,
                                                 state="readonly")
        taal_box.set(korad_taal.TALEN[korad_taal.huidig()])
        taal_box.pack(side="left", padx=(10, 0))
        tk.Label(taalrij, text=tr("Weergave"), bg=PANEL, fg=INK, font=(FONT, 11)).pack(side="left", padx=(22, 0))
        self._thema_box = thema_box = Keuze(taalrij, ["donker", "licht"], width=10, state="readonly")
        thema_box.set(THEMA)
        thema_box.pack(side="left", padx=(10, 0))
        self._caption(kop_, tr("Meldingen op je telefoon (ntfy)"), bg=PANEL).pack(anchor="w", pady=(12, 0))
        tk.Label(win, bg=PANEL, fg=INK, font=(FONT, 10), wraplength=px(560), justify="left",
                 text=tr("Het paneel stuurt een melding bij een alarm of grensoverschrijding, als een "
                         "testprogramma klaar is, en als de voeding onbereikbaar wordt terwijl de uitgang aan "
                         "staat. Installeer de app ntfy en abonneer je op hetzelfde onderwerp.\n\nHet onderwerp "
                         "werkt als een wachtwoord: wie het kent, leest mee. Kies een lange naam die niet te "
                         "raden is. Hij staat alleen in korad_instellingen.json op deze computer.")).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))
        entries = {}
        for r, (key, txt) in enumerate((("ntfy_server", tr("Server")), ("ntfy_topic", tr("Onderwerp"))), start=2):
            tk.Label(win, text=txt, bg=PANEL, fg=INK, font=(FONT, 11)).grid(row=r, column=0, sticky="w", padx=16)
            e = tk.Entry(win, width=40, font=(FONT, 11), relief="flat", highlightthickness=1,
                         highlightbackground=PANEL_DARK)
            e.insert(0, self.settings[key])
            e.grid(row=r, column=1, columnspan=2, sticky="w", padx=(6, 16), pady=3)
            entries[key] = e
        on_var = tk.BooleanVar(value=self.settings["ntfy_aan"])
        self._check(win, tr("Meldingen sturen"), on_var, size=11).grid(row=4, column=1, sticky="w", padx=6, pady=(4, 0))
        win.grid_columnconfigure(2, weight=1)      # extra breedte van de lange uitleg naar rechts, niet naar de labels
        status = tk.Label(win, text="", bg=PANEL, fg=INK, font=(FONT, 10), wraplength=px(560), justify="left")
        status.grid(row=5, column=0, columnspan=3, sticky="w", padx=16, pady=(8, 0))
        self._caption(win, tr("Geluid"), bg=PANEL).grid(row=6, column=0, columnspan=3, sticky="w", padx=16, pady=(16, 2))
        snd_var = tk.BooleanVar(value=self.settings.get("geluid_cc", True))
        self._check(win, tr("Pieptoon als de voeding gaat begrenzen (CC)"), snd_var, size=11).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=16)
        self._caption(win, tr("Gesproken meldingen"), bg=PANEL).grid(row=8, column=0, columnspan=3, sticky="w", padx=16,
                                                                 pady=(16, 2))
        spr_var = tk.BooleanVar(value=bool(self.settings.get("spraak_aan")))
        self._check(win, tr("Meldingen uitspreken in de taal van het paneel"), spr_var, size=11).grid(
            row=9, column=0, columnspan=3, sticky="w", padx=16)
        spr_lbl = tk.Label(win, text="", bg=PANEL, fg=MUTED, font=(FONT, 10), wraplength=px(560), justify="left")
        spr_lbl.grid(row=10, column=0, columnspan=3, sticky="w", padx=16, pady=(4, 0))
        self._caption(win, tr("Koppeling voor scripts"), bg=PANEL).grid(row=11, column=0, columnspan=3, sticky="w", padx=16,
                                                                    pady=(16, 2))
        api_var = tk.BooleanVar(value=bool(self.settings.get("api_aan")))
        self._check(win, tr("Scripts mogen via het paneel meten (alleen op deze pc, poort {0})", self.settings['api_poort']),
                    api_var, size=11).grid(row=12, column=0, columnspan=3, sticky="w", padx=16)
        api_fout = getattr(self, "_api_fout", "")
        tk.Label(win, bg=PANEL, fg=BAD if api_fout else MUTED, font=(FONT, 10), wraplength=px(560), justify="left",
                 text=(tr("De koppeling start niet: {0}", api_fout) if api_fout else
                       tr("Binnen dezelfde grenzen als de knoppen. Uitgang aanzetten of de spanning verhogen kan "
                          "alleen met een expliciet akkoord in de opdracht."))).grid(
            row=13, column=0, columnspan=3, sticky="w", padx=16, pady=(4, 0))
        spk = self._speech_ensure(reprobe=True)

        def spr_show():
            try:
                if not spr_lbl.winfo_exists():
                    return
            except tk.TclError:
                return
            if spk.state == "start":
                spr_lbl.config(text=tr("Zoeken naar een stem in de taal van het paneel..."), fg=MUTED)
                win.after(300, spr_show)
            elif spk.state == "ok":
                spr_lbl.config(fg=INK, text=tr("Stem: {0}. Het paneel spreekt bij de stroomgrens, een noodstop "
                                               "of alarm, en bij de uitslag van een onderdeel, opstartcurve of "
                                               "testprogramma. De nachttest blijft stil.", spk.voice))
                hear.config(state="normal")
            elif spk.state == "geen_stem":
                spr_lbl.config(fg=LED_AMBER, text=tr("Er staat nog geen stem in de taal van het paneel op deze "
                                                     "computer. Toevoegen (gratis, eenmalig): Instellingen van "
                                                     "Windows > Tijd en taal > Spraak > Stemmen beheren: Stemmen "
                                                     "toevoegen. Open daarna dit venster opnieuw."))
            else:
                spr_lbl.config(fg=BAD, text=tr("De spraak van Windows werkt hier niet: {0}", spk.voice[:120]))

        def collect():
            return {"ntfy_server": entries["ntfy_server"].get().strip() or "https://ntfy.sh",
                    "ntfy_topic": entries["ntfy_topic"].get().strip(), "ntfy_aan": on_var.get(),
                    "geluid_cc": snd_var.get(), "spraak_aan": spr_var.get(), "api_aan": api_var.get(),
                    "taal": list(korad_taal.TALEN)[taal_box.current()], "thema": thema_box.get()}

        def show(ok, err):
            try:
                status.config(text=tr("Testmelding verstuurd. Komt hij niet binnen, controleer dan het onderwerp "
                                      "in de app.") if ok else tr("Versturen mislukt: {0}", err), fg=GOOD if ok else BAD)
            except tk.TclError:
                pass

        def test():
            st = collect()
            if not st["ntfy_topic"]:
                status.config(text=tr("Vul eerst een onderwerp in."), fg=BAD)
                return
            status.config(text=tr("Versturen..."), fg=INK)
            ntfy_send(st["ntfy_server"], st["ntfy_topic"], tr("CurrentBench: testmelding"),
                      tr("CurrentBench kan je bereiken."), 3, ("white_check_mark",),
                      done=lambda ok, err: self.inq.put(("call", lambda: show(ok, err))))

        def save():
            st = collect()
            if st["ntfy_aan"] and not st["ntfy_topic"]:
                status.config(text=tr("Zonder onderwerp kan het paneel geen meldingen sturen."), fg=BAD)
                return
            self.settings.update(st)
            save_settings(self.settings)
            if st["api_aan"]:
                self._api_start()
            else:
                self._api_stop()
            win.destroy()
            if st["taal"] != korad_taal.huidig() or st["thema"] != THEMA:
                self._herstart_na_keuze()

        bar = tk.Frame(win, bg=PANEL)
        bar.grid(row=14, column=0, columnspan=3, sticky="ew", padx=16, pady=14)
        self._btn(bar, tr("Testmelding sturen"), test).pack(side="left")
        hear = self._btn(bar, tr("Laat horen"), lambda: spk.say(spoken(tr("Dit is CurrentBench. Stroom begrensd "
                                                                      "bij 1,5 A."))))
        hear.config(state="disabled")
        hear.pack(side="left", padx=(8, 0))
        self._btn(bar, tr("Gegevensmap openen"), self._open_gegevensmap).pack(side="left", padx=(8, 0))
        spr_show()
        self._btn(bar, tr("Annuleren"), win.destroy).pack(side="right", padx=(8, 0))
        self._btn(bar, tr("Opslaan"), save, bg=BTN_GREEN).pack(side="right")

    def _open_handleiding(self):
        try:
            os.startfile(str(korad_paden.bron(f"docs/handleiding/handleiding-{korad_taal.huidig()}.pdf")))
        except OSError as err:
            messagebox.showerror(tr("Kan niet openen"), str(err))

    def _open_over(self):
        win = tk.Toplevel(self, bg=PANEL)
        win.title(tr("Over dit programma"))
        win.transient(self)
        try:
            win.iconbitmap(str(korad_paden.bron("korad.ico")))
        except tk.TclError:
            pass
        tk.Label(win, text=NAAM, bg=PANEL, fg=TEXT, font=(FONT_NUM, 18)).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(win, text=tr("Voor Korad-voedingen"), bg=PANEL, fg=TEXT).pack(anchor="w", padx=20)
        tk.Label(win, text=tr("Versie {0}", VERSIE), bg=PANEL, fg=MUTED).pack(anchor="w", padx=20)
        tk.Label(win, text=tr("Idee en opdracht van {0}. De code is geschreven door Claude (Anthropic).", MAKER), bg=PANEL, fg=TEXT, font=(FONT_NUM, 12), wraplength=px(420),
                 justify="left").pack(anchor="w", padx=20, pady=(12, 2))
        site = tk.Label(win, text=WEBSITE, bg=PANEL, fg=BLUE, font=(FONT_NUM, 12, "underline"), cursor="hand2")
        site.pack(anchor="w", padx=20, pady=(0, 10))
        site.bind("<Button-1>", lambda e: webbrowser.open("https://" + WEBSITE))
        for tekst in (tr("Gratis hobbyproject zonder winstoogmerk, onder de MIT-licentie en zonder garantie. Niet officieel "
                         "en niet verbonden aan Korad."),
                      tr("Met dank aan: QR Code generator van Project Nayuki (MIT), pySerial (BSD), Pillow (MIT-CMU) en de "
                         "openbare modelgegevens van het sigrok-project.")):
            tk.Label(win, text=tekst, bg=PANEL, fg=MUTED, wraplength=px(420), justify="left").pack(anchor="w", padx=20, pady=(0, 8))
        self._btn(win, tr("Sluiten"), win.destroy).pack(anchor="e", padx=20, pady=(6, 16))

    def _open_welkom(self):
        """Venster bij de eerste start: in vier stappen aan de slag, en de taal kiezen."""
        win = self._toplevel("_welkomwin", tr("Welkom bij {0}", NAAM))
        if not win:
            return

        def gezien():
            if not self.settings.get("welkom_gezien"):
                self.settings["welkom_gezien"] = True
                save_settings(self.settings)
            win.destroy()

        def taal(code):
            if code == korad_taal.huidig():
                return
            self.settings["taal"] = code       # het venster komt na de herstart terug, in de gekozen taal
            save_settings(self.settings)
            self._herstart(korad_paden.DEMO)

        self._kop(win, tr("Welkom bij {0}", NAAM)).pack(anchor="w", padx=20, pady=(16, 4))
        breed = px(560)
        tk.Label(win, text=tr("{0} bedient en bewaakt je labvoeding vanaf de pc. In vier stappen aan de slag:", NAAM),
                 bg=PANEL, fg=INK, font=(FONT, 11), wraplength=breed, justify="left").pack(anchor="w", padx=20, pady=(0, 8))
        for nr, tekst in enumerate((
                tr("Sluit de voeding aan met de usb-kabel en zet hem aan."),
                tr("Kies rechtsboven de poort en klik op Verbinden."),
                tr("Stel eerst de stroomgrens in en dan de spanning. Zet daarna pas de uitgang aan."),
                tr("Kies of maak bovenin een project: dat is de hoogste spanning en stroom die het paneel toelaat "
                   "voor wat je aansluit.")), 1):
            rij = tk.Frame(win, bg=PANEL)
            rij.pack(anchor="w", padx=20, pady=3)
            tk.Label(rij, text=str(nr), bg=PANEL, fg=MUTED, font=(FONT, 11, "bold"), width=2, anchor="w").pack(
                side="left", anchor="n")
            tk.Label(rij, text=tekst, bg=PANEL, fg=INK, font=(FONT, 11), wraplength=breed - px(30),
                     justify="left").pack(side="left")
        tk.Label(win, text=tr("De stroomgrens op de voeding is de echte beveiliging. Dit programma helpt, maar "
                              "gebruik is op eigen risico."), bg=PANEL, fg=INK, font=(FONT, 11, "bold"),
                 wraplength=breed, justify="left").pack(anchor="w", padx=20, pady=(12, 4))
        tk.Label(win, text=tr("Dit venster vind je terug onder Gereedschap. De weergave (licht of donker) wijzig je "
                              "onder Instellingen."), bg=PANEL, fg=MUTED, font=(FONT, 10), wraplength=breed,
                 justify="left").pack(anchor="w", padx=20, pady=(0, 10))
        tk.Label(win, text=tr("Het paneel begint eenvoudig. Met de knop Uitgebreid, rechts naast de geheugenknoppen, "
                              "komen de extra functies in beeld."), bg=PANEL, fg=MUTED, font=(FONT, 10),
                 wraplength=breed, justify="left").pack(anchor="w", padx=20, pady=(0, 10))
        talen = tk.Frame(win, bg=PANEL)
        talen.pack(anchor="w", padx=20, pady=(0, 4))
        tk.Label(talen, text="Taal / Language / Sprache", bg=PANEL, fg=INK, font=(FONT, 11)).pack(side="left", padx=(0, 8))
        for code, naam in korad_taal.TALEN.items():
            self._btn(talen, naam, lambda c=code: taal(c), bg=BLUE if code == korad_taal.huidig() else PANEL_DARK).pack(
                side="left", padx=(0, 6))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=20, pady=(12, 16))
        self._btn(bar, tr("Handleiding"), self._open_handleiding).pack(side="left")
        self._btn(bar, tr("Aan de slag"), gezien, bg=BTN_GREEN).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", gezien)

    def _foutinfo_tekst(self):
        """Alles wat nodig is om een fout te melden, zonder iets persoonlijks: geen codes, onderwerpen, adressen,
        serienummers, projectnamen of de naam van de gebruiker. De kopjes zijn bewust Engels: wie de melding leest
        hoeft de taal van de gebruiker niet te kennen."""
        import platform
        thuis = str(Path.home())

        def anoniem(tekst):
            tekst = re.sub(r"SN:\s*\S+", "SN:(hidden)", tekst)
            return tekst.replace(thuis, "~").replace(thuis.replace("\\", "/"), "~")

        st = self.settings
        vmax, imax = self._limits()
        loopt = [naam for naam, attr in (("test program", "run"), ("battery simulation", "sim"), ("startup curve", "curve"),
                                         ("overnight test", "night"), ("component tester", "part"))
                 if getattr(self, attr, None)]
        regels = [
            f"{NAAM} {VERSIE}" + (" (exe)" if korad_paden.BEVROREN else " (python)") + (" DEMO" if korad_paden.DEMO else ""),
            f"Date: {datetime.now():%Y-%m-%d %H:%M}",
            f"System: {platform.platform()}",
            f"Python: {platform.python_version()}, Tk {self.tk.call('info', 'patchlevel')}, pyserial {getattr(serial, '__version__', '?')}",
            f"Language: {korad_taal.huidig()}, theme: {THEMA}, scaling: {px(100) / 100:.2f}",
            f"Supply: {anoniem(self.idn) if self.idn else '(not connected)'}",
            f"Model setting: {st.get('model') or '(auto)'}, range {nl(MAX_V)} V / {nl(MAX_A)} A",
            f"Connected: {bool(self.dev)}, output: {self.out}, set: {self.vset} V / {self.iset} A",
            f"Project limit: {nl(vmax)} V / {nl(imax)} A" + (" (own project)" if st.get("project") != "vrij" else " (Free)"),
            f"Running: {', '.join(loopt) or 'nothing'}",
            "Options: " + ", ".join(f"{k}={bool(st.get(k))}" for k in ("api_aan", "web_aan", "ntfy_aan", "spraak_aan", "geluid_cc")),
            f"Alarm: {anoniem(self.alarm) if getattr(self, 'alarm', '') else 'none'}",
            "", "--- last errors (korad_fouten.log) ---"]
        try:
            log = ERROR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
            regels += [anoniem(r) for r in log] or ["(empty)"]
        except OSError:
            regels.append("(no error log)")
        return "\n".join(regels)

    def _open_foutinfo(self):
        win = self._toplevel("_fiwin", tr("Foutinformatie"))
        if not win:
            return
        self._kop(win, tr("Foutinformatie")).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(win, bg=PANEL, fg=INK, font=(FONT, 11), wraplength=px(640), justify="left",
                 text=tr("Ging er iets mis? Stuur deze tekst mee met je melding. Er staan geen codes, adressen, "
                         "serienummers of projectnamen in. Lees hem gerust eerst door.")).pack(anchor="w", padx=20, pady=(0, 8))
        tekst = self._foutinfo_tekst()
        vak = tk.Frame(win, bg=PANEL)
        vak.pack(fill="both", expand=True, padx=20)
        txt = tk.Text(vak, width=92, height=22, wrap="none", bg=CARD, fg=INK, font=("Consolas", 9), relief="flat",
                      highlightthickness=1, highlightbackground=LINE)
        rol = ttk.Scrollbar(vak, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=rol.set)
        txt.pack(side="left", fill="both", expand=True)
        rol.pack(side="left", fill="y")
        txt.insert("1.0", tekst)
        txt.config(state="disabled")
        bar = tk.Frame(win, bg=PANEL)
        stand = tk.Label(bar, text="", bg=PANEL, fg=GOOD, font=(FONT, 10))

        def kopieer():
            self.clipboard_clear()
            self.clipboard_append(tekst)
            stand.config(text=tr("Gekopieerd. Plak de tekst in je melding."), fg=GOOD)

        def bewaar():
            pad = filedialog.asksaveasfilename(parent=win, title=tr("Foutinformatie opslaan"), defaultextension=".txt",
                                               initialfile=f"currentbench_info_{datetime.now():%Y%m%d_%H%M}.txt",
                                               filetypes=[(tr("Tekstbestand"), "*.txt")])
            if not pad:
                return
            try:
                Path(pad).write_text(tekst, encoding="utf-8")
                stand.config(text=tr("Opgeslagen als {0}.", Path(pad).name), fg=GOOD)
            except OSError as err:
                stand.config(text=tr("Niet opgeslagen: {0}", err), fg=BAD)

        bar.pack(fill="x", padx=20, pady=(10, 16))
        def meld(adres):
            self.clipboard_clear()
            self.clipboard_append(tekst)
            stand.config(text=tr("Gekopieerd. Plak de tekst in het formulier dat nu opent."), fg=GOOD)
            webbrowser.open(adres)

        if MELD_GITHUB:
            self._btn(bar, tr("Melden op GitHub"), lambda: meld(MELD_GITHUB), bg=BLUE).pack(side="left", padx=(0, 6))
        if MELD_WEBSITE:
            self._btn(bar, tr("Melden via de website"), lambda: meld(MELD_WEBSITE)).pack(side="left", padx=(0, 6))
        self._btn(bar, tr("Kopiëren"), kopieer, bg=PANEL_DARK if MELD_GITHUB else BLUE).pack(side="left")
        self._btn(bar, tr("Opslaan als"), bewaar).pack(side="left", padx=6)
        stand.pack(side="left", padx=8)
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")

    def _open_gegevensmap(self):
        try:
            os.startfile(str(korad_paden.DATA))
        except OSError as err:
            messagebox.showerror(tr("Kan de map niet openen"), str(err))

    def _herstart_na_keuze(self):
        """Teksten en kleuren worden bij het starten opgebouwd: een andere taal of weergave vraagt om een nieuwe start."""
        if messagebox.askyesno(tr("Instellingen"), tr("Dit gaat in bij de volgende start. Het paneel nu opnieuw "
                                                      "starten?")):
            self._herstart(korad_paden.DEMO)

    def _start_demo(self):
        if messagebox.askyesno(tr("Demo"), tr("De demo start het paneel opnieuw met een nagebootste voeding. Er is geen "
                                              "voeding nodig en je eigen projecten en metingen blijven apart.\n\n"
                                              "Demo starten?")):
            self._herstart(True)

    def _herstart(self, demo):
        self._on_close()
        if not self.running:      # niet als er bij het sluiten op Annuleren is geklikt
            subprocess.Popen(korad_paden.herstart_opdracht(demo), cwd=str(korad_paden.PROGRAMMA))

    # ---------- lopende metingen stoppen (opstartcurve, onderdeel)
    def _stop_new(self, msg):
        self._curve_stop(msg)
        self._part_stop(msg)

    # ---------- geluid en noodstop
    def _beep(self, kind):
        if kind == "cc" and not self.settings.get("geluid_cc", True):
            return
        seq = {"cc": ((1100, 90), (1100, 90)), "noodstop": ((520, 220), (390, 320)), "alarm": ((880, 160),)}[kind]

        def run():
            try:
                import winsound
                for f, d in seq:
                    winsound.Beep(f, d)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _safe_write(dev, cmd):
        try:
            dev.write(cmd)
        except Exception:
            pass

    def _emergency_stop(self, source="Esc"):
        """Noodstop: uitgang direct uit (eigen thread, niet achter de wachtrij) en alles stoppen wat loopt."""
        if not self.dev:
            return
        dev = self.dev
        threading.Thread(target=self._safe_write, args=(dev, "OUT0"), daemon=True).start()
        self.cmdq.put("OUT0")
        msg = tr("Gestopt: noodstop ({0})", source)
        for stop in (lambda: self._stop_program(msg), lambda: self._stop_sim(msg),
                     lambda: self._stop_new(msg), lambda: self._night_stop(tr("gestopt: noodstop ({0})", source))):
            try:
                stop()
            except Exception:
                pass
        t = time.time()
        self.alarm = tr("{0:%H:%M:%S}  Noodstop ({1}): uitgang uitgezet.", datetime.fromtimestamp(t), source)
        self.alarm_lbl.config(text=tr("Alarm om {0}", self.alarm[:8]))
        self.alarm_btn.pack(anchor="w", padx=14, pady=(4, 10))
        self._update_guard_lamp()
        self._add_marker(tr("NOODSTOP ({0}): uitgang uit", source))
        self._beep("noodstop")
        self._say(tr("Noodstop. Uitgang uit."))

    # ---------- opstartcurve
    def _curve_start(self, v_end, i_lim, step_v=0.2, dwell=0.5, hold=0.0, done=None, label="opstartcurve"):
        """Zachte start: uitgang uit, stroomgrens zetten, op 0 V aan en de spanning in stapjes laten oplopen terwijl
        de stroom wordt gemeten. Bij de stroomgrens gaat de uitgang uit."""
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."))
            return False
        vmax, imax = self._limits()
        if not (0.5 <= v_end <= vmax + 1e-6 and 0.001 <= i_lim <= imax + 1e-6):
            messagebox.showerror(tr("Buiten de grens"), self._limit_text())
            return False
        msg = tr("Gestopt: {0} gestart", label)
        self._stop_program(msg)
        self._stop_sim(msg)
        self._part_stop(msg)
        self._curve_stop(tr("Gestopt: nieuwe meting"))
        now = time.time()
        self.curve = {"id": now, "t0": now, "label": label, "v_end": round(v_end, 2), "i_lim": i_lim,
                      "step": step_v, "dwell": dwell, "hold": hold, "v": 0.0, "pts": [], "cc_at": None,
                      "ccs": [], "done": done, "t_step": now + 0.8, "phase": "ramp", "i_end": None, "i_max": None}
        for cmd in ("OUT0", f"ISET1:{i_lim:.3f}", "VSET1:0.00", "OUT1"):
            self.cmdq.put(cmd)
        self._add_marker(tr("{0}: start, 0 tot {1} V, grens {2}", label, nl(v_end), fmt_ma(i_lim)))
        self.after(int((0.8 + dwell) * 1000), lambda: self._curve_tick(now))
        self._curve_refresh()
        return True

    def _curve_cc(self, t0, t1):
        """Aantal metingen met CC (stroom begrensd) tussen t0 en t1."""
        return sum(1 for t, cc in (self.curve or {}).get("ccs", []) if t0 <= t <= t1 and cc)

    def _curve_tick(self, cid):
        c = self.curve
        if not c or c["id"] != cid:
            return
        now = time.time()
        if c["phase"] == "ramp":
            ta = c["t_step"] + c["dwell"] * 0.4
            pts = in_window(self.hist, ta, now)
            if not pts and now - c["t_step"] < c["dwell"] * 4:
                self.after(150, lambda: self._curve_tick(cid))      # nog geen meting na deze stap: even wachten
                return
            if pts:
                i = sum(p[2] for p in pts) / len(pts)
                c["pts"].append((c["v"], sum(p[1] for p in pts) / len(pts), i))
                if self._curve_cc(ta, now) >= 2 or i >= c["i_lim"] * 0.98:
                    c["cc_at"] = c["v"]
                    self.cmdq.put("OUT0")
                    self._curve_finish()
                    return
            if c["v"] >= c["v_end"] - 1e-6:
                if c["hold"] > 0:
                    c["phase"], c["t_hold"] = "hold", now
                    self.after(int(c["hold"] * 1000), lambda: self._curve_tick(cid))
                else:
                    c["i_end"] = c["pts"][-1][2] if c["pts"] else None
                    self._curve_finish()
                return
            c["v"] = round(min(c["v_end"], c["v"] + c["step"]), 2)
            self.cmdq.put(f"VSET1:{c['v']:.2f}")
            c["t_step"] = time.time()
            self.after(int(c["dwell"] * 1000), lambda: self._curve_tick(cid))
            self._curve_refresh()
        else:   # vasthouden op de eindspanning en het gemiddelde nemen
            hp = in_window(self.hist, c["t_hold"] + 1.0, now)
            if self._curve_cc(c["t_hold"] + 0.5, now) >= 2:
                c["cc_at"] = c["v_end"]
                self.cmdq.put("OUT0")
            elif hp:
                c["i_end"] = sum(p[2] for p in hp) / len(hp)
                c["i_max"] = max(p[2] for p in hp)
            else:
                c["i_end"] = c["pts"][-1][2] if c["pts"] else None
            self._curve_finish()

    def _curve_finish(self):
        c = self.curve
        self.curve = None
        res = {"t0": c["t0"], "t1": time.time(), "label": c["label"], "v_end": c["v_end"], "i_lim": c["i_lim"],
               "pts": list(c["pts"]), "cc_at": c["cc_at"], "i_end": c["i_end"], "i_max": c["i_max"],
               "ok": c["cc_at"] is None}
        if res["i_end"] is None and res["pts"]:
            res["i_end"] = res["pts"][-1][2]
        res["uitleg"] = curve_analysis(res)
        if res["ok"] and is_opstartcurve(c["label"]):
            res["uitleg"].append(tr("De uitgang staat nog aan op {0} V.", nl(c["v_end"])))
        self.curves.append(res)
        del self.curves[:-20]
        own = is_opstartcurve(c["label"])
        if res["ok"]:
            self._add_marker(tr("{0}: klaar, {1} bij {2} V", c['label'], fmt_ma(res['i_end'] or 0), nl(c['v_end'])))
            if own:
                self._say(tr("Opstartcurve klaar. {0} bij {1} V.", fmt_ma(res['i_end'] or 0), nl(c['v_end'])))
        else:
            self._add_marker(tr("{0}: grens bereikt bij {1} V, uitgang uit", c['label'], nlf(res['cc_at'], 1)))
            self._beep("alarm")
            if own:
                self._say(tr("Stroomgrens bij {0} V. Uitgang uit.", nlf(res['cc_at'], 1)))
        if own:
            self._wb_add("opstartcurve", tr("Opstartcurve tot {0} V, grens {1}", nl(c['v_end']), fmt_ma(c['i_lim'])) +
                         ("" if res["ok"] else tr(": grens bij {0} V", nlf(res['cc_at'], 1))), about=" ".join(res["uitleg"]))
        if c["done"]:
            c["done"](res)
        self._curve_refresh()

    def _curve_stop(self, msg):
        if not self.curve:
            return
        label = self.curve["label"]
        self.curve = None
        self._add_marker(f"{label}: {msg[0].lower() + msg[1:]}")
        self._curve_refresh()

    def _plot_iv(self, cv, items, i_lim=None):
        """Opstartcurve(s) tekenen op een canvas: x = ingestelde spanning, y = stroom in mA.
        items = [(punten, kleur, dik, grens_bereikt_bij)]; punten = (V ingesteld, V gemeten, A)."""
        cv.delete("all")
        w, h = int(cv.cget("width")), int(cv.cget("height"))
        L, R, T, B = px(50), px(14), px(12), px(26)
        pw, ph = w - L - R, h - T - B
        allp = [p for it in items for p in it[0]]
        xmax = max([p[0] for p in allp] + [1.0])
        xmax = 14.0 if xmax <= 14.0 else nice_ceil(xmax)
        ymax = nice_ceil(max([p[2] * 1000 for p in allp] + [5.0]) * 1.2)
        X = lambda v: L + pw * v / xmax
        Y = lambda ma: T + ph * (1 - min(ma / ymax, 1))
        for k in range(5):
            y = T + ph * k / 4
            cv.create_line(L, y, L + pw, y, fill=GRID)
            cv.create_text(L - px(6), y, text=nl(ymax * (1 - k / 4)), fill=MUTED, anchor="e", font=(FONT, 8))
        stepx = 2 if xmax <= 16 else 5
        ticks = list(range(0, int(xmax) + 1, stepx))
        for k in ticks:
            cv.create_line(X(k), T, X(k), T + ph, fill=GRID)
            last = k == ticks[-1]       # eenheid bij het laatste getal, zodat ze niet over elkaar vallen
            cv.create_text(X(k), T + ph + px(12), text=f"{k} V" if last else str(k), fill=MUTED,
                           anchor="e" if last else "center", font=(FONT, 8))
        cv.create_text(px(6), T + px(2), text="mA", fill=MUTED, anchor="nw", font=(FONT, 8, "bold"))
        if i_lim and i_lim * 1000 <= ymax:
            y = Y(i_lim * 1000)
            cv.create_line(L, y, L + pw, y, fill=LED_RED, dash=(px(5), px(4)))
            cv.create_text(L + px(4), y - px(2), text=tr("stroomgrens"), fill=LED_RED, anchor="sw", font=(FONT, 8))
        for pts, col, width, cc_at in items:
            if len(pts) >= 2:
                cv.create_line(*[c for p in pts for c in (X(p[0]), Y(p[2] * 1000))], fill=col, width=width)
            elif len(pts) == 1:
                x, y = X(pts[0][0]), Y(pts[0][2] * 1000)
                cv.create_oval(x - px(2), y - px(2), x + px(2), y + px(2), fill=col, outline="")
            if cc_at is not None and pts:
                x, y = X(pts[-1][0]), Y(pts[-1][2] * 1000)
                cv.create_oval(x - px(5), y - px(5), x + px(5), y + px(5), fill=LED_RED, outline=TEXT)
                cv.create_text(x + px(8), y, text=tr("grens"), fill=LED_RED, anchor="w", font=(FONT, 8, "bold"))

    def _open_curve(self):
        win = self._toplevel("_cwin", tr("Opstartcurve"))
        if not win:
            return
        cfg = self._curve_cfg
        self._kop(win, tr("Opstartcurve")).pack(anchor="w", padx=22,
                                                                                             pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(780),
                 text=tr("De uitgang gaat uit, dan op 0 V weer aan, en de spanning loopt in kleine stapjes op "
                         "terwijl het paneel de stroom tekent. Een fout zie je dan al bij een paar volt, voordat "
                         "er iets warm kan worden. Bij de stroomgrens stopt het paneel en gaat de uitgang uit. "
                         "Gaat alles goed, dan blijft de uitgang aan op de eindspanning: dit is meteen een "
                         "zachte start.")).pack(anchor="w", padx=22)
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(12, 6))
        ents = {}
        for key, txt, unit, w in (("v", tr("Eindspanning"), "V", 6), ("i", tr("Stroomgrens"), "A", 6), ("stap", tr("Stap"), "V", 5)):
            tk.Label(row, text=txt, bg=PANEL, fg=INK, font=(FONT, 10)).pack(side="left")
            e = self._entry(row, w, size=11)
            e.insert(0, nl(cfg[key]))
            e.pack(side="left", padx=(6, 3), ipady=1)
            tk.Label(row, text=unit, bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=(0, 14))
            ents[key] = e

        def start():
            try:
                v, i, step = (float(ents[k].get().replace(",", ".")) for k in ("v", "i", "stap"))
            except ValueError:
                messagebox.showerror(tr("Ongeldige waarde"), tr("Vul getallen in, bijvoorbeeld 13,8 en 0,1 en 0,2."), parent=win)
                return
            if not 0.05 <= step <= 2.0:
                messagebox.showerror(tr("Ongeldige stap"), tr("De stap moet tussen 0,05 en 2 V liggen."), parent=win)
                return
            dur = (v / step + 1) * 0.5 + 1
            if not messagebox.askyesno(
                    tr("Opstartcurve"), tr("Na afloop blijft de uitgang aan op {0} V.", nl(v)) + "\n\n" +
                    tr("De uitgang gaat uit; daarna loopt de spanning van 0 naar {0} V in "
                                       "stappen van {1} V, met een stroomgrens van {2}. Dat duurt ongeveer {3}. "
                                       "Bij de stroomgrens stopt het paneel en gaat de uitgang uit.\n\nStarten?", nl(v), nl(step), fmt_ma(i), fmt_duur(dur)), parent=win):
                return
            cfg.update(v=v, i=i, stap=step)
            self._curve_start(v, i, step_v=step, dwell=0.5, label=tr("opstartcurve"))

        self._c_btn = self._btn(row, tr("Start"), lambda: self._curve_stop(tr("Gestopt")) if self.curve else start(), bg=BLUE)
        self._c_btn.pack(side="left", padx=(6, 6))
        self._btn(row, tr("Uitgang uit"), lambda: self._send("OUT0")).pack(side="left")
        self._c_canvas = tk.Canvas(win, width=px(800), height=px(330), bg=GLASS, highlightthickness=0)
        self._c_canvas.pack(padx=22, pady=(6, 6))
        self._c_text = tk.Label(win, text="", bg=PANEL, fg=INK, font=(FONT, 10), justify="left", anchor="w",
                                wraplength=px(800))
        self._c_text.pack(anchor="w", fill="x", padx=22)
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=16)
        self._btn(bar, tr("Opslaan als CSV"), self._curve_csv).pack(side="left")
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._curve_refresh()

    def _curve_refresh(self):
        """Venster Opstartcurve bijwerken."""
        win = getattr(self, "_cwin", None)
        try:
            alive = bool(win and win.winfo_exists())
        except tk.TclError:
            alive = False
        if alive:
            items, i_lim = [], None
            done = [r for r in self.curves if is_opstartcurve(r["label"])]
            for r in done[-3:-1] if self.curve is None else done[-2:]:
                items.append((r["pts"], DIM, px(1.5), r["cc_at"]))      # vorige metingen, ter vergelijking
            if self.curve and is_opstartcurve(self.curve["label"]):
                items.append((self.curve["pts"], LED_AMBER, px(2.5), None))
                i_lim = self.curve["i_lim"]
                last = self.curve["pts"][-1] if self.curve["pts"] else None
                txt = (tr("Bezig: {0} V, {1} mA", nl(last[0]), nlf(last[2] * 1000, 0)) if last else tr("Bezig: uitgang op 0 V..."))
            elif done:
                r = done[-1]
                items.append((r["pts"], LED_AMBER, px(2.5), r["cc_at"]))
                i_lim = r["i_lim"]
                txt = (tr("Laatste meting {0:%H:%M:%S} (grijs: de metingen daarvoor).\n", datetime.fromtimestamp(r['t0']))
                       + "\n".join(r["uitleg"]))
            else:
                txt = tr("Nog geen meting. Vul de eindspanning en de stroomgrens in en klik op Start.")
            self._plot_iv(self._c_canvas, items, i_lim)
            self._c_text.config(text=txt)
            running = bool(self.curve and is_opstartcurve(self.curve["label"]))
            self._c_btn.config(text=tr("Stop") if running else tr("Start"), bg=BTN_RED if running else BLUE)

    def _curve_csv(self):
        done = [r for r in self.curves if r["pts"]]
        if not done:
            messagebox.showinfo(tr("Geen meting"), tr("Er is nog geen opstartcurve om op te slaan."))
            return
        r = done[-1]
        path = filedialog.asksaveasfilename(title=tr("Opstartcurve opslaan"), defaultextension=".csv",
                                            initialfile=f"opstartcurve_{datetime.fromtimestamp(r['t0']):%Y%m%d_%H%M}.csv",
                                            filetypes=[(tr("CSV-bestand"), "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["spanning_ingesteld_V", "spanning_gemeten_V", "stroom_mA"])
            for p in r["pts"]:
                wr.writerow([f"{p[0]:.2f}", f"{p[1]:.2f}", f"{p[2] * 1000:.1f}"])
        self._wb_add("opstartcurve", Path(path).name, path, about=tr("opstartcurve opgeslagen als CSV"))

    # ---------- nachttest
    def _open_night(self):
        win = self._toplevel("_nwin", tr("Nachttest"))
        if not win:
            return
        cfg = self._night_cfg
        self._kop(win, tr("Nachttest")).pack(anchor="w", padx=22, pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(620),
                 text=tr("Uren achter elkaar meten, bijvoorbeeld een nacht. Het paneel houdt een log bij, zet "
                         "bijzonderheden als markering in de grafiek, stuurt een melding naar je telefoon en "
                         "maakt aan het eind vanzelf een rapport in de map rapporten. Laat het paneel en de "
                         "laptop zolang aan staan.")).pack(anchor="w",
                                                                                                    padx=22)
        grid = tk.Frame(win, bg=PANEL)
        grid.pack(anchor="w", padx=22, pady=(12, 4))
        ents = {}
        for r, (key, txt, unit) in enumerate((("uren", tr("Duur"), tr("uur")), ("v", tr("Spanning"), "V"),
                                              ("i", tr("Stroomgrens"), "A"), ("piek", tr("Melden bij stroom boven"), "mA"))):
            tk.Label(grid, text=txt, bg=PANEL, fg=INK, font=(FONT, 10)).grid(row=r, column=0, sticky="w", pady=2)
            e = self._entry(grid, 7, size=11)
            e.insert(0, nl(cfg[key]))
            e.grid(row=r, column=1, padx=(10, 4), pady=2)
            tk.Label(grid, text=unit, bg=PANEL, fg=MUTED, font=(FONT, 10)).grid(row=r, column=2, sticky="w")
            ents[key] = e
        log_var = tk.BooleanVar(value=cfg["log"])
        off_var = tk.BooleanVar(value=cfg["uit"])
        self._check(win, tr("Log opslaan in de map logs"), log_var).pack(anchor="w", padx=22, pady=(6, 0))
        self._check(win, tr("Uitgang uit na afloop"), off_var).pack(anchor="w", padx=22, pady=(2, 0))
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(12, 4))

        def start():
            try:
                vals = {k: float(ents[k].get().replace(",", ".")) for k in ents}
            except ValueError:
                messagebox.showerror(tr("Ongeldige waarde"), tr("Vul overal een getal in."), parent=win)
                return
            if not (0.005 <= vals["uren"] <= 48 and vals["piek"] >= 0):
                messagebox.showerror(tr("Ongeldige waarde"), tr("Duur tussen 0,005 en 48 uur, piekgrens 0 of meer (0 "
                                                            "= niet melden)."), parent=win)
                return
            cfg.update(vals, log=log_var.get(), uit=off_var.get())
            self._night_start(win)

        self._n_btn = self._btn(row, tr("Start"), lambda: self._night_stop(tr("gestopt")) if self.night else start(), bg=BLUE)
        self._n_btn.pack(side="left")
        self._n_lbl = tk.Label(row, text="", bg=PANEL, fg=INK, font=(FONT, 10))
        self._n_lbl.pack(side="left", padx=12)
        tk.Label(win, text=tr("BIJZONDERHEDEN"), bg=PANEL, fg=MUTED, font=(FONT, 9, "bold")).pack(anchor="w", padx=22,
                                                                                            pady=(10, 2))
        self._n_list = tk.Listbox(win, height=7, width=70, bg=CARD, fg=INK, font=(FONT, 10), relief="flat",
                                  highlightthickness=1, highlightbackground=LINE, selectbackground=BLUE,
                                  activestyle="none")
        self._n_list.pack(anchor="w", padx=22)
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=16)
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._night_refresh(win)

    def _night_refresh(self, win):
        try:
            if not (win and win.winfo_exists()):
                return
        except tk.TclError:
            return
        n, r = self.night, self.night_result
        self._n_btn.config(text=tr("Stop") if n else tr("Start"), bg=BTN_RED if n else BLUE)
        events = n["events"] if n else (r["events"] if r else [])
        if n:
            el = time.time() - n["t0"]
            self._n_lbl.config(text=tr("Loopt: {0} van {1}, {2} bijzonderheden", fmt_duur(el), fmt_duur(n['t_end'] - n['t0']), len(n['events'])), fg=LED_AMBER)
        elif r:
            self._n_lbl.config(text=r["tekst"], fg=INK, wraplength=px(480), justify="left")
        else:
            self._n_lbl.config(text="")
        self._n_list.delete(0, "end")
        for t, txt in events[-200:]:
            self._n_list.insert("end", f"{datetime.fromtimestamp(t):%H:%M:%S}  {txt}")
        if not events:
            self._n_list.insert("end", tr("Nog niets bijzonders."))
        self.after(1000, lambda: self._night_refresh(win))

    def _night_start(self, parent=None):
        cfg = self._night_cfg
        if self.night:
            return
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."), parent=parent)
            return
        vmax, imax = self._limits()
        if not (0 <= cfg["v"] <= vmax and 0 <= cfg["i"] <= imax):
            messagebox.showerror(tr("Buiten de grens"), self._limit_text(), parent=parent)
            return
        up = self.out and self.vset is not None and cfg["v"] > self.vset + 0.05
        if not messagebox.askyesno(
                tr("Nachttest starten"),
                tr("{0} meten op {1} V met een stroomgrens van {2}.", fmt_duur(cfg['uren'] * 3600), nl(cfg['v']), fmt_ma(cfg['i']))
                + (tr("\n\nDe uitgang staat aan en de spanning gaat omhoog van {0} naar {1} V.", nl(self.vset), nl(cfg['v']))
                   if up else "") + tr("\n\nDe uitgang gaat aan (of blijft aan). Starten?"), parent=parent, icon="warning"):
            return
        msg = tr("Gestopt: nachttest gestart")
        self._stop_program(msg)
        self._stop_sim(msg)
        self._stop_new(msg)
        for cmd in (f"ISET1:{cfg['i']:.3f}", f"VSET1:{cfg['v']:.2f}", "OUT1"):
            self.cmdq.put(cmd)
        now = time.time()
        own_log = None
        if cfg["log"] and not self.log_file:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            own_log = LOG_DIR / f"nachttest_{datetime.now():%Y%m%d_%H%M}.csv"
            self._log_open(own_log)
        self.night = {"id": now, "t0": now, "t_end": now + cfg["uren"] * 3600, "uit": cfg["uit"],
                      "peak": cfg["piek"] / 1000, "events": [], "counts": {}, "last_ev": {},
                      "last_note": {}, "cc_since": None, "cc_flag": False,
                      "hour": 0, "log": own_log}
        self._add_marker(tr("nachttest: start, {0}", fmt_duur(cfg['uren'] * 3600)))
        self.after(1000, lambda: self._night_tick(now))

    def _night_event(self, kind, text, notify=True):
        n = self.night
        if not n:
            return
        now = time.time()
        n["counts"][kind] = n["counts"].get(kind, 0) + 1
        if now - n["last_ev"].get(kind, 0) < 60:       # hooguit een regel per soort per minuut
            return
        n["last_ev"][kind] = now
        n["events"].append((now, text))
        self._add_marker(tr("nachttest: {0}", text))
        if notify and now - n["last_note"].get(kind, 0) >= 600:
            n["last_note"][kind] = now
            self._notify(tr("Nachttest"), text, priority=4, tags=("warning",))

    def _night_tick(self, nid):
        n = self.night
        if not n or n["id"] != nid:
            return
        now = time.time()
        recent = in_window(self.hist, now - 1.2, now)
        if recent and n["peak"] > 0:
            m = max(p[2] for p in recent)
            if m > n["peak"]:
                self._night_event("piek", tr("stroompiek {0} mA (grens {1} mA)", nlf(m * 1000, 0), nlf(n['peak'] * 1000, 0)))
        if self.out and self.cc:
            if n["cc_since"] is None:
                n["cc_since"] = now
            elif now - n["cc_since"] >= 2 and not n["cc_flag"]:
                n["cc_flag"] = True
                self._night_event("cc", tr("de voeding begrenst de stroom (CC)"))
        else:
            n["cc_since"], n["cc_flag"] = None, False
        h = int((now - n["t0"]) // 3600)
        if h > n["hour"]:
            n["hour"] = h
            self._add_marker(tr("nachttest: {0} uur", h))
        if now >= n["t_end"]:
            self._night_finish(tr("klaar"))
            return
        self.after(1000, lambda: self._night_tick(nid))

    def _night_finish(self, why):
        n = self.night
        self.night = None
        t1 = time.time()
        if n["log"] and self.log_file:
            self._log_close()
        if n["uit"] and why == tr("klaar") and self.dev:
            self.cmdq.put("OUT0")
        st = stats(in_window(self.hist, n["t0"], t1))
        txt = tr("Nachttest {0}: {1}, {2} bijzonderheden", why, fmt_duur(t1 - n['t0']), len(n['events']))
        if st:
            txt += (tr("; gemiddeld {0}, hoogste {1}, {2} mAh, {3} Wh", fmt_ma(st['i_gem']), fmt_ma(st['i_max']), nlf(st['mah'], 0), nlf(st['wh'], 2)))
        txt += "."
        if self.out and not (n["uit"] and why == tr("klaar")):
            txt += " " + tr("De uitgang staat nog aan.")
        self.night_result ={"t0": n["t0"], "t1": t1, "why": why, "events": n["events"], "counts": n["counts"],
                             "stats": st, "log": str(n["log"]) if n["log"] else "", "tekst": txt, "rapport": ""}
        self._add_marker(tr("nachttest {0}", why))
        if st:
            path = REPORT_DIR / f"nachttest_{datetime.fromtimestamp(n['t0']):%Y%m%d_%H%M}.html"
            src, self.src = self.src, None      # het rapport gaat over de nacht zelf, ook als er een oud log open staat
            try:
                made = self._make_report(tr("Nachttest {0}", nl_date(n['t0'])), txt, n["t0"], t1, path=path,
                                         open_browser=False, wb_kind="nachttest")
            finally:
                self.src = src
            if made:
                self.night_result["rapport"] = str(made)
        if not self.night_result["rapport"]:
            self._wb_add("nachttest", tr("Nachttest {0}", nl_date(n['t0'])), about=txt)
        self._notify(tr("Nachttest klaar") if why == tr("klaar") else tr("Nachttest gestopt"), txt,
                     priority=4 if n["events"] or why != tr("klaar") else 3)

    def _night_stop(self, why):
        if self.night:
            self._night_finish(why)

    # ---------- logs vergelijken
    def _open_compare(self):
        win = self._toplevel("_vwin", tr("Logs vergelijken"))
        if not win:
            return
        if self.src and not self.cmp.get("A"):
            self.cmp["A"] = {"name": self.src["name"], "pts": self.src["pts"]}
        self._kop(win, tr("Logs vergelijken")).pack(anchor="w", padx=22,
                                                                                             pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(860),
                 text=tr("Twee logs van het paneel over elkaar, allebei vanaf hun eigen begin. Bijvoorbeeld het "
                         "verbruik voor en na een firmware-update, of met en zonder scherm.")).pack(anchor="w", padx=22)
        self._v_names = {}
        for key, col in (("A", LED_AMBER), ("B", ACCENT)):
            r = tk.Frame(win, bg=PANEL)
            r.pack(fill="x", padx=22, pady=(8, 0))
            tk.Label(r, image=dot_image(col, px(11)), bg=PANEL).pack(side="left")
            tk.Label(r, text=tr("  Meting {0}", key), bg=PANEL, fg=INK, font=(FONT, 11, "bold")).pack(side="left")
            self._btn(r, tr("Kiezen"), lambda k=key: self._cmp_pick(k), size=9).pack(side="left", padx=12)
            lbl = tk.Label(r, text="", bg=PANEL, fg=MUTED, font=(FONT, 10))
            lbl.pack(side="left")
            self._v_names[key] = lbl
        seg = tk.Frame(win, bg=CARD_2)
        seg.pack(anchor="w", padx=22, pady=(12, 6))
        for val, txt in (("stroom", tr("Stroom")), ("spanning", tr("Spanning")), ("vermogen", tr("Vermogen"))):
            tk.Radiobutton(seg, text=txt, value=val, variable=self.cmp_what, indicatoron=0, bg=CARD_2, fg=TEXT,
                           selectcolor=KEUZE_AAN, activebackground=CARD_3, activeforeground=TEXT, relief="flat", bd=0,
                           padx=px(12), pady=px(4), font=(FONT, 9), cursor="hand2", highlightthickness=0,
                           command=self._cmp_refresh).pack(side="left")
        self._v_canvas = tk.Canvas(win, width=px(860), height=px(280), bg=GLASS, highlightthickness=0)
        self._v_canvas.pack(padx=22, pady=(4, 8))
        self._v_table = tk.Frame(win, bg=PANEL)
        self._v_table.pack(anchor="w", padx=22)
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=16)
        self._btn(bar, tr("Rapport maken"), self._cmp_report).pack(side="left")
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._cmp_refresh()

    def _cmp_pick(self, key):
        path = filedialog.askopenfilename(title=tr("Meting {0} kiezen", key), initialdir=str(LOG_DIR) if LOG_DIR.exists() else None,
                                          filetypes=[(tr("CSV-bestand"), "*.csv")], parent=self._vwin)
        if not path:
            return
        try:
            pts, _ = read_log(path)
        except (OSError, KeyError, ValueError, TypeError):
            messagebox.showerror(tr("Kan log niet openen"), tr("Dit bestand is geen log van CurrentBench."), parent=self._vwin)
            return
        if len(pts) < 2:
            messagebox.showerror(tr("Te weinig metingen"), tr("Dit log bevat minder dan twee metingen."), parent=self._vwin)
            return
        self.cmp[key] = {"name": Path(path).name, "pts": pts}
        self._cmp_refresh()

    def _cmp_series(self, pts):
        what = self.cmp_what.get()
        t0 = pts[0][0]
        if what == "stroom":
            return [(p[0] - t0, p[2] * 1000) for p in pts], "mA"
        if what == "spanning":
            return [(p[0] - t0, p[1]) for p in pts], "V"
        return [(p[0] - t0, p[1] * p[2]) for p in pts], "W"

    def _cmp_rows(self):
        a = stats(self.cmp["A"]["pts"]) if self.cmp.get("A") else None
        b = stats(self.cmp["B"]["pts"]) if self.cmp.get("B") else None
        rows = []
        for label, key, f in ((tr("Duur"), "duur", lambda x: fmt_duur(x)), (tr("Gemiddelde stroom"), "i_gem", fmt_ma),
                              (tr("Hoogste stroom"), "i_max", fmt_ma), (tr("Laagste stroom"), "i_min", fmt_ma),
                              (tr("Gemiddelde spanning"), "v_gem", lambda x: f"{nlf(x, 2)} V"),
                              (tr("Gemiddeld vermogen"), "w_gem", lambda x: f"{nlf(x, 2)} W"),
                              (tr("Lading"), "mah", lambda x: f"{nlf(x, 1)} mAh"), (tr("Energie"), "wh", lambda x: f"{nlf(x, 3)} Wh")):
            va, vb = (a[key] if a else None), (b[key] if b else None)
            diff = ""
            if va is not None and vb is not None and key != "duur":
                d = vb - va
                pct = f" ({'+' if d >= 0 else ''}{nlf(d / va * 100, 1)} %)" if abs(va) > 1e-9 else ""
                diff = ("+" if d >= 0 else "-") + f(abs(d)) + pct
            rows.append((label, f(va) if va is not None else "-", f(vb) if vb is not None else "-", diff))
        return rows

    def _cmp_refresh(self):
        win = getattr(self, "_vwin", None)
        try:
            if not (win and win.winfo_exists()):
                return
        except tk.TclError:
            return
        for key in ("A", "B"):
            m = self.cmp.get(key)
            self._v_names[key].config(text=f"{m['name']}  ({fmt_duur(m['pts'][-1][0] - m['pts'][0][0])})" if m
                                      else tr("nog niet gekozen"))
        cv = self._v_canvas
        cv.delete("all")
        w, h = int(cv.cget("width")), int(cv.cget("height"))
        L, R, T, B = px(56), px(16), px(14), px(28)
        pw, ph = w - L - R, h - T - B
        series = [(self._cmp_series(self.cmp[k]["pts"]), col) for k, col in (("A", LED_AMBER), ("B", ACCENT))
                  if self.cmp.get(k)]
        if not series:
            cv.create_text(w / 2, h / 2, text=tr("Kies twee logs om te vergelijken."), fill=MUTED, font=(FONT, 11))
        else:
            unit = series[0][0][1]
            xmax = max(s[-1][0] for (s, u), c in series) or 1
            ymax = nice_ceil(max(max(p[1] for p in s) for (s, u), c in series) * 1.15 or 0.01)
            X = lambda x: L + pw * x / xmax
            Y = lambda y: T + ph * (1 - min(y / ymax, 1))
            for k in range(5):
                y = T + ph * k / 4
                cv.create_line(L, y, L + pw, y, fill=GRID)
                cv.create_text(L - px(6), y, text=nl(ymax * (1 - k / 4)), fill=MUTED, anchor="e", font=(FONT, 8))
            for k in range(7):
                x = L + pw * k / 6
                cv.create_line(x, T, x, T + ph, fill=GRID)
                cv.create_text(x, T + ph + px(14), text=fmt_duur(xmax * k / 6), fill=MUTED, font=(FONT, 8))
            cv.create_text(px(6), T, text=unit, fill=MUTED, anchor="nw", font=(FONT, 8, "bold"))
            for (s, u), col in series:
                pts3 = [(p[0], 0, p[1]) for p in s]
                flat = self._trace(pts3, X, Y, 2, pw)
                if len(flat) >= 4:
                    cv.create_line(*flat, fill=col, width=px(2))
        for wdg in self._v_table.winfo_children():
            wdg.destroy()
        for c, head in enumerate(("", tr("Meting A"), tr("Meting B"), tr("Verschil B - A"))):
            tk.Label(self._v_table, text=head, bg=PANEL, fg=MUTED, font=(FONT, 9, "bold")).grid(row=0, column=c,
                                                                                            sticky="w", padx=(0, 26))
        for r, row in enumerate(self._cmp_rows(), start=1):
            for c, val in enumerate(row):
                tk.Label(self._v_table, text=val, bg=PANEL, fg=INK if c else MUTED, font=(FONT, 10)).grid(
                    row=r, column=c, sticky="w", padx=(0, 26))

    def _cmp_report(self):
        if not (self.cmp.get("A") and self.cmp.get("B")):
            messagebox.showinfo(tr("Twee logs nodig"), tr("Kies eerst meting A en meting B."), parent=self._vwin)
            return
        esc = html.escape
        W, H, L, R, T, B = 1000, 360, 62, 20, 20, 40
        pw, ph = W - L - R, H - T - B
        series = [(self._cmp_series(self.cmp[k]["pts"]), col) for k, col in (("A", "#C98400"), ("B", "#2F6FD0"))]
        unit = series[0][0][1]
        xmax = max(s[-1][0] for (s, u), c in series) or 1
        ymax = nice_ceil(max(max(p[1] for p in s) for (s, u), c in series) * 1.15 or 0.01)
        X = lambda x: L + pw * x / xmax
        Y = lambda y: T + ph * (1 - min(y / ymax, 1))
        svg = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
               f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="#F3EEDF"/>']
        for k in range(5):
            y = T + ph * k / 4
            svg.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="#DDD5C1"/>')
            svg.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="#6E6A60">'
                       f'{nl(ymax * (1 - k / 4))}</text>')
        for k in range(7):
            x = L + pw * k / 6
            svg.append(f'<text x="{x:.1f}" y="{T + ph + 22}" text-anchor="middle" font-size="12" fill="#6E6A60">'
                       f'{fmt_duur(xmax * k / 6)}</text>')
        svg.append(f'<text x="6" y="{T + 10}" font-size="12" fill="#6E6A60">{unit}</text>')
        for (s, u), col in series:
            flat = self._trace([(p[0], 0, p[1]) for p in s], X, Y, 2, pw)
            pairs = " ".join(f"{flat[k]:.1f},{flat[k + 1]:.1f}" for k in range(0, len(flat), 2))
            svg.append(f'<polyline points="{pairs}" fill="none" stroke="{col}" stroke-width="2"/>')
        svg.append("</svg>")
        rows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(c)}</td><td>{esc(d)}</td></tr>"
                       for a, b, c, d in self._cmp_rows())
        page = f"""<!DOCTYPE html>
<html lang="{korad_taal.huidig()}"><head><meta charset="utf-8"><title>{tr("Vergelijking")}</title>
<style>
  body {{ margin: 0; background: #E6E0D2; color: #2B2A27; font-family: "Bahnschrift", "Segoe UI", sans-serif; }}
  .page {{ max-width: 1040px; margin: 32px auto; background: #FBF8F1; padding: 40px 52px; border: 1px solid #CFC8B6; }}
  h1 {{ font-size: 32px; margin: 2px 0 6px; }} .meta {{ color: #4A4740; font-size: 15px; margin: 2px 0; }}
  .legend i {{ display: inline-block; width: 22px; height: 3px; vertical-align: middle; margin: 0 6px 0 14px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 15px; margin-top: 18px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #DDD5C1; }} th {{ color: #7A7466; font-size: 13px; }}
  svg {{ width: 100%; height: auto; font-family: inherit; }}
  @media print {{ body {{ background: white; }} .page {{ margin: 0; border: none; padding: 0; }} }}
</style></head><body><div class="page">
  <p class="meta">{tr("Vergelijking")}</p><h1>{tr("{0} en {1}", esc(self.cmp['A']['name']), esc(self.cmp['B']['name']))}</h1>
  <p class="legend"><i style="background:#C98400;margin-left:0"></i>{tr("Meting A")}: {esc(self.cmp['A']['name'])}
    <i style="background:#2F6FD0"></i>{tr("Meting B")}: {esc(self.cmp['B']['name'])}</p>
  {''.join(svg)}
  <table><tr><th></th><th>{tr("Meting A")}</th><th>{tr("Meting B")}</th><th>{tr("Verschil B - A")}</th></tr>{rows}</table>
  <p class="meta" style="margin-top:20px">{tr("Allebei vanaf hun eigen begin.")}
    {tr("Gemaakt met CurrentBench op {0} om {1}.", nl_date(time.time()), f"{datetime.now():%H:%M}")}</p>
</div></body></html>
"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"vergelijking_{datetime.now():%Y%m%d_%H%M%S}.html"
        path.write_text(page, encoding="utf-8")
        self._wb_add("vergelijking", tr("{0} en {1}", self.cmp['A']['name'], self.cmp['B']['name']), path)
        webbrowser.open(path.resolve().as_uri())
        return path

    # ---------- mini-venster
    def _toggle_mini(self):
        if self.mini:
            self._mini_close()
            return
        win = tk.Toplevel(self)
        win.title(NAAM)
        win.configure(bg=CARD)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
            win.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        row = tk.Frame(win, bg=CARD)
        row.pack(padx=14, pady=(10, 2))
        v = tk.Label(row, text="--", bg=CARD, fg=LED_RED, font=(FONT_NUM, 24), width=6, anchor="e")
        v.pack(side="left")
        tk.Label(row, text="V", bg=CARD, fg=MUTED, font=(FONT, 11)).pack(side="left", anchor="s", pady=(0, 6))
        i = tk.Label(row, text="--", bg=CARD, fg=LED_AMBER, font=(FONT_NUM, 24), width=6, anchor="e")
        i.pack(side="left", padx=(10, 0))
        tk.Label(row, text="A", bg=CARD, fg=MUTED, font=(FONT, 11)).pack(side="left", anchor="s", pady=(0, 6))
        row2 = tk.Frame(win, bg=CARD)
        row2.pack(fill="x", padx=14, pady=(2, 10))
        lamp = Lamp(row2, tr("niet verbonden"), bg=CARD, size=10)
        lamp.pack(side="left")
        self._btn(row2, tr("Uit"), lambda: self._send("OUT0"), bg=BTN_RED, size=9).pack(side="right")
        tk.Label(row2, text=tr("Esc = noodstop"), bg=CARD, fg=DIM, font=(FONT, 8)).pack(side="right", padx=8)
        for wdg in (v, i):
            wdg.bind("<Double-Button-1>", lambda e: (self.deiconify(), self.lift()))
        win.protocol("WM_DELETE_WINDOW", self._mini_close)
        self.mini = {"win": win, "v": v, "i": i, "lamp": lamp}
        win.update_idletasks()
        wl, wt, wr, wb = self._workarea()
        try:
            x, y = (int(a) for a in self.settings.get("mini_pos", "").split(","))
        except ValueError:
            x, y = wr - win.winfo_reqwidth() - px(24), wt + px(24)
        x = max(wl, min(x, wr - win.winfo_reqwidth()))
        y = max(wt, min(y, wb - win.winfo_reqheight() - px(30)))
        win.geometry(f"+{x}+{y}")
        self._mini_update()

    def _mini_close(self):
        m = self.mini
        if not m:
            return
        self.mini = None
        try:
            self.settings["mini_pos"] = f"{m['win'].winfo_x()},{m['win'].winfo_y()}"
            save_settings(self.settings)
            m["win"].destroy()
        except tk.TclError:
            pass

    def _mini_update(self, v=None, i=None):
        m = self.mini
        if not m:
            return
        try:
            if not self.dev:
                m["v"].config(text="--")
                m["i"].config(text="--")
                m["lamp"].set(False)
                m["lamp"].lbl.config(text=tr("niet verbonden"))
                return
            if v is not None:
                m["v"].config(text=nlf(v, 2))
                m["i"].config(text=nlf(i, 3))
            if not self.out:
                m["lamp"].set(False)
                m["lamp"].lbl.config(text=tr("uitgang uit"))
            elif self.cc:
                m["lamp"].set(True, LED_AMBER)
                m["lamp"].lbl.config(text=tr("CC  stroom begrensd"))
            else:
                m["lamp"].set(True)
                m["lamp"].lbl.config(text=tr("CV  uitgang aan"))
        except tk.TclError:
            self.mini = None

    # ---------- telefoon als afstandsbediening
    def _web_url(self):
        return f"http://{local_ip()}:{self.settings['web_poort']}/?k={self.settings['web_code']}"

    def _web_start(self):
        if self.web:
            return True
        if not self.settings.get("web_code"):
            self.settings["web_code"] = secrets.token_urlsafe(9)
            save_settings(self.settings)
        try:
            srv = ThreadingHTTPServer((WEB_HOST, int(self.settings["web_poort"])), make_web_handler(self))
        except OSError as e:
            messagebox.showerror(tr("Telefoon"), tr("De webserver kon niet starten op poort {0}.\n\n{1}", self.settings['web_poort'], e))
            return False
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.web = srv
        self.settings["web_aan"] = True
        save_settings(self.settings)
        self._add_marker(tr("telefoon: bediening aan"))
        self._web_tick()
        return True

    def _web_stop(self, remember=True):
        srv, self.web = self.web, None
        if not srv:
            return
        threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
        if remember:
            self.settings["web_aan"] = False
            save_settings(self.settings)
            self._add_marker(tr("telefoon: bediening uit"))

    def _web_tick(self):
        if not self.web:
            return
        now = time.time()
        recent = in_window(self.hist, now - 300, now)
        step = max(1, len(recent) // 150)
        last = self.hist[-1] if (self.hist and self.dev) else None
        self._web_snap = {
            "t": now, "verbonden": bool(self.dev), "v": last[1] if last else None, "i": last[2] if last else None,
            "vset": self.vset if self.dev else None, "iset": self.iset if self.dev else None,
            "uit": bool(self.out and self.dev), "cc": bool(self.cc), "grens": PROJECTS[self.settings["project"]]["naam"],
            "alarm": self.alarm or "", "programma": self.prog_lbl.cget("text"),
            "punten": [[round(now - p[0], 1), round(p[1], 2), round(p[2], 4)] for p in recent[::step]]}
        self.after(1000, self._web_tick)

    def _open_phone(self):
        win = self._toplevel("_twin", tr("Telefoon"))
        if not win:
            return
        self._kop(win, tr("Telefoon als afstandsbediening")).pack(
            anchor="w", padx=22, pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(640),
                 text=tr("Zet de bediening aan en scan de code met de camera van je telefoon (zelfde "
                         "wifi-netwerk als de laptop). Op de telefoon zie je spanning, stroom, de grafiek van de "
                         "laatste vijf minuten en een alarm. Je kunt er een markering plaatsen en de uitgang UIT "
                         "zetten. Aanzetten of de spanning veranderen kan alleen aan de laptop.")).pack(anchor="w", padx=22)
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(12, 6))
        self._t_lamp = Lamp(row, "", bg=PANEL)
        self._t_lamp.pack(side="left")
        self._t_btn = self._btn(row, "", lambda: (self._web_stop() if self.web else self._web_start(),
                                                 self._phone_refresh()))
        self._t_btn.pack(side="left", padx=14)
        self._btn(row, tr("Nieuwe code"), self._phone_newcode, size=9).pack(side="left")
        self._t_qr = tk.Label(win, bg=PANEL)
        self._t_qr.pack(anchor="w", padx=22, pady=(8, 4))
        self._t_url = tk.Entry(win, width=58, font=(FONT, 10), relief="flat", bg=CARD_2, fg=TEXT,
                               readonlybackground=CARD_2, highlightthickness=0)
        self._t_url.pack(anchor="w", padx=22, ipady=3)
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 9), justify="left", wraplength=px(640),
                 text=tr("De eerste keer vraagt Windows of Python verbindingen mag ontvangen: kies "
                         "Privénetwerken en Toestaan. De code in de link werkt als een wachtwoord; met Nieuwe "
                         "code werken oude links niet meer.")).pack(anchor="w", padx=22, pady=(8, 0))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=16)
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._phone_refresh()

    def _phone_newcode(self):
        self.settings["web_code"] = secrets.token_urlsafe(9)
        save_settings(self.settings)
        self._add_marker(tr("telefoon: nieuwe code"))
        self._phone_refresh()

    def _phone_refresh(self):
        win = getattr(self, "_twin", None)
        try:
            if not (win and win.winfo_exists()):
                return
        except tk.TclError:
            return
        on = bool(self.web)
        self._t_lamp.set(on)
        self._t_lamp.lbl.config(text=tr("Aan: bereikbaar op het thuisnetwerk") if on else tr("Uit"))
        self._t_btn.config(text=tr("Uitzetten") if on else tr("Aanzetten"), bg=CARD_2 if on else BLUE)
        self._t_url.config(state="normal")
        self._t_url.delete(0, "end")
        if on:
            url = self._web_url()
            self._t_url.insert(0, url)
            self._t_qr_img = qr_photo(url, px(4))
            self._t_qr.config(image=self._t_qr_img or "", text="" if self._t_qr_img else tr("(QR-module ontbreekt)"),
                              fg=MUTED)
        else:
            self._t_qr_img = None
            self._t_qr.config(image="", text="")
        self._t_url.config(state="readonly")

    # ---------- gereedschap
    def _open_tools(self):
        win = self._toplevel("_xwin", tr("Gereedschap"))
        if not win:
            return
        self._kop(win, tr("Gereedschap")).pack(anchor="w", padx=22,
                                                                                        pady=(18, 8))
        grid = tk.Frame(win, bg=PANEL)
        grid.pack(padx=22)
        mini_tekst = tr("staat aan") if self.mini else tr("staat uit")
        tiles = ((tr("Opstartcurve"), tr("Spanning langzaam van 0 omhoog en de stroom tekenen: fouten zie je dan al "
                                     "bij een paar volt."), "curve", self._open_curve, self._wb_tekst("opstartcurve")),
                 (tr("Onderdelentester"), tr("Diode of led (richting en kleur), of een kleine weerstand nameten."), "onderdeel", self._open_parts, self._wb_tekst("onderdeel")),
                 (tr("Nachttest"), tr("Uren meten met een log, meldingen bij bijzonderheden en 's ochtends een "
                                  "rapport."),
                  "nacht", self._open_night, self._wb_tekst("nachttest")),
                 (tr("Logs vergelijken"), tr("Twee metingen over elkaar, met de verschillen in een tabel."), "vergelijk",
                  self._open_compare, self._wb_tekst("vergelijking")),
                 (tr("Stroomafdruk"), tr("Bewaar hoe een goed bordje opstart en vergelijk elke nieuwe start daarmee."), "afdruk",
                  self._open_afdruk, tr("in gebruik: {0}", self.settings['afdruk_actief']) if self.settings.get("afdruk_actief")
                  else tr("niet in gebruik")),
                 (tr("Projecten"), tr("Grens, kleur, geheugens en bewaking per project."), "projecten", self._open_projecten,
                  tr("nu: {0}", PROJECTS[self.settings['project']]['kort'])),
                 (tr("Werkboek"), tr("Alles wat je hebt gemeten op datum, met een grafiekje per dag. Ook voor "
                                 "notities."),
                  "werkboek", self._open_workbook, tr("{0} regels", len(self.wb))),
                 (tr("Werkbankstand"), tr("De hele laptop als display: twee enorme getallen en een uit-knop. F11 "
                                      "schakelt."),
                  "werkbank", self._toggle_bench, ""),
                 (tr("Mini-venster"), tr("Klein venster dat altijd bovenop blijft: spanning, stroom, CC en een "
                                     "uit-knop."),
                  "mini", self._toggle_mini, mini_tekst),
                 (tr("Telefoon"), tr("De meters op je telefoon, met een knop om de uitgang uit te zetten."), "telefoon",
                  self._open_phone, tr("staat aan") if self.web else tr("staat uit")),
                 (tr("Handleiding"), tr("Alle functies stap voor stap, als PDF."), "hulp", self._open_handleiding, ""),
                 (tr("Over dit programma"), tr("Versie, maker en licenties."), "info", self._open_over, ""),
                 (tr("Welkom"), tr("De eerste stappen en de taalkeuze."), "info", self._open_welkom, ""),
                 (tr("Foutinformatie"), tr("Gegevens om mee te sturen als je een fout meldt."), "info",
                  self._open_foutinfo, ""))
        for n, (title, about, icoon, cmd, laatst) in enumerate(tiles):
            card = tk.Frame(grid, bg=CARD, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
            card.grid(row=n // 3, column=n % 3, sticky="nsew", padx=(0, 12 if n % 3 < 2 else 0), pady=(0, 12))
            rij = tk.Frame(card, bg=CARD)
            rij.pack(fill="x", padx=14, pady=(12, 2))
            ic = tk.Label(rij, text=ICONEN[icoon], bg=CARD, fg=PROJECTS[self.settings["project"]]["kleur"],
                          font=(FONT_ICON, 16))
            ic.pack(side="left", padx=(0, 10))
            kop_ = tk.Label(rij, text=title, bg=CARD, fg=INK, font=(FONT, 12, "bold"))
            kop_.pack(side="left")
            uitleg = tk.Label(card, text=about, bg=CARD, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(280))
            uitleg.pack(anchor="w", padx=14)
            stand = tk.Label(card, text=laatst, bg=CARD, fg=DIM, font=(FONT, 9), justify="left", wraplength=px(280))
            stand.pack(anchor="w", side="bottom", padx=14, pady=(8, 12))
            delen = (card, rij, ic, kop_, uitleg, stand)

            def hover(aan, delen=delen):
                for d in delen:
                    d.config(bg=CARD_2 if aan else CARD)

            for d in delen:
                d.bind("<Enter>", lambda e, h=hover: h(True))
                d.bind("<Leave>", lambda e, h=hover: h(False))
                d.bind("<Button-1>", lambda e, c=cmd: c())
        for c in range(3):
            grid.grid_columnconfigure(c, uniform="tegel")
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(900),
                 text=tr("Noodstop: de Esc-toets zet altijd de uitgang uit, in elk venster van het paneel.")).pack(
            anchor="w", padx=22, pady=(0, 4))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=14)
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")

    def _wb_tekst(self, *soorten):
        """Laatste regel van deze soorten uit het werkboek, kort en met de datum."""
        e = next((x for x in reversed(self.wb) if x.get("soort") in soorten), None)
        if not e:
            return tr("nog niet gedaan")
        d = datetime.fromtimestamp(e["t"]).date()
        dagen = (datetime.now().date() - d).days
        wanneer = tr("vandaag") if dagen == 0 else (tr("gisteren") if dagen == 1 else tr("{0} dagen geleden", dagen))
        titel = e["titel"]
        return f"{wanneer}: {titel if len(titel) <= 48 else titel[:47] + '...'}"

    # ---------- gesproken meldingen (06-10-2026)
    def _speech_ensure(self, reprobe=False):
        """Spraakproces starten, of opnieuw zoeken naar een stem nadat er een in Windows is toegevoegd."""
        sp = self.speaker
        if sp is None or (reprobe and sp.state in ("geen_stem", "fout")):
            if sp:
                sp.stop()
            self.speaker = Speaker()
        return self.speaker

    def _say(self, text):
        """Melding uitspreken als dat aan staat (Instellingen). Dezelfde tekst binnen 4 s maar een keer."""
        if not self.settings.get("spraak_aan"):
            return
        now = time.time()
        if text == self._said[0] and now - self._said[1] < 4:
            return
        self._said = (text, now)
        self._speech_ensure().say(spoken(text))

    # ---------- onderdelentester
    PT_GAUGE = {"diode": (5.0, 12.0), "weerstand": (1.0, 120.0)}   # schaal V en mA per soort

    def _open_parts(self):
        win = self._toplevel("_ptwin", tr("Onderdelentester"))
        if not win:
            return
        self._kop(win, tr("Onderdelentester")).pack(anchor="w", padx=22,
                                                                                             pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(1000),
                 text=tr("De voeding als meetinstrument voor een los onderdeel: de doorlaatspanning en de "
                         "richting van een diode of led, of de waarde van een kleine weerstand. De uitgang gaat "
                         "een paar seconden aan met een lage stroomgrens en daarna weer uit; je instellingen "
                         "komen terug. Alleen losse onderdelen aan de klemmen, nooit de print.")).pack(anchor="w", padx=22)
        cards = tk.Frame(win, bg=PANEL)
        cards.pack(fill="x", padx=22, pady=(14, 0))
        self._pt_cards = {}
        for n, (key, m) in enumerate(PART_MODES.items()):
            card = tk.Frame(cards, bg=CARD, highlightthickness=px(2), highlightbackground=LINE, cursor="hand2")
            card.grid(row=0, column=n, sticky="nsew", padx=(0, 12 if n < 2 else 0))
            cards.grid_columnconfigure(n, weight=1, uniform="pt")
            t = tk.Label(card, text=m["naam"], bg=CARD, fg=INK, font=(FONT, 12, "bold"), cursor="hand2")
            t.pack(anchor="w", padx=14, pady=(10, 0))
            s = tk.Label(card, text=m["kort"], bg=CARD, fg=MUTED, font=(FONT, 10), cursor="hand2")
            s.pack(anchor="w", padx=14, pady=(0, 10))
            for w in (card, t, s):
                w.bind("<Button-1>", lambda e, k=key: self._part_select(k))
            self._pt_cards[key] = card
        cols = tk.Frame(win, bg=PANEL)
        cols.pack(fill="x", padx=22, pady=(14, 0))
        left = tk.Frame(cols, bg=PANEL)
        left.pack(side="left", anchor="n")
        self._pt_cv = tk.Canvas(left, width=px(520), height=px(118), bg=GLASS, highlightthickness=0)
        self._pt_cv.pack(anchor="w")
        self._pt_how = tk.Label(left, text="", bg=PANEL, fg=INK, font=(FONT, 10), justify="left", wraplength=px(520),
                                anchor="w", height=5)
        self._pt_how.pack(anchor="w", fill="x", pady=(8, 0))
        row = tk.Frame(left, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self._pt_btn = self._btn(row, tr("Meten"), lambda: self._part_stop(tr("Gestopt")) if self.part else
                                 self._part_start(self._pt_sel), bg=BLUE, size=11)
        self._pt_btn.pack(side="left")
        self._btn(row, tr("Uitgang uit"), lambda: self._send("OUT0")).pack(side="left", padx=(8, 0))
        self._pt_state = tk.Label(row, text="", bg=PANEL, fg=MUTED, font=(FONT, 10))
        self._pt_state.pack(side="left", padx=(14, 0))
        self._caption(left, tr("Eerdere metingen"), bg=PANEL).pack(anchor="w", pady=(14, 4))
        self._pt_tree = ttk.Treeview(left, columns=("tijd", "soort", "uitslag"), show="headings", height=5,
                                     selectmode="browse")
        for col, txt, w in (("tijd", tr("Tijd"), 80), ("soort", tr("Soort"), 120), ("uitslag", tr("Uitslag"), 318)):
            self._pt_tree.heading(col, text=txt, anchor="w")
            self._pt_tree.column(col, width=px(w), anchor="w", stretch=False)
        self._pt_tree.pack(anchor="w")
        self._pt_tree.bind("<<TreeviewSelect>>", lambda e: self._part_refresh())
        self._pt_seen = -1
        right = tk.Frame(cols, bg=PANEL)
        right.pack(side="left", anchor="n", padx=(18, 0))
        gc = self._card(right)
        gc.pack(fill="x")
        self._caption(gc, tr("Meters")).pack(anchor="w", padx=14, pady=(10, 0))
        gr = tk.Frame(gc, bg=CARD)
        gr.pack(padx=10, pady=(2, 8))
        self._pt_gv = Gauge(gr, "V", LED_RED, size=132)
        self._pt_gi = Gauge(gr, "mA", LED_AMBER, size=132)
        self._pt_gv.pack(side="left")
        self._pt_gi.pack(side="left", padx=(16, 0))
        self.xgauges += [self._pt_gv, self._pt_gi]
        rc = self._card(right)
        rc.pack(fill="x", pady=(12, 0))
        self._caption(rc, tr("Uitslag")).pack(anchor="w", padx=14, pady=(10, 0))
        self._pt_kop = tk.Label(rc, text="", bg=CARD, fg=TEXT, font=(FONT_NUM, 19), anchor="w")
        self._pt_kop.pack(anchor="w", fill="x", padx=14)
        self._pt_meet = tk.Label(rc, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self._pt_meet.pack(anchor="w", padx=14)
        self._pt_uitleg = tk.Label(rc, text="", bg=CARD, fg=INK, font=(FONT, 10), justify="left", anchor="nw",
                                   wraplength=px(420), height=3)
        self._pt_uitleg.pack(anchor="w", fill="x", padx=14, pady=(4, 0))
        self._pt_scale = tk.Canvas(rc, width=px(420), height=px(56), bg=CARD, highlightthickness=0)
        self._pt_scale.pack(padx=14, pady=(6, 2))
        self._pt_plot = tk.Canvas(rc, width=px(420), height=px(104), bg=GLASS, highlightthickness=0)
        self._pt_plot.pack(padx=14, pady=(2, 14))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=14)
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._part_select(self._pt_sel, force=True)

    def _part_alive(self):
        win = getattr(self, "_ptwin", None)
        try:
            return bool(win and win.winfo_exists())
        except tk.TclError:
            return False

    def _part_select(self, key, force=False):
        if self.part and not force:
            return                  # niet wisselen tijdens een meting
        self._pt_sel = key
        if not self._part_alive():
            return
        for k, card in self._pt_cards.items():
            card.config(highlightbackground=BLUE if k == key else LINE)
        self._pt_how.config(text=PART_MODES[key]["hoe"])
        self._part_schematic(key)
        self._part_refresh()

    def _part_schematic(self, mode):
        """Tekening: rode en zwarte klem met het onderdeel ertussen, in de goede richting."""
        cv = self._pt_cv
        cv.delete("all")
        W, H = int(cv.cget("width")), int(cv.cget("height"))
        y, cx = H * 0.44, W / 2
        xr, xb, r = px(48), W - px(48), px(15)
        cv.create_line(xr + r, y, xb - r, y, fill=MUTED, width=px(2))
        for x, col, lab, sign in ((xr, LED_RED, tr("rode klem"), "+"), (xb, "#22262D", tr("zwarte klem"), "-")):
            cv.create_oval(x - r, y - r, x + r, y + r, fill=col, outline=lighten(col, 0.25), width=px(2))
            cv.create_text(x, y - px(1), text=sign, fill="#FFFFFF", font=(FONT_NUM, 13))
            cv.create_text(x, y + r + px(12), text=lab, fill=MUTED, font=(FONT, 9))
        s = px(15)
        if mode == "weerstand":
            cv.create_rectangle(cx - px(36), y - px(11), cx + px(36), y + px(11), fill=GLASS, outline=TEXT, width=px(2))
            cv.create_text(cx, y - px(26), text=tr("1 tot 200 Ω"), fill=TEXT, font=(FONT, 9))
            cv.create_text(cx, y + px(30), text=tr("de richting maakt niet uit"), fill=MUTED, font=(FONT, 9))
            return
        fwd = mode == "diode"            # driehoek wijst naar de zwarte klem (doorlaatrichting)
        tri = (cx - s, y - s, cx - s, y + s, cx + s, y) if fwd else (cx + s, y - s, cx + s, y + s, cx - s, y)
        bx = cx + s if fwd else cx - s
        cv.create_polygon(*tri, fill=TEXT, outline=TEXT)
        cv.create_line(bx, y - s, bx, y + s, fill=TEXT, width=px(3))
        for k in (0, px(9)):             # pijltjes: zo ziet een led eruit
            cv.create_line(cx + px(2) + k, y - s - px(2), cx + px(12) + k, y - s - px(12), fill=LED_AMBER,
                           width=px(1.5), arrow="last", arrowshape=(px(5), px(6), px(2)))
        left_t, right_t = (tr("anode (lange poot)"), tr("kathode (streep)")) if fwd else (tr("kathode (streep)"), tr("anode"))
        cv.create_text(cx - s - px(14), y - px(16), text=left_t, fill=TEXT, font=(FONT, 9), anchor="e")
        cv.create_text(cx + s + px(14), y - px(16), text=right_t, fill=TEXT, font=(FONT, 9), anchor="w")
        cv.create_text(cx, y + px(32), text=tr("streep naar de zwarte klem") if fwd else
                       tr("streep naar de rode klem (sperrichting)"), fill=MUTED, font=(FONT, 9))

    def _part_start(self, mode):
        if self.part:
            return False
        par = self._ptwin if self._part_alive() else self
        if not self.dev:
            messagebox.showinfo(tr("Niet verbonden"), tr("Verbind eerst met de voeding."), parent=par)
            return False
        if self.night:
            messagebox.showinfo(tr("Nachttest loopt"), tr("Stop eerst de nachttest; die gebruikt de uitgang."), parent=par)
            return False
        m = PART_MODES[mode]
        if not messagebox.askyesno(
                tr("Onderdeel meten"), tr("{0}: de uitgang gaat uit, dan een paar seconden aan met {1}, en daarna "
                                      "weer uit. Je instellingen komen terug.\n\nZit alleen het losse onderdeel "
                                      "aan de klemmen, niet de print?", m['naam'], m['kort']), icon="warning", parent=par):
            return False
        msg = tr("Gestopt: onderdeel meten")
        self._stop_program(msg)
        self._stop_sim(msg)
        self._stop_new(msg)
        now = time.time()
        v0, i0 = m["v"], m["i"]
        self.part = {"id": now, "t0": now, "mode": mode, "phase": "meet", "t_meet": now,
                     "ccs": [], "v_back": self.vset, "i_back": self.iset}
        self._pt_msg = ""
        for cmd in ("OUT0", f"ISET1:{i0:.3f}", f"VSET1:{v0:.2f}", "OUT1"):    # eerst de stroomgrens, dan de spanning
            self.cmdq.put(cmd)
        self._add_marker(tr("onderdeel meten: {0}, {1}", m['naam'].lower(), m['kort']))
        self.after(600, lambda: self._part_tick(now))
        self._part_refresh()
        return True

    def _part_window(self, t_from, now):
        """Metingen van de laatste seconde (vanaf t_from) en of ze stil staan."""
        w = in_window(self.hist, max(now - 1.0, t_from), now)
        if len(w) < 3:
            return w, False
        vs, cs = [x[1] for x in w], [x[2] for x in w]
        return w, (max(vs) - min(vs) <= max(0.03, 0.004 * max(vs)) and
                   max(cs) - min(cs) <= max(0.0015, 0.02 * max(cs)))

    def _part_tick(self, pid):
        p = self.part
        if not p or p["id"] != pid:
            return
        m = PART_MODES[p["mode"]]
        now = time.time()
        w, stable = self._part_window(p["t_meet"] + 0.8, now)
        if (stable and now - p["t_meet"] > 1.6) or now - p["t0"] > m["timeout"]:
            self._part_finish(w, stable)
            return
        self._part_refresh()
        self.after(250, lambda: self._part_tick(pid))

    def _part_restore(self, p):
        """Uitgang uit en de vorige instellingen terug (eerst de stroomgrens, dan de spanning)."""
        vmax, imax = self._limits()
        self.cmdq.put("OUT0")
        if p["i_back"] is not None:
            self.cmdq.put(f"ISET1:{min(p['i_back'], imax):.3f}")
        if p["v_back"] is not None:
            self.cmdq.put(f"VSET1:{min(p['v_back'], vmax):.2f}")

    def _part_finish(self, w, stable):
        p = self.part
        self.part = None
        self._part_restore(p)
        m = PART_MODES[p["mode"]]
        now = time.time()
        pts = [(t - p["t0"], v, i) for t, v, i in in_window(self.hist, p["t0"], now)]
        if not w:
            kop, uitleg, v, i, cc = tr("Geen meting"), tr("De voeding gaf geen metingen; is hij nog verbonden?"), None, None, False
        else:
            v, i = sum(x[1] for x in w) / len(w), sum(x[2] for x in w) / len(w)
            flags = [c for t, c in p["ccs"] if w[0][0] <= t <= w[-1][0]]
            cc = bool(flags) and sum(flags) * 2 >= len(flags)
            kop, uitleg = part_verdict(p["mode"], v, i, cc)
            if not stable:
                uitleg += tr(" De meting werd niet helemaal stil; meet voor de zekerheid nog een keer.")
        res = {"t": now, "mode": p["mode"], "v": v, "i": i, "cc": cc, "kop": kop, "uitleg": uitleg, "pts": pts}
        self.parts.append(res)
        del self.parts[:-20]
        self._parts_seq += 1
        meet = "" if v is None else f"{nlf(v, 2)} V, {nlf(i * 1000, 0)} mA, {'CC' if cc else 'CV'}"
        self._add_marker(tr("onderdeel ({0}): {1}", m['naam'].lower(), kop))
        self._wb_add("onderdeel", f"{m['naam']}: {kop}", about=tr("{0} Gemeten: {1}.", uitleg, meet) if meet else uitleg)
        self._say(kop)
        self._part_refresh()

    def _part_stop(self, msg):
        p = self.part
        if not p:
            return
        self.part = None
        self._part_restore(p)
        self._pt_msg = msg
        self._add_marker(tr("onderdeel meten: {0}", msg[0].lower() + msg[1:]))
        self._part_refresh()

    def _part_refresh(self):
        if not self._part_alive():
            return
        running = self.part is not None
        self._pt_btn.config(text=tr("Stop") if running else tr("Meten"), bg=BTN_RED if running else BLUE)
        tree = self._pt_tree
        if self._parts_seq != self._pt_seen:          # nieuwe meting: lijst opnieuw, nieuwste bovenaan
            self._pt_seen = self._parts_seq
            tree.delete(*tree.get_children())
            for n in range(len(self.parts) - 1, -1, -1):
                r = self.parts[n]
                tree.insert("", "end", iid=str(n), values=(f"{datetime.fromtimestamp(r['t']):%H:%M:%S}",
                                                           PART_MODES[r["mode"]]["naam"], r["kop"]))
        if running:
            p = self.part
            mode = p["mode"]
            now = time.time()
            last = self.hist[-1] if self.hist and self.hist[-1][0] >= p["t0"] else None
            what = tr("meten")
            self._pt_state.config(text=tr("Bezig: {0}, {1} s", what, nlf(now - p['t0'], 0)), fg=LED_AMBER)
            self._pt_kop.config(text=tr("Bezig..."), fg=MUTED)
            self._pt_meet.config(text=tr("nu {0} V, {1} mA", nlf(last[1], 2), nlf(last[2] * 1000, 0)) if last else "")
            self._pt_uitleg.config(text=tr("Het paneel wacht tot de spanning en de stroom stil staan; daarna "
                                           "gaat de uitgang vanzelf uit."))
            pts = [(t - p["t0"], v, i) for t, v, i in in_window(self.hist, p["t0"], now)]
            self._part_gauges(mode, last[1] if last else 0.0, last[2] if last else 0.0)
            self._part_scale(mode, None)
            self._part_plot(mode, pts)
            return
        sel = tree.selection()
        res = self.parts[int(sel[0])] if sel and int(sel[0]) < len(self.parts) else (self.parts[-1] if self.parts
                                                                                     else None)
        self._pt_state.config(text=getattr(self, "_pt_msg", "") or "", fg=MUTED)
        if not res:
            self._pt_kop.config(text=tr("Nog geen meting"), fg=MUTED)
            self._pt_meet.config(text="")
            self._pt_uitleg.config(text=tr("Kies hierboven wat je meet, sluit het onderdeel aan zoals op de "
                                           "tekening en klik op Meten."))
            self._part_gauges(self._pt_sel, 0.0, 0.0, idle=True)
            self._part_scale(self._pt_sel, None)
            self._part_plot(self._pt_sel, [])
            return
        mode = res["mode"]
        good = res["kop"] not in (tr("Kortsluiting"), tr("Geen stroom"), tr("Geen meting"))
        self._pt_kop.config(text=res["kop"], fg=GOOD if good else LED_AMBER)
        self._pt_meet.config(text=(f"{datetime.fromtimestamp(res['t']):%H:%M:%S}  {PART_MODES[mode]['naam']}:  "
                                   f"{nlf(res['v'], 2)} V, {nlf(res['i'] * 1000, 0)} mA, "
                                   f"{tr("stroom begrensd (CC)") if res['cc'] else tr("spanning vast (CV)")}")
                             if res["v"] is not None else "")
        self._pt_uitleg.config(text=res["uitleg"])
        self._part_gauges(mode, res["v"] or 0.0, res["i"] or 0.0)
        value = None
        if res["v"] is not None:
            value = res["v"] if mode != "weerstand" else (res["v"] / res["i"] if res["i"] >= 0.0015 and
                                                          res["v"] >= 0.02 else None)
        self._part_scale(mode, value)
        self._part_plot(mode, res["pts"])

    def _part_gauges(self, mode, v, i, idle=False):
        vmax, imax = self.PT_GAUGE[mode]
        lim = PART_MODES[mode]["i"] * 1000
        self._pt_gv.set_scale(vmax)
        self._pt_gi.set_scale(imax, mark=lim, redzone=(lim * 0.95, imax))
        self._pt_gv.target, self._pt_gi.target = min(v, vmax), min(i * 1000, imax)
        self._pt_gv.show("--" if idle else nlf(v, 2))
        self._pt_gi.show("--" if idle else nlf(i * 1000, 0))

    def _part_scale(self, mode, value):
        """Schaal met de zones (bijvoorbeeld silicium of led) en een pijl op de uitslag."""
        cv = self._pt_scale
        cv.delete("all")
        W = int(cv.cget("width"))
        lo, hi, log, zones = PART_SCALES[mode]
        L, R = px(6), W - px(6)

        def X(x):
            x = max(lo, min(hi, x))
            f = math.log10(x / lo) / math.log10(hi / lo) if log else (x - lo) / (hi - lo)
            return L + (R - L) * f

        yb, hb = px(18), px(15)
        cv.create_rectangle(L, yb, R, yb + hb, fill=CARD_2, outline="")
        for a, b, txt, col in zones:
            if THEMA == "licht":          # de zonekleuren zijn voor een donkere achtergrond gemaakt
                col = blend(col, "#FFFFFF", 0.62)
            cv.create_rectangle(X(a), yb, X(b), yb + hb, fill=col, outline="")
            if txt and X(b) - X(a) > px(9) * len(txt) * 0.62:
                cv.create_text((X(a) + X(b)) / 2, yb + hb / 2, text=txt, fill=TEXT, font=(FONT, 8))
        ticks = ([(1, "1 Ω"), (10, "10 Ω"), (100, "100 Ω"), (1000, "1 kΩ")] if log else
                 [(k, f"{k} V") for k in (range(0, 5) if mode == "diode" else range(14, 23, 2))])
        for k, (val, lab) in enumerate(ticks):
            x = X(val)
            cv.create_line(x, yb + hb, x, yb + hb + px(4), fill=DIM)
            anchor = "w" if x - L < px(10) else ("e" if R - x < px(10) else "center")
            cv.create_text(x, yb + hb + px(12), text=lab, fill=MUTED, font=(FONT, 8), anchor=anchor)
        if value is not None:
            x = X(value)
            cv.create_polygon(x - px(7), yb - px(11), x + px(7), yb - px(11), x, yb + px(2), fill=TEXT, outline="")
            lab = (f"{nlf(value, 2 if value < 10 else 1 if value < 100 else 0)} Ω" if mode == "weerstand"
                   else f"{nlf(value, 2 if mode == 'diode' else 1)} V")
            right = x < (L + R) / 2
            cv.create_text(x + (px(10) if right else -px(10)), yb - px(6), text=lab, fill=TEXT,
                           font=(FONT, 9, "bold"), anchor="w" if right else "e")
        else:
            cv.create_text(L, yb - px(6), text=tr("Schaal: waar valt de uitslag?"), fill=DIM, font=(FONT, 8), anchor="w")

    def _part_plot(self, mode, pts):
        """Spanning (rood) en stroom (oranje) tijdens de meting."""
        cv = self._pt_plot
        cv.delete("all")
        W, H = int(cv.cget("width")), int(cv.cget("height"))
        L, R, T, B = px(42), px(46), px(8), px(18)
        pw, ph = W - L - R, H - T - B
        vmax, imax = self.PT_GAUGE[mode]
        tmax = max(3.0, pts[-1][0] if pts else 3.0)
        for k in range(3):
            y = T + ph * k / 2
            cv.create_line(L, y, L + pw, y, fill=GRID)
            cv.create_text(L - px(5), y, text=nl(vmax * (1 - k / 2)) + (" V" if k == 0 else ""), fill=LED_RED,
                           anchor="e", font=(FONT, 8))
            cv.create_text(L + pw + px(5), y, text=nl(imax * (1 - k / 2)) + (" mA" if k == 0 else ""), fill=LED_AMBER,
                           anchor="w", font=(FONT, 8))
        cv.create_text(L, H - px(2), text="0 s", fill=MUTED, anchor="sw", font=(FONT, 8))
        cv.create_text(L + pw, H - px(2), text=f"{nlf(tmax, 0)} s", fill=MUTED, anchor="se", font=(FONT, 8))
        if len(pts) < 2:
            cv.create_text(L + pw / 2, T + ph / 2, text=tr("spanning en stroom tijdens de meting"), fill=DIM, font=(FONT, 9))
            return
        X = lambda t: L + pw * t / tmax
        cv.create_line(*[c for t, v, i in pts for c in (X(t), T + ph * (1 - min(i * 1000 / imax, 1)))],
                       fill=LED_AMBER, width=px(1.5))
        cv.create_line(*[c for t, v, i in pts for c in (X(t), T + ph * (1 - min(v / vmax, 1)))],
                       fill=LED_RED, width=px(2))

    # ---------- werkboek
    def _wb_add(self, kind, title, path=None, about="", t=None):
        """Regel in het werkboek: soort, titel, eventueel een bestand, en een korte uitleg."""
        e = {"t": t or time.time(), "soort": kind, "titel": str(title)[:160],
             "pad": str(Path(path).resolve()) if path else "", "uitleg": str(about or "")[:700]}
        self.wb.append(e)
        del self.wb[:-500]
        save_workbook(self.wb)
        self._wb_refresh()
        return e

    def _wb_scan(self):
        """Rapporten en logs die al in de mappen staan (ook van voor het werkboek) erbij zetten."""
        known = {e["pad"].lower() for e in self.wb if e.get("pad")}
        added = 0
        for folder, pattern in ((REPORT_DIR, "*.html"), (LOG_DIR, "*.csv")):
            try:
                files = sorted(folder.glob(pattern))
            except OSError:
                continue
            for f in files:
                p = str(f.resolve())
                if p.lower() in known:
                    continue
                kind = "log" if f.suffix.lower() == ".csv" else next(
                    (k for k in ("nachttest", "vergelijking") if f.stem.startswith(k + "_")),
                    "rapport")
                try:
                    t = f.stat().st_mtime
                except OSError:
                    continue
                self.wb.append({"t": t, "soort": kind, "titel": f.name, "pad": p,
                                "uitleg": tr("gevonden in de map {0}", folder.name)})
                known.add(p.lower())
                added += 1
        if added:
            self.wb.sort(key=lambda e: e["t"])
            del self.wb[:-500]
            save_workbook(self.wb)
        return added

    def _open_workbook(self):
        win = self._toplevel("_wbwin", tr("Werkboek"))
        if not win:
            return
        self._wb_scan()
        self._kop(win, tr("Werkboek")).pack(anchor="w", padx=22,
                                                                                     pady=(18, 2))
        tk.Label(win, bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", wraplength=px(940),
                 text=tr("Alles wat je met het paneel hebt gemeten, op datum: onderdelen, opstartcurves, "
                         "testprogramma's, rapporten en logs. Dubbelklik op een regel om hem te openen: een log "
                         "komt in de grafiek van het paneel, een rapport in de browser.")).pack(anchor="w", padx=22)
        cc = self._card(win)
        cc.pack(fill="x", padx=22, pady=(12, 0))
        self._caption(cc, tr("Activiteit, laatste 30 dagen")).pack(anchor="w", padx=14, pady=(10, 0))
        self._wb_chart = tk.Canvas(cc, width=px(920), height=px(118), bg=CARD, highlightthickness=0)
        self._wb_chart.pack(padx=14, pady=(4, 10))
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=22, pady=(12, 6))
        tk.Label(row, text=tr("Soort"), bg=PANEL, fg=INK, font=(FONT, 10)).pack(side="left")
        self._wb_kind = tk.StringVar(value=tr("Alles"))
        box = ttk.Combobox(row, textvariable=self._wb_kind, state="readonly", width=16, font=(FONT, 10),
                           values=[tr("Alles")] + [n for n, _ in WB_KINDS.values()])
        box.pack(side="left", padx=(8, 18))
        box.bind("<<ComboboxSelected>>", lambda e: self._wb_refresh())
        tk.Label(row, text=tr("Zoeken"), bg=PANEL, fg=INK, font=(FONT, 10)).pack(side="left")
        self._wb_q = self._entry(row, 24, size=10, justify="left")
        self._wb_q.pack(side="left", padx=(8, 0), ipady=2)
        self._wb_q.bind("<KeyRelease>", lambda e: self._wb_refresh())
        self._wb_count = tk.Label(row, text="", bg=PANEL, fg=MUTED, font=(FONT, 10))
        self._wb_count.pack(side="right")
        tf = tk.Frame(win, bg=PANEL)
        tf.pack(fill="x", padx=22)
        self._wb_tree = ttk.Treeview(tf, columns=("datum", "soort", "titel"), show="headings", height=10,
                                     selectmode="browse")
        for col, txt, w in (("datum", tr("Datum"), 150), ("soort", tr("Soort"), 130), ("titel", tr("Wat"), 620)):
            self._wb_tree.heading(col, text=txt, anchor="w")
            self._wb_tree.column(col, width=px(w), anchor="w", stretch=False)
        self._wb_tree.tag_configure("weg", foreground=DIM)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self._wb_tree.yview)
        self._wb_tree.configure(yscrollcommand=sb.set)
        self._wb_tree.pack(side="left")
        sb.pack(side="left", fill="y")
        self._wb_tree.bind("<<TreeviewSelect>>", self._wb_show)
        self._wb_tree.bind("<Double-1>", self._wb_open)
        self._wb_tree.bind("<Return>", self._wb_open)
        self._wb_detail = tk.Label(win, text="", bg=PANEL, fg=INK, font=(FONT, 10), justify="left", anchor="nw",
                                   wraplength=px(940), height=3)
        self._wb_detail.pack(anchor="w", fill="x", padx=22, pady=(8, 0))
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=22, pady=14)
        self._btn(bar, tr("Openen"), self._wb_open, bg=BLUE).pack(side="left")
        self._btn(bar, tr("Map openen"), self._wb_folder).pack(side="left", padx=(8, 0))
        self._btn(bar, tr("Notitie toevoegen"), self._wb_note).pack(side="left", padx=(8, 0))
        self._btn(bar, tr("Uit de lijst"), self._wb_remove).pack(side="left", padx=(8, 0))
        self._btn(bar, tr("Sluiten"), win.destroy).pack(side="right")
        self._wb_items = {}
        self._wb_refresh()

    def _wb_refresh(self):
        tree = getattr(self, "_wb_tree", None)
        try:
            if not (tree and tree.winfo_exists()):
                return
        except tk.TclError:
            return
        kind = next((k for k, (n, _) in WB_KINDS.items() if n == self._wb_kind.get()), None)
        q = self._wb_q.get().strip().lower()
        sel = tree.selection()
        keep = self._wb_items.get(sel[0]) if sel else None
        tree.delete(*tree.get_children())
        self._wb_items = {}
        rows = [e for e in reversed(self.wb) if not e.get("weg") and (kind is None or e["soort"] == kind)
                and (not q or q in f"{e['titel']} {e['uitleg']}".lower())]
        for n, e in enumerate(rows):
            iid = f"e{n}"
            self._wb_items[iid] = e
            missing = bool(e["pad"]) and not Path(e["pad"]).exists()
            tree.insert("", "end", iid=iid, tags=("weg",) if missing else (),
                        values=(f"{datetime.fromtimestamp(e['t']):%d-%m-%Y  %H:%M}", WB_KINDS.get(e["soort"],
                                                                                              (e["soort"],))[0],
                                e["titel"] + (tr("  (bestand weg)") if missing else "")))
            if e is keep:
                tree.selection_set(iid)
                tree.see(iid)
        total = sum(1 for e in self.wb if not e.get("weg"))
        self._wb_count.config(text=tr("{0} van {1} regels", len(rows), total) if len(rows) != total else tr("{0} regels", total))
        if not tree.selection():
            self._wb_detail.config(text=tr("Kies een regel; dubbelklik opent hem.") if rows else
                                   tr("Nog niets gevonden. Alles wat je meet komt hier vanzelf bij."), fg=MUTED)
        self._wb_draw_chart()

    def _wb_draw_chart(self):
        cv = getattr(self, "_wb_chart", None)
        try:
            if not (cv and cv.winfo_exists()):
                return
        except tk.TclError:
            return
        cv.delete("all")
        W, H = int(cv.cget("width")), int(cv.cget("height"))
        L, R, T, B = px(28), px(190), px(8), px(20)
        pw, ph = W - L - R, H - T - B
        today = datetime.now().date()
        days = [today - timedelta(days=k) for k in range(29, -1, -1)]
        counts = {d: {} for d in days}
        totals = {}
        for e in self.wb:
            if e.get("weg"):
                continue
            d = datetime.fromtimestamp(e["t"]).date()
            if d in counts:
                counts[d][e["soort"]] = counts[d].get(e["soort"], 0) + 1
                totals[e["soort"]] = totals.get(e["soort"], 0) + 1
        ymax = max(4, int(nice_ceil(max([sum(c.values()) for c in counts.values()] + [1]))))
        for k in range(3):
            y = T + ph * k / 2
            cv.create_line(L, y, L + pw, y, fill=GRID)
            cv.create_text(L - px(5), y, text=str(round(ymax * (1 - k / 2))), fill=MUTED, anchor="e", font=(FONT, 8))
        bw = pw / len(days)
        for n, d in enumerate(days):
            x0, x1 = L + n * bw + bw * 0.16, L + (n + 1) * bw - bw * 0.16
            y = T + ph
            for kind, (_, col) in WB_KINDS.items():
                c = counts[d].get(kind, 0)
                if c:
                    h = ph * c / ymax
                    cv.create_rectangle(x0, y - h, x1, y, fill=col, outline="")
                    y -= h
            if n % 7 == 1 or n == len(days) - 1:
                cv.create_text((x0 + x1) / 2, T + ph + px(10), text=tr("vandaag") if d == today else f"{d.day}-{d.month}",
                               fill=TEXT if d == today else MUTED, font=(FONT, 8))
        lx, ly = L + pw + px(22), T
        top = sorted(totals.items(), key=lambda kv: -kv[1])[:6]
        if not top:
            cv.create_text(lx, T + ph / 2, text=tr("nog niets in deze 30 dagen"), fill=DIM, anchor="w", font=(FONT, 9))
        for kind, c in top:
            name, col = WB_KINDS.get(kind, (kind, MUTED))
            cv.create_rectangle(lx, ly + px(3), lx + px(10), ly + px(13), fill=col, outline="")
            cv.create_text(lx + px(16), ly + px(8), text=f"{name}  {c}", fill=TEXT, anchor="w", font=(FONT, 9))
            ly += px(16)

    def _wb_selected(self):
        tree = getattr(self, "_wb_tree", None)
        try:
            sel = tree.selection() if tree else ()
        except tk.TclError:
            return None
        return self._wb_items.get(sel[0]) if sel else None

    def _wb_show(self, _e=None):
        e = self._wb_selected()
        if not e:
            return
        lines = [tr("{0}, {1} om {2:%H:%M}: {3}", WB_KINDS.get(e['soort'], (e['soort'],))[0], nl_date(e['t']), datetime.fromtimestamp(e['t']), e['titel'])]
        if e["uitleg"]:
            lines.append(e["uitleg"])
        if e["pad"]:
            lines.append(e["pad"] + ("" if Path(e["pad"]).exists() else tr("  (niet meer gevonden)")))
        self._wb_detail.config(text="\n".join(lines), fg=INK)

    def _wb_open(self, _e=None):
        e = self._wb_selected()
        if not e:
            return
        par = self._wbwin
        if not e["pad"]:
            messagebox.showinfo(tr("Geen bestand"), tr("Bij deze regel hoort geen bestand; wat er gemeten is staat "
                                                   "onder de lijst."), parent=par)
            return
        p = Path(e["pad"])
        if not p.exists():
            messagebox.showerror(tr("Bestand niet gevonden"), tr("{0}\n\nis verplaatst of verwijderd.", p), parent=par)
            return
        if p.suffix.lower() == ".csv" and e["soort"] == "log":
            self._open_log(str(p))
            self.lift()
        elif p.suffix.lower() == ".html":
            webbrowser.open(p.resolve().as_uri())
        else:
            try:
                os.startfile(str(p))
            except OSError as err:
                messagebox.showerror(tr("Kan niet openen"), str(err), parent=par)

    def _wb_folder(self):
        e = self._wb_selected()
        p = Path(e["pad"]) if e and e["pad"] else None
        try:
            if p and p.exists():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                folder = p.parent if p else REPORT_DIR
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(str(folder))
        except OSError as err:
            messagebox.showerror(tr("Kan de map niet openen"), str(err), parent=self._wbwin)

    def _wb_note(self):
        win = self._toplevel("_wbnwin", tr("Notitie toevoegen"))
        if not win:
            return
        self._kop(win, tr("Notitie toevoegen")).pack(anchor="w", padx=18,
                                                                                              pady=(14, 2))
        tk.Label(win, text=tr("De eerste regel wordt de titel. Bijvoorbeeld: wat je hebt gesoldeerd, wat je "
                              "opviel, of een meting met een multimeter."), bg=PANEL, fg=MUTED, font=(FONT, 10), wraplength=px(520),
                 justify="left").pack(anchor="w", padx=18)
        text = tk.Text(win, width=60, height=7, font=(FONT, 11), relief="flat", wrap="word", highlightthickness=1,
                       highlightbackground=LINE, highlightcolor=BLUE)
        text.pack(padx=18, pady=(8, 0))
        text.focus_set()

        def save():
            txt = text.get("1.0", "end").strip()
            win.destroy()
            if txt:
                self._wb_note_save(txt)

        bar = tk.Frame(win, bg=PANEL)
        bar.pack(fill="x", padx=18, pady=14)
        self._btn(bar, tr("Opslaan"), save, bg=BTN_GREEN).pack(side="right")
        self._btn(bar, tr("Annuleren"), win.destroy).pack(side="right", padx=(0, 8))

    def _wb_note_save(self, txt):
        first, _, rest = txt.strip().partition("\n")
        e = self._wb_add("notitie", first.strip()[:120] or tr("Notitie"), about=rest.strip())
        self._add_marker(tr("notitie: {0}", first.strip()[:60]))
        return e

    def _wb_remove(self):
        e = self._wb_selected()
        if not e:
            return
        if not messagebox.askyesno(tr("Uit de lijst"), tr("\"{0}\" uit het werkboek halen?\n\nHet bestand zelf blijft "
                                                      "staan.", e['titel']), parent=self._wbwin):
            return
        e["weg"] = True
        save_workbook(self.wb)
        self._wb_refresh()

    # ---------- vangnet
    def report_callback_exception(self, exc, val, tb):
        """Onverwachte fout in een knop of timer: vastleggen, lopende proeven stoppen en de uitgang uitzetten."""
        txt = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{txt}\n")
        except OSError:
            pass
        busy = bool(self.run or self.sim or self.curve or self.night or self.part)
        if busy:
            for stop in (lambda: self._stop_program(tr("Gestopt: fout in het paneel")),
                         lambda: self._stop_sim(tr("Gestopt: fout in het paneel")),
                         lambda: self._stop_new(tr("Gestopt: fout in het paneel")),
                         lambda: self._night_stop(tr("gestopt: fout in het paneel"))):
                try:
                    stop()
                except Exception:
                    pass
            self.run = self.sim = self.curve = self.night = self.part = None
            if self.dev:
                self.cmdq.put("OUT0")
        messagebox.showerror(tr("Fout in het paneel"),
                             tr("{0}: {1}\n\nDe details staan in {2}.", exc.__name__, val, ERROR_LOG.name)
                             + (tr("\n\nDe lopende proef is gestopt en de uitgang is uitgezet.") if busy else "")
                             + "\n\n" + tr("Wil je de fout melden? Onder Gereedschap staat Foutinformatie: daar staat "
                                           "alles wat nodig is."))

    # ---------- afsluiten
    def _on_close(self):
        if self.part and self.dev:          # onderdeelmeting: uitgang uit en de instellingen terug, direct
            p, self.part = self.part, None
            vmax, imax = self._limits()
            cmds = ["OUT0"] + ([f"ISET1:{min(p['i_back'], imax):.3f}"] if p["i_back"] is not None else []) + \
                   ([f"VSET1:{min(p['v_back'], vmax):.2f}"] if p["v_back"] is not None else [])
            for cmd in cmds:
                try:
                    self.dev.write(cmd)
                except Exception:
                    pass
            self.out = False
        if self.dev and self.out:
            ans = messagebox.askyesnocancel(
                tr("Uitgang staat aan"),
                tr("De uitgang van de voeding staat aan. Na het sluiten bewaakt het paneel hem niet meer (de "
                   "stroomgrens van de voeding zelf blijft wel werken).\n\nJa: uitgang uitzetten en sluiten.\nNee: "
                   "uitgang aan laten en sluiten.\nAnnuleren: paneel open laten."), icon="warning")
            if ans is None:
                return
            if ans:
                try:
                    self.dev.write("OUT0")
                except Exception:
                    pass
        self._night_stop(tr("gestopt: paneel gesloten"))
        self._web_stop(remember=False)
        self._api_stop()
        self._bench_sluit()
        self._mini_close()
        if self.log_file:
            self._log_close()
        if self.speaker:
            self.speaker.stop()
        self.running = False
        if self.dev:
            time.sleep(0.15)
            try:
                self.dev.close()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
