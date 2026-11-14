"""Test of the Korad panel with a simulated power supply, in one language.

    py tests/proef_paneel.py [nl|en|de] [licht]         one language (default nl), about one minute

Opens every window, runs the main functions and writes screenshots to tests/afdrukken/. In English and German it also
looks for Dutch text that was not translated. Everything runs in a temporary folder; no real supply is needed and your
own settings are not touched.
"""
import ctypes
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path

TAAL = next((a for a in sys.argv[1:] if a in ("nl", "en", "de")), "nl")
os.environ["KORAD_TAAL"] = TAAL
LICHT = "licht" in sys.argv
os.environ["KORAD_THEMA"] = "licht" if LICHT else "donker"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHOTS = HERE / "afdrukken"
SHOTS.mkdir(exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="korad_test_"))
os.environ["KORAD_DATA"] = str(WORK)
sys.path.insert(0, str(ROOT))
import korad_paneel as kp  # noqa: E402
import korad_analyse as ana  # noqa: E402
import korad_klant  # noqa: E402
import korad_taal  # noqa: E402
from korad_taal import tr  # noqa: E402
from PIL import Image  # noqa: E402

kp.WEB_HOST = "127.0.0.1"
CATALOGUS = {} if TAAL == "nl" else json.loads((ROOT / "lang" / f"{TAAL}.json").read_text(encoding="utf-8"))
NL_WOORDEN = re.compile(r"\b(de|het|een|naar|voor|van|aan|uit|uitgang|klik|kies|hoogste|gemiddeld|sluiten|opslaan|voeding|grens"
                        r"|spanning|stroom)\b", re.IGNORECASE)
if TAAL == "de":
    NL_WOORDEN = re.compile(r"\b(de|het|een|naar|voor|van|aan|uit|uitgang|klik|kies|hoogste|gemiddeld|sluiten|opslaan|voeding|grens"
                            r"|spanning|stroom)\b")
T0 = time.time()
CHECKS, DIALOGEN, RESTEN = [], [], set()
FOUTEN_TK = []


def log(*a):
    print(f"[{time.time() - T0:5.1f}s]", *a, flush=True)


def check(naam, ok, detail=""):
    CHECKS.append((naam, bool(ok)))
    log(("GOOD " if ok else "FAIL ") + naam + (f"  ({detail})" if detail else ""))


# ------------------------------------------------------------------ simulated supply
STAND = {"model": "gewoon"}


def demand(v):
    m = STAND["model"]
    if m == "diode":
        return max(0.0, v - 0.60) * 0.2
    if m == "led":
        return max(0.0, v - 1.85) * 0.2
    if m == "diode_om":
        return 0.0
    if m == "r33":
        return v / 33.0
    if m == "kort":
        return v / 0.5
    return 0.15 if v > 0.5 else 0.0


class NepKorad(kp.Korad):
    def __init__(self, port=None):
        self.lock = threading.Lock()
        self.vset, self.iset, self.out = 7.0, 0.2, False
        self.idn, self.stil = b"KORAD KA3005PS V1.5 SN:TEST", False

    def close(self):
        pass

    def physics(self):
        if not self.out:
            return 0.0, 0.0, True
        d = demand(self.vset)
        if d > self.iset:
            if STAND["model"] in ("diode", "led", "diode_om", "r33"):
                lo, hi = 0.0, self.vset
                for _ in range(50):
                    mid = (lo + hi) / 2
                    if demand(mid) > self.iset:
                        hi = mid
                    else:
                        lo = mid
                return lo, self.iset, False
            return self.vset * self.iset / d, self.iset, False
        return self.vset, d, True

    def write(self, cmd):
        if cmd.startswith("VSET1:"):
            self.vset = float(cmd[6:])
        elif cmd.startswith("ISET1:"):
            self.iset = float(cmd[6:])
        elif cmd in ("OUT0", "OUT1"):
            self.out = cmd == "OUT1"
        time.sleep(0.005)

    def query(self, cmd, max_wait=0.5):
        time.sleep(0.005)
        v, i, cv = self.physics()
        if self.stil:
            return b""
        return {"*IDN?": self.idn, "VSET1?": f"{self.vset:05.2f}".encode(),
                "ISET1?": f"{self.iset:.3f}".encode(), "VOUT1?": f"{v:05.2f}".encode(),
                "IOUT1?": f"{i:.3f}".encode(),
                "STATUS?": bytes([(1 if cv else 0) | (0x40 if self.out else 0)])}.get(cmd, b"")


NEP = NepKorad()


class NepBox:
    def _rec(self, soort, titel, tekst, antwoord):
        DIALOGEN.append((soort, titel, tekst))
        kijk_tekst(titel)
        kijk_tekst(tekst)
        return antwoord

    def showinfo(self, t, m, **k):
        return self._rec("info", t, m, "ok")

    def showerror(self, t, m, **k):
        return self._rec("fout", t, m, "ok")

    def showwarning(self, t, m, **k):
        return self._rec("let op", t, m, "ok")

    def askyesno(self, t, m, **k):
        return self._rec("ja/nee", t, m, True)

    def askyesnocancel(self, t, m, **k):
        return self._rec("ja/nee/annuleren", t, m, True)


GESTART = []
kp.messagebox = NepBox()
kp.filedialog.asksaveasfilename = lambda **k: str(WORK / "uit.html")
kp.webbrowser.open = lambda *a, **k: None
kp.Korad = lambda port: NEP
kp.App._beep = lambda self, kind: None
kp.App._say = lambda self, text: None
kp.subprocess.Popen, ECHTE_POPEN = (lambda *a, **k: GESTART.append(a[0])), kp.subprocess.Popen

_api = __import__("socket").socket()
_api.bind(("127.0.0.1", 0))
kp.SETTINGS_DEFAULTS["api_poort"] = _api.getsockname()[1]
_api.close()
# The screenshots feed the manual, which shows the advanced layout without the welcome window in front.
kp.SETTINGS_DEFAULTS["uitgebreid"] = True
kp.SETTINGS_DEFAULTS["welkom_gezien"] = True

app = kp.App()
app.report_callback_exception = lambda *a: FOUTEN_TK.append("".join(traceback.format_exception(*a)))
u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32


def ui(f, *a, **k):
    """Voer f uit in de hoofdthread en wacht op de uitslag."""
    klaar, uit = threading.Event(), {}

    def doe():
        try:
            uit["r"] = f(*a, **k)
        except Exception as e:
            uit["e"] = e
            uit["tb"] = traceback.format_exc()
        klaar.set()
    app.after(0, doe)
    klaar.wait(30)
    if "e" in uit:
        FOUTEN_TK.append(uit["tb"])
        raise uit["e"]
    return uit.get("r")


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def foto(top, naam):
    top.update()
    hwnd = int(top.wm_frame(), 16)
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
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(SHOTS / f"{TAAL}{'_licht' if LICHT else ''}_{naam}.png")


def kijk_tekst(s):
    """Noteer tekst die nog Nederlands lijkt, in het Engels en Duits."""
    s = str(s or "").strip()
    if TAAL == "nl" or not s:
        return
    if s in CATALOGUS and CATALOGUS[s] != s:
        RESTEN.add("niet vertaald: " + s[:90])
    elif NL_WOORDEN.search(s) and s not in CATALOGUS.values():
        RESTEN.add("lijkt Nederlands: " + s[:90])


def kijk_widgets(w):
    for k in w.winfo_children():
        try:
            if k.winfo_class() == "Canvas":
                for item in k.find_all():
                    if k.type(item) == "text":
                        kijk_tekst(k.itemcget(item, "text"))
            elif "text" in k.keys():
                kijk_tekst(k.cget("text"))
            elif k.winfo_class() == "TCombobox":
                for v in k.cget("values"):
                    kijk_tekst(v)
            elif k.winfo_class() == "Treeview":
                for c in k.cget("columns"):
                    kijk_tekst(k.heading(c, "text"))
                for rij in k.get_children():
                    for x in k.item(rij, "values"):
                        kijk_tekst(x)
        except Exception:
            pass
        kijk_widgets(k)


def vensters():
    return [w for w in app.winfo_children() if w.winfo_class() == "Toplevel" and w.winfo_exists()]


def open_venster(opener, naam):
    voor = set(vensters())

    def doe():
        opener()
        app.update()
        app.update_idletasks()
        nieuw = [w for w in vensters() if w not in voor]
        for w in nieuw:
            kijk_widgets(w)
            foto(w, naam)
            w.destroy()
        return len(nieuw)
    n = ui(doe)
    check(f"window opens: {naam}", n >= 1)


def wacht(sec):
    time.sleep(sec)


def tot(voorwaarde, sec=15):
    t = time.time() + sec
    while time.time() < t:
        if ui(voorwaarde):
            return True
        time.sleep(0.1)
    return False


def proef():
    # ---- verbinden
    ui(lambda: (app.port_box.configure(values=["COM10  (USB Serial Device)"]),
                app.port_var.set("COM10  (USB Serial Device)"), app._connect()))
    check("connects", tot(lambda: bool(app.dev) and app.vset is not None))
    check("starts on the unrestricted project", app.settings["project"] == "vrij")
    check("only one built-in project", list(kp.PROJECTS) == ["vrij"], str(list(kp.PROJECTS)))
    ui(lambda: (kijk_widgets(app), foto(app, "hoofd")))

    # ---- taal
    ui(lambda: check("decimal separator follows the language", kp.nl(1.5) == ("1.5" if TAAL == "en" else "1,5"), kp.nl(1.5)))
    pagina = kp.web_pagina("abc")
    check("phone page has no open fields", "@@" not in pagina and "__TAAL__" not in pagina and "__KOMMA__" not in pagina)
    check("phone page in this language", f'<html lang="{TAAL}"' in pagina and tr("Spanning") in pagina)
    keuze = ui(lambda: kp.Keuze(app, ["boven", "onder"], state="readonly"))
    ui(keuze.set, "onder")
    check("choice list shows the translation", ui(lambda: keuze.cget("values")[1]) == tr("onder"))
    check("choice list keeps the fixed value", ui(keuze.get) == "onder")
    ui(keuze.destroy)

    # ---- alle vensters
    for opener, naam in ((app._open_tools, "gereedschap"), (app._open_projecten, "projecten"),
                         (app._open_settings, "instellingen"), (app._open_afdruk, "afdruk"),
                         (app._open_guards, "bewaking"), (app._open_programs, "programmas"),
                         (app._open_curve, "opstartcurve"), (app._open_night, "nachttest"),
                         (app._open_compare, "vergelijken"), (app._open_phone, "telefoon"),
                         (app._open_parts, "onderdelen"), (app._open_workbook, "werkboek"),
                         (app._wb_note, "notitie")):
        open_venster(opener, naam)

    # ---- instellen, uitgang
    r = ui(app._api_zet, {"v": 5.0, "i": 0.2})
    check("set 5 V", r[0] == 200, str(r))
    check("value arrives", tot(lambda: abs((app.vset or 0) - 5.0) < 0.01))
    r = ui(app._api_aan, {})
    check("output on refused without consent", r[0] == 409, str(r))
    r = ui(app._api_aan, {"akkoord": True})
    check("output on with consent", r[0] == 200, str(r))
    check("output is on", tot(lambda: bool(app.out)))
    wacht(1)
    ui(lambda: (kijk_widgets(app), foto(app, "hoofd_aan")))
    ui(app._api_uit)
    check("output is off", tot(lambda: not app.out))

    # ---- eigen project: grens en opslaan
    p = kp.schoon_project({"naam": "My board: max 5.5 V, 2 A", "kort": "My board", "kleur": "#A78BFA", "vmax": 5.5, "imax": 2.0})
    check("own project accepted", p is not None)

    def maak():
        kp.PROJECTS["bord"] = p
        kp.save_projects()
        app._kies_project("bord")
    ui(maak)
    check("own project chosen", app.settings["project"] == "bord")
    check("own project is saved", "bord" in kp.load_projects())
    r = ui(app._api_zet, {"v": 9.0, "i": 0.2})
    check("above the limit refused", r[0] == 422, str(r))
    NEP.vset = 7.0
    check("supply reading arrives", tot(lambda: abs((app.vset or 0) - 7.0) < 0.05))
    n = len(DIALOGEN)
    ui(app._toggle_out)
    check("button refuses output above the limit", not NEP.out and any(d[1] == tr("Buiten de grens") for d in DIALOGEN[n:]))
    r = ui(app._api_aan, {"akkoord": True})
    check("API refuses output above the limit", r[0] == 422 and not NEP.out, str(r))
    ui(app._api_zet, {"v": 5.0, "i": 0.2})
    tot(lambda: abs((app.vset or 0) - 5.0) < 0.05)

    # ---- bewaking en noodstop
    def bewaking():
        app.guards = [dict(g) for g in app.guards]
        app.guards[0].update(aan=True, wat="stroom", richting="boven", waarde=50.0, duur=0.3, actie="uitgang uit")
        app.guard_state = [{"since": None, "fired": False} for _ in app.guards]
    ui(bewaking)
    ui(app._api_aan, {"akkoord": True})
    check("guard fires", tot(lambda: bool(app.alarm), 8), str(app.alarm))
    check("guard turns output off", tot(lambda: not NEP.out, 5))
    ui(lambda: (kijk_widgets(app), foto(app, "alarm")))

    def stop_bewaking():
        app.guards[0]["aan"] = False
        app._clear_alarm()
    ui(stop_bewaking)
    ui(app._api_aan, {"akkoord": True})
    tot(lambda: bool(NEP.out), 5)
    ui(app._emergency_stop, "Esc")
    check("emergency stop", tot(lambda: not NEP.out, 3))
    ui(app._clear_alarm)

    # ---- testprogramma: banden en soorten uit de markeringen
    t_start = time.time()
    prog = {"naam": "Proef", "herhalen": 1, "uit_na_afloop": True, "stappen": [
        {"overgang": "sprong", "v": 5.0, "i": 0.2, "uit": "aan", "duur": 2.5, "verwacht": {"i_min": 100, "i_max": 200, "na": 1}},
        {"overgang": "sprong", "v": 4.0, "i": 0.2, "uit": "aan", "duur": 2.5, "verwacht": {"i_min": 900, "i_max": 1000, "na": 1}}]}
    ui(app._start_program, prog)
    check("test program starts", ui(lambda: bool(app.run)))
    check("test program finishes", tot(lambda: not app.run, 15))
    wacht(1)
    marks = [m for m in app.markers if m[0] >= t_start]
    banden = ana.stap_banden(marks, time.time())
    check("step bands found", len(banden) == 2, str(banden)[:200])
    check("step results read", [b["uitslag"] for b in banden] == ["goed", "fout"], str([b["uitslag"] for b in banden]))
    soorten = {m[1]: ana.soort_markering(m[1]) for m in marks}
    check("marker kinds recognised", {"stap", "goed", "fout"} <= set(soorten.values()), str(soorten)[:300])
    ui(lambda: (kijk_widgets(app), foto(app, "programma")))

    # ---- opstartcurve
    STAND["model"] = "gewoon"
    ui(app._curve_start, 3.0, 0.3, 0.5, 0.05)
    check("startup curve finishes", tot(lambda: app.curve is None and bool(app.curves), 20))
    check("startup curve explains", bool(app.curves and app.curves[-1]["uitleg"]))
    for t in app.curves[-1]["uitleg"]:
        kijk_tekst(t)
    open_venster(app._open_curve, "opstartcurve_uitslag")
    STAND["model"] = "kort"
    ui(app._curve_start, 3.0, 0.1, 0.5, 0.05)
    check("startup curve stops at the limit", tot(lambda: app.curve is None and app.curves[-1]["cc_at"] is not None, 20))
    STAND["model"] = "gewoon"

    # ---- onderdelen
    ui(app._open_parts)
    STAND["model"] = "diode"
    ui(app._part_start, "diode")
    check("diode measured", tot(lambda: app.part is None and bool(app.parts), 15), str(app.parts[-1]["kop"] if app.parts else ""))
    check("diode verdict", app.parts[-1]["kop"].startswith(tr("Diode: {0} V", "")[:4]), app.parts[-1]["kop"])
    n = len(app.parts)
    STAND["model"] = "r33"
    ui(app._part_start, "weerstand")
    check("resistor measured", tot(lambda: app.part is None and len(app.parts) > n, 15), str(app.parts[-1]["kop"]))
    check("resistor value", "33" in app.parts[-1]["kop"], app.parts[-1]["kop"])
    n = len(app.parts)
    STAND["model"] = "diode_om"
    ui(app._part_start, "diode")
    check("reversed diode", tot(lambda: app.part is None and len(app.parts) > n, 15))
    check("reversed diode verdict", app.parts[-1]["kop"] == tr("Geen stroom"), app.parts[-1]["kop"])
    STAND["model"] = "gewoon"
    ui(lambda: (kijk_widgets(app._ptwin), foto(app._ptwin, "onderdeel_uitslag"), app._ptwin.destroy()))

    # ---- log, rapport, vergelijken
    ui(app._api_aan, {"akkoord": True})
    log_a, log_b = WORK / "a.csv", WORK / "b.csv"
    ui(app._log_open, log_a)
    wacht(2)
    ui(app._log_close)
    ui(app._log_open, log_b)
    wacht(2)
    ui(app._log_close)
    ui(app._api_uit)
    pts, _ = kp.read_log(log_a)
    check("log is read back", len(pts) >= 2, str(len(pts)))
    pad = WORK / "rapport.html"
    nu = time.time()
    ui(app._make_report, "Test", "Note", nu - 30, nu, pad, False)
    html_tekst = pad.read_text(encoding="utf-8")
    check("report written", tr("Samenvatting") in html_tekst and f'<html lang="{TAAL}"' in html_tekst)
    ui(app._open_compare)
    ui(lambda: (app.cmp.update(A={"name": "a.csv", "pts": kp.read_log(log_a)[0]}, B={"name": "b.csv", "pts": kp.read_log(log_b)[0]}), app._cmp_refresh()))
    pad2 = ui(app._cmp_report)
    check("comparison written", bool(pad2) and tr("Meting A") in Path(pad2).read_text(encoding="utf-8"))
    ui(lambda: (kijk_widgets(app._vwin), foto(app._vwin, "vergelijken_uitslag"), app._vwin.destroy()))

    # ---- nachttest, mini, werkbank
    ui(app._open_night)
    ui(lambda: app._night_cfg.update(v=5.0, i=0.2))
    ui(app._night_start, app._nwin if hasattr(app, "_nwin") else None)
    check("overnight test starts", ui(lambda: bool(app.night)))
    wacht(1)
    ui(app._night_stop, tr("gestopt"))
    check("overnight test stops", tot(lambda: not app.night, 5))
    if getattr(app, "_nwin", None) and ui(app._nwin.winfo_exists):
        ui(lambda: (kijk_widgets(app._nwin), app._nwin.destroy()))
    tot(lambda: not app.out, 5)
    ui(app._api_uit)

    def mini():
        app._toggle_mini()
        app.update()
        kijk_widgets(app.mini if hasattr(app.mini, "winfo_children") else app)
        app._toggle_mini()
    ui(mini)
    check("mini window", app.mini is None)

    def bench():
        app._toggle_bench()
        app.update()
        kijk_widgets(app.bench["win"])
        foto(app.bench["win"], "werkbank")
        app._toggle_bench()
    ui(bench)
    check("bench mode", not app.bench)

    # ---- koppeling
    def api_aan():
        app.settings["api_code"] = app.settings.get("api_code") or "testcode"
        kp.save_settings(app.settings)
        app._api_start()
    ui(api_aan)
    wacht(0.3)
    kl = korad_klant.Paneel(poort=app.settings["api_poort"], code=app.settings["api_code"], wacht=8)
    check("API reads the state", kl.stand()["verbonden"] is True)
    namen = [a["naam"] for a in kl.acties()]
    check("no project-specific actions", not set(namen) & {"monitor", "rooktest", "bouwstap", "ups_duurtest", "ijken", "spanningscontrole"}, str(len(namen)))
    check("API returns a screenshot", kl.scherm("hoofd", 800)[:4] == b"\x89PNG")
    r = kl.actie("teller_nul", wacht=5)
    check("API action runs", r["status"] == "klaar", str(r))

    # ---- over dit programma
    open_venster(app._open_over, "over")
    check("manual present in this language", kp.korad_paden.bron(f"docs/handleiding/handleiding-{TAAL}.pdf").exists())

    # ---- andere modellen en merken
    NORMAAL = NEP.idn
    ui(lambda: app._kies_project("vrij") if app.settings["project"] != "vrij" else None)

    def verbind(idn, na=None):
        ui(lambda: app._disconnect("x") if app.dev else None)
        NEP.idn, NEP.out = idn, False
        ui(lambda: (app.after(250, na) if na else None, app._connect()))

    verbind(b"KORADKA6003PV2.0\x01")
    check("60 V model recognised", (kp.MAX_V, kp.MAX_A) == (60.0, 3.0), f"{kp.MAX_V} {kp.MAX_A}")
    check("unrestricted follows the model", app._limits() == (60.0, 3.0), str(app._limits()))
    check("model shown", app.model_lbl.cget("text") == "KA6003P" and "KA6003P" in app.title(), app.title())
    verbind(b"TENMA 72-2540 V2.1 SN:123")
    check("rebrand recognised", (kp.MAX_V, kp.MAX_A) == (30.0, 5.0) and app.model_lbl.cget("text") == "Tenma 72-2540")
    kp.PROJECTS["t48"] = dict(kp.PROJECTS["vrij"], vmax=48.0, imax=2.0, kort="T48")
    app.settings["project"] = "t48"
    check("project above the supply is limited by the supply", app._limits() == (30.0, 2.0), str(app._limits()))
    app.settings["project"] = "vrij"
    del kp.PROJECTS["t48"]

    onbekend = {}

    def vul():
        w = [x for x in vensters() if hasattr(x, "invul")][-1]
        kijk_widgets(w)
        foto(w, "bereik")
        (ve, ie), bewaar = w.invul
        ve.insert(0, "99")
        ie.insert(0, "2")
        bewaar()
        onbekend["te_hoog_blijft_open"] = w.winfo_exists()
        ve.delete(0, "end")
        ve.insert(0, "24")
        ie.delete(0, "end")
        ie.insert(0, dec_invoer)
        bewaar()

    dec_invoer = "2,5"
    verbind(b"ACME PSU9000 V1 SN:9", vul)
    check("unknown model: range too high refused", onbekend.get("te_hoog_blijft_open"))
    check("unknown model: own range used", (kp.MAX_V, kp.MAX_A) == (24.0, 2.5) and bool(app.dev), f"{kp.MAX_V} {kp.MAX_A}")
    check("unknown model: range remembered", app.settings["bereik_per_idn"].get("ACME PSU9000 V1") == [24.0, 2.5])
    aantal = len(DIALOGEN)
    verbind(b"ACME PSU9000 V1 SN:10")
    check("unknown model: no second question", bool(app.dev) and len(DIALOGEN) == aantal)
    app.settings["bereik_per_idn"] = {}
    ja = kp.messagebox.askyesno
    kp.messagebox.askyesno = lambda *a, **k: (kijk_tekst(a[0]), kijk_tekst(a[1]), False)[2]
    verbind(b"ACME PSU9000 V1 SN:10")
    check("unknown model: can be declined", not app.dev)
    NEP.stil = True
    verbind(b"")
    check("silent port refused", not app.dev and DIALOGEN[-1][0] == "fout", str(DIALOGEN[-1]))
    NEP.stil = False

    # ---- demo kiezen vanuit het gewone paneel (nee zeggen: de proef sluit het paneel niet)
    ui(app._refresh_ports)
    demo = app.port_box["values"][-1]
    check("demo in the port list", demo.startswith(kp.DEMO_POORT), demo)
    kijk_tekst(demo)
    ui(lambda: (app.port_var.set(demo), app._connect()))
    check("declining the demo keeps the panel", not app.dev and not any("--demo" in x for x in GESTART), str(GESTART))
    kp.messagebox.askyesno = ja
    ui(lambda: (app.port_box.configure(values=["COM10  (USB Serial Device)"]), app.port_var.set("COM10  (USB Serial Device)")))
    verbind(NORMAAL)
    check("back to the normal model", (kp.MAX_V, kp.MAX_A) == (30.0, 5.0) and bool(app.dev))

    # ---- taal kiezen en herstarten
    doel = "en" if TAAL != "en" else "de"

    def kies_taal():
        app._open_settings()
        app.update()
        app._taal_box.set(korad_taal.TALEN[doel])
        for w in vensters():
            for k in alle_widgets(w):
                if k.winfo_class() in ("Button", "Label") and k.cget("text") == tr("Opslaan"):
                    k.event_generate("<Button-1>") if k.winfo_class() == "Label" else k.invoke()
                    return True
        return False

    def alle_widgets(w):
        for k in w.winfo_children():
            yield k
            yield from alle_widgets(k)

    check("language can be saved", ui(kies_taal))     # sluit het paneel; de rest gebeurt na de mainloop


def einde():
    """Na het sluiten: was de taal bewaard, is de herstart aangevraagd en bleef alles foutloos?"""
    doel = "en" if TAAL != "en" else "de"
    bewaard = json.loads(kp.SETTINGS_FILE.read_text(encoding="utf-8")).get("taal") if kp.SETTINGS_FILE.exists() else None
    check("language stored", bewaard == doel, str(bewaard))
    check("restart requested", bool(GESTART) and GESTART[-1][-1].endswith("korad_paneel.py"), str(GESTART))
    check("output left off", not NEP.out)
    check("no errors in the panel", not FOUTEN_TK and not kp.ERROR_LOG.exists(), "\n".join(FOUTEN_TK)[:1500])
    if TAAL != "nl":
        for r in sorted(RESTEN):
            log("REST", r)
        check("nothing left in Dutch", not RESTEN, f"{len(RESTEN)} texts")
    goed = sum(1 for _, ok in CHECKS if ok)
    log(f"RESULT {TAAL}: {goed} of {len(CHECKS)} good")
    for n, ok in CHECKS:
        if not ok:
            log("FAILED:", n)
    return goed == len(CHECKS)


UITKOMST = {"ok": False}


def draad():
    try:
        proef()
        UITKOMST["doorlopen"] = True
    except Exception:
        log("TEST STOPPED:\n" + traceback.format_exc())
    finally:
        try:
            if app.winfo_exists():
                app.after(0, app.destroy)
        except Exception:
            pass


testdraad = threading.Thread(target=draad, daemon=True)
app.after(800, testdraad.start)
app.mainloop()
testdraad.join(5)
UITKOMST["ok"] = UITKOMST.get("doorlopen", False) and einde()
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if UITKOMST["ok"] else 1)
