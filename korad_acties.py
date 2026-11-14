"""Opdrachten voor de lokale koppeling: het paneel bedienen zoals met de knoppen (november 2026).

Elke opdracht roept dezelfde functies aan als de knop in het paneel, dus met dezelfde grenzen en dezelfde
vragen op het scherm. Een opdracht loopt los van de aanvraag, want er kan een dialoog openstaan die op de gebruiker wacht;
de aanvrager krijgt een nummer en vraagt daarmee de uitslag op.

Regels:
- akkoord=True: alleen met "akkoord": true in de opdracht. Geldt voor alles wat de uitgang kan aanzetten of de
  spanning kan verhogen;
- stuurt=True: geweigerd zolang er een proef of nachttest loopt;
- bewust niet mogelijk: een hogere projectgrens kiezen, projecten of instellingen wijzigen, de bewaking uitzetten,
  de koppeling of telefoonbediening veranderen, en dialogen beantwoorden. Dat blijft aan de gebruiker.
"""
from __future__ import annotations

import korad_paden
from korad_demo import DEMO_POORT
from korad_taal import dec, tr

import ctypes
import io
import re
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PIL import Image

ACTIES = {}


class Weiger(Exception):
    """De opdracht mag of kan nu niet; de tekst is de reden."""


def actie(naam, tekst, akkoord=False, verbonden=False, stuurt=False):
    def plak(f):
        ACTIES[naam] = {"f": f, "tekst": tekst, "akkoord": akkoord, "verbonden": verbonden, "stuurt": stuurt}
        return f
    return plak


# ---------------------------------------------------------------- starten en uitslag
def lijst():
    return [{"naam": n, "tekst": a["tekst"], "akkoord": a["akkoord"]} for n, a in ACTIES.items()]


def start(app, d):
    """Hoofdthread. Controleert de opdracht, zet hem klaar en geeft meteen een nummer terug."""
    naam, info = d.get("actie"), ACTIES.get(d.get("actie"))
    if info is None:
        return 404, {"fout": tr("onbekende opdracht: {0}", naam)}
    if info["akkoord"] and d.get("akkoord") is not True:
        return 409, {"fout": tr("{0} kan alleen met akkoord", naam)}
    if info["verbonden"] and not app.dev:
        return 409, {"fout": tr("de voeding is niet verbonden")}
    if info["stuurt"]:
        b = app._bezig() or ("nachttest" if app.night else None)
        if b:
            return 409, {"fout": tr("er loopt een proef ({0})", b)}
    if app.actie_loopt and naam != "noodstop":      # de noodstop wacht nergens op
        return 409, {"fout": tr("er loopt nog een opdracht (staat er een vraag open in het paneel?)")}
    app.actie_nr += 1
    rec = {"id": app.actie_nr, "naam": naam, "status": "loopt", "uitslag": None, "t": time.time()}
    if naam != "noodstop":
        app.actie_loopt = rec
    app.acties_log.append(rec)
    app.after(0, lambda: _voer_uit(app, info, d, rec))
    return 202, {"id": rec["id"], "status": "loopt"}


def _voer_uit(app, info, d, rec):
    try:
        rec["uitslag"] = info["f"](app, d)
        rec["status"] = "klaar"
    except Weiger as e:
        rec.update(status="geweigerd", uitslag=str(e))
    except Exception as e:  # noqa: BLE001 - de fout hoort bij deze opdracht; het paneel moet gewoon doorlopen
        rec.update(status="fout", uitslag=f"{type(e).__name__}: {e}")
    finally:
        if app.actie_loopt is rec:
            app.actie_loopt = None


def uitslag(app, nr):
    return next((dict(r) for r in reversed(app.acties_log) if r["id"] == nr), None)


# ---------------------------------------------------------------- vensters en schermbeeld
def _vensters(app):
    return {"gereedschap": ("_xwin", app._open_tools), "projecten": ("_pjwin", app._open_projecten),
            "afdruk": ("_afwin", app._open_afdruk), "bewaking": ("_gwin", app._open_guards),
            "instellingen": ("_swin", app._open_settings), "testprogrammas": ("_pwin", app._open_programs),
            "opstartcurve": ("_cwin", app._open_curve), "nachttest": ("_nwin", app._open_night),
            "vergelijken": ("_vwin", app._open_compare), "telefoon": ("_twin", app._open_phone),
            "onderdelen": ("_ptwin", app._open_parts), "welkom": ("_welkomwin", app._open_welkom), "foutinfo": ("_fiwin", app._open_foutinfo),
            "werkboek": ("_wbwin", app._open_workbook)}


def _leeft(win):
    try:
        return win is not None and bool(win.winfo_exists())
    except Exception:  # noqa: BLE001 - tkinter gooit van alles als een venster net weg is
        return False


def venster_van(app, naam):
    """Het tk-venster met deze naam, of None als het niet open staat."""
    if naam == "hoofd":
        return app
    if naam == "mini":
        return app.mini["win"] if app.mini else None
    if naam == "werkbank":
        return app.bench["win"] if app.bench else None
    v = _vensters(app).get(naam)
    win = getattr(app, v[0], None) if v else None
    return win if _leeft(win) else None


def open_vensters(app):
    alle = ["hoofd", "mini", "werkbank", *_vensters(app)]
    return [n for n in alle if _leeft(venster_van(app, n))]


def foto_hwnd(hwnd, breed=None, kader=None):
    """PNG van een Windows-venster, ook als het bedekt is. Kader: (links, boven, breedte, hoogte) binnen het venster."""
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    im = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    if kader:
        x, y, kw, kh = kader
        im = im.crop((x, y, x + kw, y + kh))
    if breed and im.width > breed:
        im = im.resize((breed, round(im.height * breed / im.width)), Image.LANCZOS)
    uit = io.BytesIO()
    im.save(uit, "PNG", optimize=True)
    return uit.getvalue()


def scherm(app, naam, breed=None):
    """Hoofdthread: (status, png-bytes) van een venster van het paneel."""
    win = venster_van(app, naam or "hoofd")
    if not _leeft(win):
        return 404, {"fout": tr("venster {0} staat niet open", naam), "open": open_vensters(app)}
    win.update_idletasks()
    hwnd = int(win.wm_frame(), 16)
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    x, y = win.winfo_rootx() - r.left, win.winfo_rooty() - r.top
    return 200, foto_hwnd(hwnd, breed, (x, y, win.winfo_width(), win.winfo_height()))


def dialogen():
    """Open vragen van dit programma (Windows-dialogen), met hun tekst. Mag uit elke thread."""
    import os
    u32 = ctypes.windll.user32
    gevonden = []
    Teller = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def tekst_van(h):
        n = u32.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, b, n + 1)
        return b.value

    def bekijk(h, _l):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        klasse = ctypes.create_unicode_buffer(32)
        u32.GetClassNameW(h, klasse, 32)
        if pid.value == os.getpid() and klasse.value == "#32770" and u32.IsWindowVisible(h):
            delen = []

            def kind(c, _l2):
                k = ctypes.create_unicode_buffer(32)
                u32.GetClassNameW(c, k, 32)
                if k.value == "Static" and tekst_van(c):
                    delen.append(tekst_van(c))
                return True

            u32.EnumChildWindows(h, Teller(kind), 0)
            gevonden.append({"titel": tekst_van(h), "tekst": "\n".join(delen)})
        return True

    u32.EnumWindows(Teller(bekijk), 0)
    return gevonden


# ---------------------------------------------------------------- hulpjes
def _getal(d, naam, laag=None, hoog=None, standaard=None):
    w = d.get(naam, standaard)
    try:
        x = float(str(w).replace(",", "."))
    except (TypeError, ValueError):
        raise Weiger(tr("{0} is geen getal", naam)) from None
    if x != x or (laag is not None and x < laag) or (hoog is not None and x > hoog):
        raise Weiger(tr("{0} moet tussen {1} en {2} liggen", naam, laag, hoog))
    return x


def _naam_in(map_, naam, patroon):
    """Alleen een naam uit de map zelf: geen paden."""
    naam = str(naam or "")
    for f in sorted(Path(map_).glob(patroon)):
        if f.stem == naam or f.name == naam:
            return f
    raise Weiger(tr("niet gevonden in {0}: {1}", Path(map_).name, naam))


def _eigen_afdruk(app, naam):
    a = next((x for x in app.afdrukken if x["naam"] == naam and x.get("project") == app.settings["project"]), None)
    if a is None:
        raise Weiger(tr("geen afdruk {0} in dit project", naam))
    return a


def _start_of_weiger(app):
    s = app._afdruk_laatste_start()
    if not s:
        raise Weiger(tr("nog geen bruikbare start van minstens 3 seconden"))
    return s


# ---------------------------------------------------------------- vensters
@actie("venster_open", tr("Een venster openen (venster=gereedschap, projecten, afdruk, bewaking, ...)"))
def _(app, d):
    v = _vensters(app).get(d.get("venster"))
    if v is None:
        raise Weiger(tr("onbekend venster; kies uit {0}", ', '.join(_vensters(app))))
    v[1]()
    return {"open": open_vensters(app)}


@actie("venster_dicht", tr("Een venster sluiten, zoals met het kruisje"))
def _(app, d):
    if d.get("venster") == "hoofd":
        raise Weiger(tr("het hoofdvenster sluit de gebruiker zelf"))
    win = venster_van(app, d.get("venster"))
    if not _leeft(win):
        raise Weiger(tr("dat venster staat niet open"))
    h = win.protocol("WM_DELETE_WINDOW")
    if h:
        win.tk.call(h)
    else:
        win.destroy()
    return {"open": open_vensters(app)}


@actie("werkbank", tr("Werkbankstand aan of uit"))
def _(app, d):
    app._toggle_bench()
    return {"aan": app.bench is not None}


@actie("mini", tr("Mini-venster aan of uit"))
def _(app, d):
    app._toggle_mini()
    return {"aan": app.mini is not None}


@actie("bediening", tr("Eenvoudige of uitgebreide bediening wisselen"))
def _(app, d):
    app._wissel_bediening()
    return {"uitgebreid": bool(app.settings["uitgebreid"])}


# ---------------------------------------------------------------- verbinding, grafiek, log, rapport
@actie("verbinden", tr("Verbinden met de voeding (poort=COM10, optioneel)"))
def _(app, d):
    if app.dev:
        raise Weiger(tr("al verbonden"))
    app._refresh_ports()
    if d.get("poort"):
        keuze = next((x for x in app.port_box["values"] if x.split()[0] == d["poort"]), None)
        if keuze is None:
            raise Weiger(tr("poort {0} niet gevonden", d['poort']))
        app.port_var.set(keuze)
    if app.port_var.get().startswith(DEMO_POORT) and not korad_paden.DEMO:
        raise Weiger(tr("de demo start je in het paneel zelf"))
    app._connect()
    return {"verbonden": bool(app.dev)}


@actie("verbreken", tr("Verbinding verbreken; de uitgang blijft zoals hij staat"), akkoord=True, verbonden=True)
def _(app, d):
    app._disconnect(tr("Verbinding verbroken"))
    return {"verbonden": False}


@actie("grafiek_span", tr("Grafiek live: sec=60, 300 of 1800"))
def _(app, d):
    s = int(_getal(d, "sec", 60, 1800))
    if s not in (60, 300, 1800):
        raise Weiger(tr("kies 60, 300 of 1800"))
    app.span.set(s)
    app._go_live()
    return {"sec": s}


@actie("grafiek_zoom", tr("Inzoomen: van en tot in seconden geleden"))
def _(app, d):
    van, tot = _getal(d, "van", 1), _getal(d, "tot", 0, standaard=0)
    if tot >= van:
        raise Weiger(tr("van moet verder terug liggen dan tot"))
    nu = time.time()
    app.view = (nu - van, nu - tot)
    app._draw_chart()
    return {"van": van, "tot": tot}


@actie("grafiek_live", tr("Terug naar live"))
def _(app, d):
    app._back_to_live()
    app._go_live()
    return {}


@actie("log_openen", tr("Een bewaard log in de grafiek zetten (naam uit de map logs)"))
def _(app, d):
    app._open_log(str(_naam_in(app.kp.LOG_DIR, d.get("naam"), "*.csv")))
    return {"open": app.src["name"] if app.src else None}


@actie("log_start", tr("Log starten in de map logs (naam optioneel)"), verbonden=True)
def _(app, d):
    if app.log_file:
        raise Weiger(tr("er loopt al een log"))
    naam = re.sub(r"[^\w.-]+", "_", str(d.get("naam") or f"korad_{datetime.now():%Y%m%d_%H%M%S}"))
    app.kp.LOG_DIR.mkdir(parents=True, exist_ok=True)
    pad = app.kp.LOG_DIR / (naam if naam.endswith(".csv") else naam + ".csv")
    if pad.exists():
        raise Weiger(tr("{0} bestaat al", pad.name))
    app._log_open(pad)
    return {"pad": str(pad)}


@actie("log_stop", tr("Log stoppen"))
def _(app, d):
    if not app.log_file:
        raise Weiger(tr("er loopt geen log"))
    app._log_close()
    return {"regels": app.log_rows}


@actie("rapport", tr("Rapport maken van wat in de grafiek staat (titel, opmerking)"))
def _(app, d):
    t0, t1 = app._view_range()
    app.kp.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pad = app.kp.REPORT_DIR / f"rapport_{datetime.now():%Y%m%d_%H%M%S}.html"
    uit = app._make_report(str(d.get("titel") or tr("Testrapport"))[:120], str(d.get("opmerking") or "")[:2000], t0, t1,
                           path=pad, open_browser=False)
    if not uit:
        raise Weiger(tr("te weinig metingen in de grafiek"))
    return {"pad": str(uit)}


@actie("teller_nul", tr("Verbruik en herstarts op nul"))
def _(app, d):
    app._reset_energy()
    return {}


@actie("notitie", tr("Notitie in het werkboek en de grafiek (tekst)"))
def _(app, d):
    tekst = str(d.get("tekst") or "").strip()
    if not tekst:
        raise Weiger(tr("geen tekst"))
    app._wb_note_save(tekst[:700])
    return {}


# ---------------------------------------------------------------- voeding
@actie("noodstop", tr("Noodstop: uitgang uit en alles stoppen"), verbonden=True)
def _(app, d):
    app._emergency_stop("koppeling")
    return {}


@actie("alarm_wissen", tr("Een alarm wissen"), akkoord=True)
def _(app, d):
    app._clear_alarm()
    return {}


@actie("geheugen", tr("Geheugenknop indrukken (n=1 tot 4)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    n = int(_getal(d, "n", 1, 4))
    app._recall(n)
    return {"n": n}


@actie("project", tr("Project kiezen; alleen met een gelijke of lagere grens"))
def _(app, d):
    k = d.get("sleutel")
    p = app.kp.PROJECTS.get(k)
    if p is None:
        raise Weiger(tr("onbekend project; kies uit {0}", ', '.join(app.kp.PROJECTS)))
    nu = app.kp.PROJECTS[app.settings["project"]]
    if k == "vrij" or p["vmax"] > nu["vmax"] or p["imax"] > nu["imax"]:
        raise Weiger(tr("een hogere grens kiest de gebruiker zelf"))
    app._kies_project(k)
    return {"project": app.settings["project"]}


@actie("bewaking_aan", tr("Een bewakingsregel aanzetten (regel=1 tot 3); uitzetten doet de gebruiker"))
def _(app, d):
    n = int(_getal(d, "regel", 1, len(app.guards)))
    nieuw = [dict(g) for g in app.guards]
    nieuw[n - 1]["aan"] = True
    app._bewaking_bewaar(nieuw)
    return {"regel": n}


# ---------------------------------------------------------------- proeven (het paneel vraagt zelf om bevestiging)
@actie("programma_lijst", tr("Welke testprogramma's er zijn"))
def _(app, d):
    return {"programmas": sorted(f.stem for f in app.kp.PROG_DIR.glob("*.json") if f.stem != "laatste")}


@actie("programma_start", tr("Testprogramma starten (naam)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    import json
    data = json.loads(_naam_in(app.kp.PROG_DIR, d.get("naam"), "*.json").read_text(encoding="utf-8"))
    if not isinstance(data.get("stappen"), list):
        raise Weiger(tr("dit bestand is geen testprogramma"))
    app.program = data
    return {"gestart": bool(app._start_program(data))}


@actie("programma_stop", tr("Testprogramma stoppen, uitgang uit"))
def _(app, d):
    app._stop_program(tr("Gestopt"), off=True)
    return {}


@actie("accu_start", tr("Accu nabootsen (van, naar, minuten, r in milliohm)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    waarden = ((app.sim_from, _getal(d, "van", 0)), (app.sim_to, _getal(d, "naar", 0)),
               (app.sim_min, _getal(d, "minuten", 0)), (app.sim_r, _getal(d, "r", 0, 1000, 0)))
    for e, w in waarden:
        e.delete(0, "end")
        e.insert(0, dec(str(w)))
    app._toggle_sim()
    return {"gestart": bool(app.sim)}


@actie("accu_stop", tr("Accu nabootsen stoppen"))
def _(app, d):
    app._stop_sim(tr("Gestopt"))
    return {}


@actie("opstartcurve", tr("Opstartcurve (v, i, stap)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    v, i, stap = _getal(d, "v", 0.5), _getal(d, "i", 0.001), _getal(d, "stap", 0.05, 2.0, 0.2)
    kp = app.kp
    if not kp.messagebox.askyesno(tr("Opstartcurve"), tr("Na afloop blijft de uitgang aan op {0} V.", kp.nl(v)) + "\n\n" +
                                  tr("De uitgang gaat uit; daarna loopt de spanning van 0 naar "
                                                     "{0} V in stappen van {1} V, met een stroomgrens van {2} "
                                                     "A.\n\nStarten?", kp.nl(v), kp.nl(stap), kp.nl(i))):
        return {"gestart": False}
    return {"gestart": bool(app._curve_start(v, i, step_v=stap, dwell=0.5, label=tr("opstartcurve")))}


@actie("curve_stop", tr("Opstartcurve stoppen"))
def _(app, d):
    app._curve_stop(tr("Gestopt"))
    return {}


@actie("onderdeel", tr("Onderdeel meten (soort=diode of weerstand)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    soort = d.get("soort")
    if soort not in app.kp.PART_MODES:
        raise Weiger(tr("kies uit {0}", ', '.join(app.kp.PART_MODES)))
    if not _leeft(venster_van(app, "onderdelen")):
        app._open_parts()
    app._part_select(soort)
    return {"gestart": bool(app._part_start(soort))}


@actie("nachttest", tr("Nachttest (uren, v, i, piek in mA)"), akkoord=True, verbonden=True, stuurt=True)
def _(app, d):
    app._night_cfg.update(uren=_getal(d, "uren", 0.01, 48), v=_getal(d, "v", 0), i=_getal(d, "i", 0),
                          piek=_getal(d, "piek", 1, 5000, app._night_cfg["piek"]))
    app._night_start(None)
    return {"gestart": bool(app.night)}


@actie("nacht_stop", tr("Nachttest stoppen"))
def _(app, d):
    app._night_stop(tr("gestopt via de koppeling"))
    return {}


# ---------------------------------------------------------------- stroomafdruk
@actie("afdruk_bewaar", tr("Laatste start bewaren als nieuwe afdruk (naam)"))
def _(app, d):
    naam = str(d.get("naam") or "").strip()[:60]
    if not naam:
        raise Weiger(tr("geen naam"))
    if any(a["naam"] == naam and a.get("project") == app.settings["project"] for a in app.afdrukken):
        raise Weiger(tr("die naam bestaat al in dit project"))
    app.afdrukken.append({"naam": naam, "project": app.settings["project"], "starts": [_start_of_weiger(app)],
                          "gemaakt": time.time()})
    app.kp.save_afdrukken(app.afdrukken)
    return {"naam": naam}


@actie("afdruk_toevoegen", tr("Laatste start toevoegen aan een afdruk (naam)"))
def _(app, d):
    a = _eigen_afdruk(app, d.get("naam"))
    a["starts"] = (a["starts"] + [_start_of_weiger(app)])[-app.kp.ana.AFDRUK_MAX_STARTS:]
    app.kp.save_afdrukken(app.afdrukken)
    return {"starts": len(a["starts"])}


@actie("afdruk_gebruik", tr("Afdruk in gebruik nemen (naam); zonder naam uit"))
def _(app, d):
    naam = d.get("naam") or ""
    if naam:
        _eigen_afdruk(app, naam)
    app.settings["afdruk_actief"] = naam
    app.kp.save_settings(app.settings)
    return {"actief": naam}
