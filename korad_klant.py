"""Scripts laten meten via het Korad paneel, terwijl het paneel open blijft (november 2026).

Op de opdrachtregel (vanuit deze map):
    py korad_klant.py stand
    py korad_klant.py zet 5 0.5 [--akkoord]        eerst de stroomgrens, dan de spanning
    py korad_klant.py aan --akkoord
    py korad_klant.py uit
    py korad_klant.py markering "tekst"
    py korad_klant.py log 60 [--csv meting.csv]    elke seconde uitlezen
    py korad_klant.py scherm [venster] [uit.png]   schermbeeld van een venster
    py korad_klant.py acties                       alle opdrachten
    py korad_klant.py actie NAAM [--akkoord] [sleutel=waarde ...]
    py korad_klant.py dialogen                     vragen die op een antwoord wachten

In een eigen script:
    from korad_klant import Paneel, PaneelNietBereikbaar
    p = Paneel(); print(p.stand()["i"])
"""
from __future__ import annotations

from korad_taal import tr

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import korad_paden

INSTELLINGEN = korad_paden.INSTELLINGEN


class PaneelNietBereikbaar(Exception):
    """Het paneel draait niet, of de koppeling staat uit."""


class PaneelWeigert(Exception):
    """Het paneel heeft de opdracht geweigerd, met de reden als tekst."""


class Paneel:
    def __init__(self, bestand=INSTELLINGEN, poort=None, code=None, wacht=6.0):
        if poort is None or code is None:
            try:
                st = json.loads(Path(bestand).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise PaneelNietBereikbaar(tr("instellingen van het paneel niet gelezen: {0}", e)) from e
            poort, code = poort or st.get("api_poort", 8086), code or st.get("api_code", "")
        if not code:
            raise PaneelNietBereikbaar(tr("het paneel heeft nog geen code; start het paneel een keer"))
        self.url, self.code, self.wacht = f"http://127.0.0.1:{poort}", code, wacht

    def _vraag(self, methode, pad, data=None):
        body = None if data is None else json.dumps(data).encode("utf-8")
        req = urllib.request.Request(self.url + pad, data=body, method=methode,
                                     headers={"X-Korad-Code": self.code, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.wacht) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                reden = json.loads(e.read().decode("utf-8")).get("fout", str(e))
            except ValueError:
                reden = str(e)
            raise PaneelWeigert(reden) from e
        except (urllib.error.URLError, OSError) as e:
            raise PaneelNietBereikbaar(tr("het paneel antwoordt niet op {0}: {1}", self.url, e)) from e

    def stand(self):
        return self._vraag("GET", "/api/stand")

    def metingen(self, sec=60):
        return self._vraag("GET", f"/api/metingen?sec={sec}")["metingen"]

    def zet(self, v, i, akkoord=False):
        return self._vraag("POST", "/api/zet", {"v": v, "i": i, "akkoord": akkoord})

    def aan(self, akkoord=False):
        return self._vraag("POST", "/api/aan", {"akkoord": akkoord})

    def uit(self):
        return self._vraag("POST", "/api/uit", {})

    def markering(self, tekst):
        return self._vraag("POST", "/api/markering", {"tekst": tekst})

    def scherm(self, venster="hoofd", breed=1800):
        req = urllib.request.Request(f"{self.url}/api/scherm?venster={venster}&breed={breed}",
                                     headers={"X-Korad-Code": self.code})
        try:
            with urllib.request.urlopen(req, timeout=max(self.wacht, 10)) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise PaneelWeigert(json.loads(e.read().decode("utf-8")).get("fout", str(e))) from e
        except (urllib.error.URLError, OSError) as e:
            raise PaneelNietBereikbaar(tr("het paneel antwoordt niet op {0}: {1}", self.url, e)) from e

    def acties(self):
        return self._vraag("GET", "/api/acties")["acties"]

    def dialogen(self):
        return self._vraag("GET", "/api/dialogen")["dialogen"]

    def actie(self, opdracht, /, akkoord=False, wacht=30.0, **waarden):
        """Opdracht geven en op de uitslag wachten. Blijft hij lopen, dan wacht het paneel meestal op een antwoord
        van de gebruiker: de uitslag heeft dan status 'loopt' en de open vragen staan onder 'dialogen'."""
        nr = self._vraag("POST", "/api/actie", {"actie": opdracht, "akkoord": akkoord, **waarden})["id"]
        eind = time.time() + wacht
        while True:
            r = self._vraag("GET", f"/api/actie?id={nr}")
            if r["status"] != "loopt":
                return r
            if time.time() >= eind:
                r["dialogen"] = self.dialogen()
                return r
            time.sleep(0.15)


class ScriptKorad:
    """Doet alsof het de Korad-klasse uit tools/korad.py of tools/labvoeding.py is, maar gaat via het paneel.
    Die scripts gebruiken dit als de seriele poort bezet is. Het paneel past zijn eigen grenzen toe; de commando's
    aan en uit tikt de gebruiker zelf in het script, dus die gelden als akkoord."""

    def __init__(self, paneel=None):
        self.p = paneel or Paneel()
        st = self.p.stand()
        if not st.get("verbonden"):
            raise PaneelNietBereikbaar(tr("het paneel draait, maar de voeding is niet verbonden"))

    def close(self):
        pass

    def idn(self):
        return self.p.stand()["idn"]

    def vset(self):
        return self.p.stand()["vset"]

    def iset(self):
        return self.p.stand()["iset"]

    def vout(self):
        return self.p.stand()["v"]

    def iout(self):
        return self.p.stand()["i"]

    def status(self):
        st = self.p.stand()
        return {"cc": st["modus"] == "CC", "out": st["uit"], "uit_aan": st["uit"]}

    def out(self, on):
        if on:
            self.p.aan(akkoord=True)
        else:
            self.p.uit()

    uitgang = out

    def set(self, v, i, akkoord=False):
        self.p.zet(v, i, akkoord)

    def zet(self, v, i):
        self.p.zet(v, i, False)

    def reading(self):
        st = self.p.stand()
        return {"v": st["v"], "a": st["i"], "w": st["w"], "modus": "CC" if st["modus"] == "CC" else "CV",
                "uitgang": "aan" if st["uit"] else "uit"}


def _waarde(tekst):
    """sleutel=waarde van de opdrachtregel: getallen en true/false worden echte waarden."""
    k, _, w = tekst.partition("=")
    if w.lower() in ("true", "false"):
        return k, w.lower() == "true"
    try:
        return k, float(w.replace(",", "."))
    except ValueError:
        return k, w


def _toon(st):
    if not st.get("verbonden"):
        print(tr("Paneel draait, maar de voeding is niet verbonden."))
        return
    print(tr("{0}  project {1} (max {2} V, {3} A)", st['idn'], st['project']['kort'], st['project']['vmax'], st['project']['imax']))
    print(tr("ingesteld {0} V, grens {1} A  |  gemeten {2} V, {3} A, {4:.3f} W", st['vset'], st['iset'], st['v'], st['i'], st['w']))
    print(tr("uitgang {0}, {1}", 'aan' if st['uit'] else 'uit', st['modus']) + (tr("  ALARM: {0}", st['alarm']) if st["alarm"] else ""))


def main():
    ap = argparse.ArgumentParser(description=tr("Via CurrentBench meten en instellen"))
    sub = ap.add_subparsers(dest="wat", required=True)
    sub.add_parser("stand")
    p = sub.add_parser("zet")
    p.add_argument("v", type=float)
    p.add_argument("i", type=float)
    p.add_argument("--akkoord", action="store_true")
    p = sub.add_parser("aan")
    p.add_argument("--akkoord", action="store_true")
    sub.add_parser("uit")
    p = sub.add_parser("markering")
    p.add_argument("tekst")
    p = sub.add_parser("log")
    p.add_argument("seconden", type=float, nargs="?", default=60)
    p.add_argument("--csv")
    p = sub.add_parser("scherm")
    p.add_argument("venster", nargs="?", default="hoofd")
    p.add_argument("pad", nargs="?", default="paneel.png")
    sub.add_parser("acties")
    sub.add_parser("dialogen")
    p = sub.add_parser("actie")
    p.add_argument("naam")
    p.add_argument("--akkoord", action="store_true")
    p.add_argument("--wacht", type=float, default=30.0)
    p.add_argument("waarden", nargs="*", help="sleutel=waarde")
    a = ap.parse_args()
    try:
        k = Paneel()
        if a.wat == "stand":
            _toon(k.stand())
        elif a.wat == "zet":
            k.zet(a.v, a.i, a.akkoord)
            print("ingesteld")
        elif a.wat == "aan":
            k.aan(a.akkoord)
            print(tr("uitgang aan"))
        elif a.wat == "uit":
            k.uit()
            print(tr("uitgang uit"))
        elif a.wat == "markering":
            k.markering(a.tekst)
            print(tr("markering geplaatst"))
        elif a.wat == "scherm":
            Path(a.pad).write_bytes(k.scherm(a.venster))
            print(a.pad)
        elif a.wat == "acties":
            for x in k.acties():
                print(f"{x['naam']:24s}{'[akkoord] ' if x['akkoord'] else ''}{x['tekst']}")
        elif a.wat == "dialogen":
            print(json.dumps(k.dialogen(), ensure_ascii=False, indent=1))
        elif a.wat == "actie":
            print(json.dumps(k.actie(a.naam, akkoord=a.akkoord, wacht=a.wacht, **dict(_waarde(x) for x in a.waarden)),
                             ensure_ascii=False, indent=1))
        elif a.wat == "log":
            f = open(a.csv, "w", newline="", encoding="utf-8") if a.csv else None
            w = csv.writer(f) if f else None
            if w:
                w.writerow(["tijd", "spanning_V", "stroom_A", "uitgang", "modus"])
            eind = time.time() + a.seconden
            try:
                while time.time() < eind:
                    s = k.stand()
                    print(f"{time.strftime('%H:%M:%S')}  {s.get('v')} V  {s.get('i')} A  {s.get('modus', '')}")
                    if w:
                        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), s.get("v"), s.get("i"), s.get("uit"),
                                    s.get("modus", "")])
                    time.sleep(1)
            finally:
                if f:
                    f.close()
    except PaneelNietBereikbaar as e:
        print(tr("Niet bereikbaar: {0}", e), file=sys.stderr)
        return 2
    except PaneelWeigert as e:
        print(tr("Geweigerd: {0}", e), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
