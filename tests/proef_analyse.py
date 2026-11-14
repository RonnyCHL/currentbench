"""Snelle controles van het rekenwerk in korad_analyse.py (geen voeding, geen scherm).  py tests/proef_analyse.py"""
import os
import random
import sys
from pathlib import Path

os.environ["KORAD_TAAL"] = "nl"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import korad_analyse as a  # noqa: E402

FOUT = []


def check(naam, ok, detail=""):
    print(("GOED " if ok else "FOUT ") + naam + (f"  ({detail})" if detail else ""))
    if not ok:
        FOUT.append(naam)


def reeks(duur, dips, normaal=0.2, laag=0.02, dipduur=2.0, ruis=0.0, stap=0.2):
    t, uit = 0.0, []
    while t < duur:
        in_dip = any(d <= t < d + dipduur for d in dips)
        uit.append((t, (laag if in_dip else normaal) + random.uniform(-ruis, ruis)))
        t += stap
    return uit


random.seed(7)
# herstartteller
d = a.DipTeller()
for t, i in reeks(200, [45, 90, 135, 180], ruis=0.004):
    d.voeg(t, i)
n, gem, reg = d.patroon()
check("dips: vier herstarts gevonden", n == 4, str(n))
check("dips: elke ongeveer 45 s", gem is not None and abs(gem - 45) < 1, str(gem))
check("dips: regelmatig herkend", reg)

d = a.DipTeller()
for t, i in reeks(60, [], ruis=0.01):
    d.voeg(t, i)
check("dips: ruis telt niet", d.patroon()[0] == 0)

d = a.DipTeller()
for t, i in reeks(60, [30]):
    d.voeg(t, i, stil=True)
check("dips: tijdens een proef telt niets", d.patroon()[0] == 0)

d = a.DipTeller()
for t, i in reeks(60, [30]):
    d.voeg(t, i, uit_aan=t < 29)
check("dips: uitgang uit is geen dip", d.patroon()[0] == 0)

d = a.DipTeller()
for t, i in reeks(100, [30], dipduur=40):
    d.voeg(t, i)
check("dips: blijvend lager is een nieuw niveau", d.patroon()[0] == 0)

d = a.DipTeller()
for t, i in reeks(200, [30, 40, 130, 135], ruis=0.002):
    d.voeg(t, i)
check("dips: onregelmatig blijft onregelmatig", not d.patroon()[2], str(d.patroon()))

# stroomafdruk
pts = [(100 + k * 0.2, 5.0, 0.05 + (0.15 if k * 0.2 > 2 else 0)) for k in range(60)]
b = a.bemonster(pts, 100.0)
check("afdruk: raster van 0,25 s", abs(len(b) - 48) <= 1, str(len(b)))
laag, hoog = a.maak_band([b])
check("afdruk: band omsluit de start", all(lo <= x <= hi for lo, x, hi in zip(laag, b, hoog)))
c = a.BandControle(laag, hoog, 500.0)
for p in pts:
    c.voeg(p[0] + 400, p[2])
check("afdruk: gelijke start valt binnen de band", c.procent() > 99, f"{c.procent():.1f}")
c = a.BandControle(laag, hoog, 500.0)
for p in pts:
    c.voeg(p[0] + 400, p[2] * 2)
check("afdruk: dubbele stroom valt buiten de band", c.procent() < 30, f"{c.procent():.1f}")
check("afdruk: voorbij het einde stopt", a.BandControle(laag, hoog, 0.0).voeg(1000.0, 0.1) is False)
check("afdruk: lege invoer geeft lege band", a.maak_band([[]]) == ([], []))

# markeringen
marks = [(10, "testprogramma: Proef"), (10.1, "stap 1: 13,8 V"), (20, "stap 1 GOED: gemiddeld 144 mA"),
         (20.1, "stap 2: uitgang uit"), (24, "stap 2 FOUT: niet gemeld"), (30, "stap 3: 13,8 V"),
         (40, "testprogramma: klaar")]
bn = a.stap_banden(marks, 99)
check("banden: drie stappen", [x["nr"] for x in bn] == [1, 2, 3])
check("banden: uitslag per stap", [x["uitslag"] for x in bn] == ["goed", "fout", ""], str(bn))
check("banden: einde bij klaar", bn[2]["t1"] == 40)
check("banden: lopende stap tot nu", a.stap_banden([(1, "stap 1: 5 V")], 9)[0]["t1"] == 9)
two = a.stap_banden([(1, "stap 1: 5 V"), (5, "stap 1 GOED: x"), (5.5, "stap 1 FOUT: y")], 9)
check("banden: een fout blijft een fout", two[0]["uitslag"] == "fout")

v = a.vlaggen(marks, lambda t: t * 10, 7, 10, 3)
check("vlaggen: dicht opeen wordt samengevoegd", v[0]["label"] == "1-2", v[0]["label"])
check("vlaggen: alle markeringen zitten erin", sum(len(x["items"]) for x in v) == len(marks))
check("vlaggen: raken elkaar niet", all(p["x1"] <= q["x0"] for p, q in zip(v, v[1:])))
check("vlaggen: fout gaat voor", next(x for x in v if any("FOUT" in i[2] for i in x["items"]))["soort"] == "fout")
for tekst, soort in (("stap 1 FOUT: x", "fout"), ("alarm: stroom boven 300", "alarm"),
                     ("NOODSTOP (Esc): uitgang uit", "alarm"),
                     ("stroomdip 3", "auto"), ("stap 1: 5 V", "stap"), ("eigen notitie", "notitie")):
    check(f"soort: {tekst}", a.soort_markering(tekst) == soort, a.soort_markering(tekst))

print(f"\nSAMENVATTING: {'alles goed' if not FOUT else str(len(FOUT)) + ' fout: ' + ', '.join(FOUT)}")
sys.exit(1 if FOUT else 0)
