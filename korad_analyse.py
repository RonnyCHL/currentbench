"""Rekenwerk van het Korad paneel, zonder scherm en zonder voeding (november 2026).

Hier staat wat los te testen is: de herstartteller, de stroomafdruk en de indeling van markeringen in vlaggetjes en
stapbanden. Het paneel roept dit aan; `tests/proef_analyse.py` controleert het in een paar seconden.
"""
from __future__ import annotations

import re
import statistics
from collections import deque

from korad_taal import tr


# ---------------------------------------------------------------- herstartteller
class DipTeller:
    """Herkent korte terugkerende stroomdips: het kenmerk van een bordje dat steeds opnieuw opstart.

    Een dip telt als de stroom onder `diep` keer het normale niveau zakt en binnen `max_duur` seconden terugkomt.
    Het normale niveau is de mediaan van de afgelopen `venster` seconden. Tijdens een proef die zelf de spanning
    of de uitgang bedient (`stil`) en met de uitgang uit telt er niets.
    """

    def __init__(self, diep=0.5, min_a=0.005, max_duur=15.0, venster=10.0, min_dip=0.15):
        self.diep, self.min_a, self.max_duur, self.venster, self.min_dip = diep, min_a, max_duur, venster, min_dip
        self.nul()

    def nul(self):
        self.dips = []                 # (starttijd, duur, normaal niveau in A)
        self._reset()

    def _reset(self):
        self._rij = deque()
        self._dip_t = self._niveau = None

    def voeg(self, t, i, uit_aan=True, stil=False):
        """Eén meting verwerken. Geeft een (start, duur, niveau) terug op het moment dat een dip voorbij is."""
        if not uit_aan or stil:
            self._reset()
            return None
        if self._dip_t is not None:
            if i >= self._niveau * 0.8:
                t0, niveau, duur = self._dip_t, self._niveau, t - self._dip_t
                self._dip_t = self._niveau = None
                self._rij.clear()
                if duur < self.min_dip:
                    return None
                self.dips.append((t0, duur, niveau))
                return self.dips[-1]
            if t - self._dip_t > self.max_duur:     # langdurig lager: dat is een nieuw niveau, geen dip
                self._reset()
            return None
        while self._rij and t - self._rij[0][0] > self.venster:
            self._rij.popleft()
        if len(self._rij) >= 8 and t - self._rij[0][0] >= 2.0:
            niveau = statistics.median(x[1] for x in self._rij)
            if i < niveau * self.diep and niveau - i >= self.min_a:
                self._dip_t, self._niveau = t, niveau
                return None
        self._rij.append((t, i))
        return None

    def patroon(self):
        """(aantal, gemiddelde tijd tussen de dips of None, regelmatig ja/nee)."""
        n = len(self.dips)
        if n < 2:
            return n, None, False
        tussen = [b[0] - a[0] for a, b in zip(self.dips, self.dips[1:])]
        gem = sum(tussen) / len(tussen)
        regelmatig = n >= 3 and gem > 0 and statistics.pstdev(tussen) / gem < 0.25
        return n, gem, regelmatig


# ---------------------------------------------------------------- stroomafdruk
AFDRUK_STAP = 0.25                     # seconden tussen twee punten van een afdruk
AFDRUK_MIN_DUUR = 3.0                  # korter is geen bruikbare start
AFDRUK_MAX_DUUR = 120.0
AFDRUK_MAX_STARTS = 10


def bemonster(pts, t_aan, duur=None, stap=AFDRUK_STAP):
    """Metingen (t, v, i) vanaf t_aan op een vast raster zetten: lijst stroomwaarden in A."""
    rij = [(p[0] - t_aan, p[2]) for p in pts if p[0] >= t_aan and (duur is None or p[0] <= t_aan + duur)]
    if len(rij) < 2:
        return []
    eind = rij[-1][0]
    uit, k = [], 0
    for n in range(int(eind / stap) + 1):
        doel = n * stap
        while k + 1 < len(rij) and rij[k + 1][0] <= doel:
            k += 1
        if k + 1 < len(rij) and rij[k + 1][0] > rij[k][0]:
            f = max(0.0, min(1.0, (doel - rij[k][0]) / (rij[k + 1][0] - rij[k][0])))
            uit.append(rij[k][1] + (rij[k + 1][1] - rij[k][1]) * f)
        else:
            uit.append(rij[k][1])
    return uit


def maak_band(starts, marge_rel=0.10, marge_abs=0.005, speling=2):
    """Band (laag, hoog) om een of meer starts. `speling` is de tijdspeling in rasterpunten: een bordje start nooit
    op precies hetzelfde moment, dus elk punt kijkt ook naar zijn buren."""
    starts = [s for s in starts if s]
    if not starts:
        return [], []
    n = max(len(s) for s in starts)
    laag, hoog = [], []
    for k in range(n):
        vals = [x for s in starts for x in s[max(0, k - speling):k + speling + 1]]
        if not vals:
            vals = [starts[0][-1]]
        laag.append(max(0.0, min(vals) * (1 - marge_rel) - marge_abs))
        hoog.append(max(vals) * (1 + marge_rel) + marge_abs)
    return laag, hoog


class BandControle:
    """Volgt één start tegen een band en houdt bij hoeveel metingen erbinnen vallen."""

    def __init__(self, laag, hoog, t_aan, stap=AFDRUK_STAP):
        self.laag, self.hoog, self.t_aan, self.stap = laag, hoog, t_aan, stap
        self.binnen = self.buiten = 0
        self.laatste_ok = True

    @property
    def duur(self):
        return len(self.laag) * self.stap

    def voeg(self, t, i):
        """Geeft False als de start voorbij het einde van de afdruk is."""
        k = int((t - self.t_aan) / self.stap)
        if k < 0:
            return True
        if k >= len(self.laag):
            return False
        self.laatste_ok = self.laag[k] <= i <= self.hoog[k]
        if self.laatste_ok:
            self.binnen += 1
        else:
            self.buiten += 1
        return True

    def procent(self):
        n = self.binnen + self.buiten
        return 100.0 * self.binnen / n if n else 100.0


# ---------------------------------------------------------------- markeringen: vlaggetjes en stapbanden
_STAP = re.escape(tr("stap"))
_STAP_START = re.compile(rf"^{_STAP} (\d+): ")
_STAP_UITSLAG = re.compile(rf"^{_STAP} (\d+)(?: \({re.escape(tr('ronde'))} \d+\))? ({re.escape(tr('GOED'))}|{re.escape(tr('FOUT'))})\b")
_PROG_EINDE = re.compile(rf"^{re.escape(tr('testprogramma'))}: ({re.escape(tr('Klaar'))}|{re.escape(tr('Gestopt'))})",
                         re.IGNORECASE)
SOORT_VOLGORDE = ("fout", "alarm", "goed", "notitie", "monitor", "auto", "stap", "gewoon")


def soort_markering(tekst):
    """Soort van een markering, voor de kleur van het vlaggetje."""
    t = tekst.lower()
    begin = lambda *woorden: t.startswith(tuple(tr(w).lower() for w in woorden))
    fout = tr("FOUT").lower()
    if f" {fout}" in t or t.startswith(fout):
        return "fout"
    if begin("alarm", "noodstop", tr("grens: uitgang"), tr("stroomgrens teruggezet")) or tr("buiten de band").lower() in t:
        return "alarm"
    if f" {tr('GOED').lower()}" in t or tr("binnen de band").lower() in t:
        return "goed"
    if begin("stroomdip", "afdruk"):
        return "auto"
    if begin("stap", "testprogramma", "nachttest", "accu", "opstartcurve"):
        return "stap"
    return "notitie"


def vlaggen(marks, x_van, breedte_per_teken, basis, tussen):
    """Markeringen (t, tekst) binnen beeld groeperen tot vlaggetjes die elkaar niet raken.

    x_van(t) geeft de plaats op het scherm. Elk vlaggetje: dict met x0, x1, label, items [(nummer, t, tekst)] en
    soort (de belangrijkste soort die erin zit)."""
    uit = []
    for nr, (t, tekst) in enumerate(sorted(marks, key=lambda m: m[0]), start=1):
        x = x_van(t)
        if uit and x - uit[-1]["x0"] < uit[-1]["w"] + tussen:
            v = uit[-1]
            v["items"].append((nr, t, tekst))
        else:
            v = {"x0": x, "w": 0, "items": [(nr, t, tekst)]}
            uit.append(v)
        v["label"] = (str(v["items"][0][0]) if len(v["items"]) == 1
                      else f"{v['items'][0][0]}-{v['items'][-1][0]}")
        v["w"] = basis + breedte_per_teken * len(v["label"])
    for v in uit:
        soorten = {soort_markering(i[2]) for i in v["items"]}
        v["soort"] = next(s for s in SOORT_VOLGORDE if s in soorten)
        v["x1"] = v["x0"] + v["w"]
    return uit


def stap_banden(marks, t_eind):
    """Stappen van testprogramma's uit de markeringen halen: lijst dicts met t0, t1, nr en uitslag ('', goed, fout)."""
    banden, open_ = [], None
    for t, tekst in sorted(marks, key=lambda m: m[0]):
        m = _STAP_START.match(tekst)
        if m:
            if open_:
                open_["t1"] = t
            open_ = {"t0": t, "t1": None, "nr": int(m.group(1)), "uitslag": ""}
            banden.append(open_)
            continue
        m = _STAP_UITSLAG.match(tekst)
        if m:
            nr = int(m.group(1))
            band = next((b for b in reversed(banden) if b["nr"] == nr and b["t0"] <= t), None)
            if band:                       # een fout blijft een fout, ook als een tweede controle wel goed is
                nieuw = "fout" if m.group(2) == tr("FOUT") else "goed"
                band["uitslag"] = "fout" if "fout" in (band["uitslag"], nieuw) else nieuw
            continue
        if open_ and _PROG_EINDE.match(tekst):
            open_["t1"] = t
            open_ = None
    for b in banden:
        if b["t1"] is None:
            b["t1"] = t_eind
    return banden
