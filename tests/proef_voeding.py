"""Checks without a window: model recognition, data folder and the simulated supply.

    py tests/proef_voeding.py
"""
import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
WORK = Path(tempfile.mkdtemp(prefix="korad_test_"))
os.environ["KORAD_DATA"] = str(WORK)
import korad_demo  # noqa: E402
import korad_paden  # noqa: E402
import korad_voeding as kv  # noqa: E402

FOUT = []


def check(naam, ok, detail=""):
    print(("GOOD " if ok else "FAIL ") + naam + (f"  ({detail})" if detail else ""))
    if not ok:
        FOUT.append(naam)


GEVALLEN = {
    "KORADKA3005PV2.0": ("KA3005P", 30, 5),
    "KORAD KA3005PS V1.5 SN:123": ("KA3005PS", 30, 5),
    "KORAD KD3005P V2.0": ("KD3005P", 30, 5),
    "KORAD KA3010P V2.0": ("KA3010P", 30, 10),
    "KORAD KA6003P V2.0": ("KA6003P", 60, 3),
    "KORAD KD6005P V2.0": ("KD6005P", 60, 5),
    "RND 320-KA3005P V2.0": ("KA3005P", 30, 5),
    "RND 320-KD3005P V5.4 SN:1": ("KD3005P", 30, 5),
    "VELLEMANPS3005DV1.3": ("PS3005D", 30, 5),
    "VELLEMAN LABPS3005D V5.0": ("LABPS3005D", 30, 5),
    "TENMA 72-2535 V2.1": ("Tenma 72-2535", 30, 3),
    "TENMA 72-2550 V2.0": ("Tenma 72-2550", 60, 3),
    "TENMA 72-2710 V6.1": ("Tenma 72-2710", 30, 5),
    "S-LS-31 V2.0": ("Stamos S-LS-31", 30, 5),
}
for idn, (naam, v, a) in GEVALLEN.items():
    m = kv.herken(idn)
    check(f"recognises {idn}", m is not None and (m.naam, m.vmax, m.imax) == (naam, v, a), str(m))
for idn in ("KORAD KA3305P V2.0", "KORAD KA3000P V2.0", "ACME PSU9000", "", "OK"):
    check(f"does not guess a range for '{idn}'", kv.herken(idn) is None)

check("control characters removed", kv.schoon_idn(b"KORADKA3005PV2.0\x01\xbc") == "KORADKA3005PV2.0")
check("serial number removed", kv.sleutel("ACME X V1 SN:42") == "ACME X V1")
check("range accepted", kv.geldig_bereik(24, 2.5))
for v, a in ((99, 2), (30, 50), (0, 2), (30, 0)):
    check(f"range refused: {v} V, {a} A", not kv.geldig_bereik(v, a))


class Antwoord(kv.Korad):
    def __init__(self, antwoord):
        self.antwoord = antwoord

    def query(self, cmd, max_wait=0.5):
        return self.antwoord


check("extra byte after ISET1? ignored", Antwoord(b"5.0002").number("ISET1?") == 5.0)
check("normal voltage read", Antwoord(b"12.34").number("VSET1?") == 12.34)
check("no number gives None", Antwoord(b"").number("VSET1?") is None)

d = korad_demo.DemoVoeding()
check("demo: output off at start", d.status()["out"] is False and d.number("VOUT1?") == 0.0)
check("demo understands the commands", kv.begrijpt_opdrachten(d))
check("demo is recognised as a model", kv.herken(kv.schoon_idn(d.query("*IDN?"))) is not None)
d.write("ISET1:0.500")
d.write("VSET1:5.00")
d.write("OUT1")
piek = d.number("IOUT1?")
time.sleep(2.2)
rust = d.number("IOUT1?")
check("demo: inrush current at switch-on", piek > rust, f"{piek} > {rust}")
check("demo: steady load", 0.11 < rust < 0.14 and d.status()["cv"], str(rust))
d.write("ISET1:0.050")
check("demo: current limit lowers the voltage", d.status()["cv"] is False and d.number("VOUT1?") < 4.0, str(d.number("VOUT1?")))
d.write("OUT0")
check("demo: output off", d.status()["out"] is False)

check("data folder from the test variable", korad_paden.DATA == WORK)
check("restart command", korad_paden.herstart_opdracht(False)[-1].endswith("korad_paneel.py"))
check("restart command for the demo", korad_paden.herstart_opdracht(True)[-1] == "--demo")
del os.environ["KORAD_DATA"]
os.environ["APPDATA"] = str(WORK / "appdata")
check("normal data folder", korad_paden._hoofdmap() == WORK / "appdata" / "CurrentBench")
korad_paden.PROGRAMMA = WORK
(WORK / "portable.txt").write_text("", encoding="utf-8")
check("portable: data next to the program", korad_paden._hoofdmap() == WORK)
(WORK / "portable.txt").unlink()
os.environ["KORAD_DEMO"] = "1"
os.environ["KORAD_DATA"] = str(WORK)
korad_paden = importlib.reload(korad_paden)
check("demo has its own folder", korad_paden.DATA == WORK / "demo" and (WORK / "demo").is_dir())
check("language and appearance stay in the main folder", korad_paden.INSTELLINGEN == WORK / "korad_instellingen.json")

print(f"RESULT: {'all good' if not FOUT else str(len(FOUT)) + ' failed'}")
sys.exit(1 if FOUT else 0)
