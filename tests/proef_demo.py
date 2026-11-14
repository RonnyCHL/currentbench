"""The demo as a user sees it: no real port, its own data folder, a live supply on the screen.

    py tests/proef_demo.py [nl|en|de]
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

TAAL = next((a for a in sys.argv[1:] if a in ("nl", "en", "de")), "en")
WORK = Path(tempfile.mkdtemp(prefix="korad_demo_"))
os.environ["KORAD_DATA"] = str(WORK)
os.environ["KORAD_DEMO"] = "1"
(WORK / "korad_instellingen.json").write_text(json.dumps({"taal": TAAL, "thema": "licht", "ntfy_topic": "bewaren"}), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import korad_paneel as kp  # noqa: E402
from korad_taal import tr  # noqa: E402

CHECKS, FOUTEN = [], []


def check(naam, ok, detail=""):
    CHECKS.append(bool(ok))
    print(("GOOD " if ok else "FAIL ") + naam + (f"  ({detail})" if detail else ""), flush=True)


def echte_poort(port):
    raise AssertionError(f"the demo opened a real port: {port}")


kp.Korad = echte_poort
kp.serial.tools.list_ports.comports = lambda: (_ for _ in ()).throw(AssertionError("the demo looked for real ports"))
kp.App._beep = lambda self, kind: None
kp.App._say = lambda self, text: None
app = kp.App()
app.report_callback_exception = lambda *a: FOUTEN.append("".join(traceback.format_exception(*a)))


def ui(f):
    klaar, uit = threading.Event(), {}

    def doe():
        uit["r"] = f()
        klaar.set()
    app.after(0, doe)
    klaar.wait(20)
    return uit.get("r")


def tot(voorwaarde, sec=10):
    t = time.time() + sec
    while time.time() < t:
        if ui(voorwaarde):
            return True
        time.sleep(0.1)
    return False


def proef():
    check("connects by itself", tot(lambda: bool(app.dev) and app.vset is not None))
    check("simulated supply in use", isinstance(app.dev, kp.DemoVoeding))
    check("only the demo in the port list", len(app.port_box["values"]) == 1 and app.port_box["values"][0].startswith("DEMO"))
    check("DEMO shown", app.model_lbl.cget("text") == "DEMO" and "DEMO" in app.title(), app.title())
    check("says it is not a real measurement", app.idn == tr("Demo: nagebootste voeding, geen echte meting"), app.idn)
    check("language shared with the panel", kp.korad_taal.huidig() == TAAL and kp.THEMA == "licht")
    ui(lambda: app.cmdq.put("ISET1:0.500"))
    ui(lambda: app.cmdq.put("VSET1:5.00"))
    ui(lambda: app.cmdq.put("OUT1"))
    check("output on", tot(lambda: app.out))
    check("current on the screen", tot(lambda: bool(app.hist) and app.hist[-1][2] > 0.05), str(app.hist[-1]) if app.hist else "")
    ui(lambda: app.cmdq.put("ISET1:0.050"))
    check("current limit shown as CC", tot(lambda: app.cc))
    ui(lambda: app.cmdq.put("OUT0"))
    check("output off", tot(lambda: not app.out))
    app.settings["ntfy_topic"] = "demo-mag-niet-doorlekken"
    ui(lambda: kp.save_settings(app.settings))
    demo = json.loads((WORK / "demo" / "korad_instellingen.json").read_text(encoding="utf-8"))
    hoofd = json.loads((WORK / "korad_instellingen.json").read_text(encoding="utf-8"))
    check("settings kept in the demo folder", demo["ntfy_topic"] == "demo-mag-niet-doorlekken")
    check("real settings untouched", hoofd["ntfy_topic"] == "bewaren" and hoofd["taal"] == TAAL and hoofd["thema"] == "licht", str(hoofd))
    check("no real settings written by the demo", not (WORK / "korad_projecten.json").exists() and not (WORK / "logs").exists())


def draad():
    try:
        proef()
    except Exception:
        FOUTEN.append(traceback.format_exc())
    app.after(0, app.destroy)


app.after(200, threading.Thread(target=draad, daemon=True).start)
app.mainloop()
check("no errors", not FOUTEN, "\n".join(FOUTEN)[:1500])
print(f"RESULT demo: {sum(CHECKS)} of {len(CHECKS)} good")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if all(CHECKS) else 1)
