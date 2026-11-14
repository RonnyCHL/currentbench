"""Talking to the power supply and recognising which model it is.

The Korad protocol is shared by the KA and KD series and by rebranded units from Tenma, Velleman, RND and Stamos. The
list of models follows the public documentation of the sigrok project. Only the KA3005PS has been tested with this panel.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import serial

PLAFOND_V, PLAFOND_A = 60.0, 20.0       # hoger bestaat in deze reeks niet; ook een handmatig bereik blijft hieronder

_TENMA = {"72-2535": (30.0, 3.0), "72-2540": (30.0, 5.0), "72-2545": (60.0, 2.0), "72-2550": (60.0, 3.0),
          "72-2705": (30.0, 3.0), "72-2710": (30.0, 5.0)}
# Alleen de bekende reeksen van 30 en 60 V: de dubbele KA3305P gebruikt andere opdrachten en valt hier bewust buiten.
_KORAD = re.compile(r"K[AD](30|60)(\d{2})PS?")
_VELLEMAN = re.compile(r"(?:LAB)?PS(30|60)(\d{2})D")


@dataclass(frozen=True)
class Model:
    naam: str
    vmax: float
    imax: float


def schoon_idn(ruw: bytes) -> str:
    """Het antwoord op *IDN? zonder de onleesbare tekens die sommige voedingen erachter zetten."""
    return "".join(c for c in ruw.decode("ascii", "ignore") if c.isprintable()).strip()


def sleutel(idn: str) -> str:
    """De naam van het model zonder serienummer, om een zelf ingevuld bereik te onthouden."""
    return re.sub(r"\s*SN:.*$", "", idn).strip()


def geldig_bereik(vmax: float, imax: float) -> bool:
    return 1.0 <= vmax <= PLAFOND_V and 0.1 <= imax <= PLAFOND_A


def herken(idn: str) -> Model | None:
    """Het model bij een *IDN?-antwoord, of None als het paneel dit model niet kent."""
    tekst = idn.upper()
    for patroon in (_KORAD, _VELLEMAN):
        m = patroon.search(tekst)
        if m and 1 <= int(m.group(2)) <= int(PLAFOND_A):
            return Model(m.group(0), float(m.group(1)), float(m.group(2)))
    for nummer, (vmax, imax) in _TENMA.items():
        if nummer in tekst:
            return Model(f"Tenma {nummer}", vmax, imax)
    if "S-LS-31" in tekst:
        return Model("Stamos S-LS-31", 30.0, 5.0)
    return None


class Korad:
    """Praat met de voeding via de seriele poort (9600 baud, geen regeleinde)."""

    def __init__(self, port):
        self.ser = serial.Serial(port, 9600, timeout=0.1)
        self.lock = threading.Lock()

    def close(self):
        self.ser.close()

    def query(self, cmd, max_wait=0.5):
        with self.lock:
            self.ser.reset_input_buffer()
            self.ser.write(cmd.encode("ascii"))
            data, start, last = b"", time.time(), None
            while time.time() - start < max_wait:
                n = self.ser.in_waiting
                if n:
                    data += self.ser.read(n)
                    last = time.time()
                elif last and time.time() - last > 0.03:
                    break
                else:
                    time.sleep(0.005)
            time.sleep(0.02)
            return data

    def write(self, cmd):
        with self.lock:
            self.ser.write(cmd.encode("ascii"))
            time.sleep(0.08)

    def number(self, cmd):
        # Hooguit drie decimalen: sommige voedingen zetten een extra teken achter het antwoord op ISET1?.
        m = re.search(r"\d+\.\d{1,3}", self.query(cmd).decode("ascii", "ignore"))
        return float(m.group()) if m else None

    def status(self):
        raw = self.query("STATUS?")
        if not raw:
            return None
        b = raw[0]
        # Volgens de Korad-documentatie: bit 0 = CV (1) of CC (0), bit 6 = uitgang aan.
        # Kloppen de lampjes niet met de voeding, dan zit het verschil hier.
        return {"cv": bool(b & 0x01), "out": bool(b & 0x40)}


def begrijpt_opdrachten(dev) -> bool:
    """Antwoordt dit apparaat als een Korad-voeding? Stelt alleen vragen en verandert niets."""
    return dev.number("VSET1?") is not None and dev.number("ISET1?") is not None and dev.status() is not None
