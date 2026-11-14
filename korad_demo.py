"""A simulated power supply for the demo: a small board that draws an inrush current and then a steady load."""
from __future__ import annotations

import math
import random
import threading
import time

from korad_voeding import Korad

DEMO_POORT = "DEMO"


class DemoVoeding(Korad):
    """Gedraagt zich als de echte voeding, met een belasting van 47 ohm, een regelaar en een inschakelpiek."""

    def __init__(self):
        self.lock = threading.Lock()
        self.vset, self.iset, self.out = 5.0, 0.5, False
        self.t_aan = 0.0

    def close(self):
        pass

    def _vraag(self, v, nu):
        piek = 0.25 * math.exp(-(nu - self.t_aan) / 0.35) * min(1.0, v / 5.0)
        return v / 47.0 + (0.018 if v > 2.5 else 0.0) + piek

    def _meet(self):
        """(spanning, stroom, CV): boven de stroomgrens zakt de spanning tot de vraag gelijk is aan de grens."""
        if not self.out:
            return 0.0, 0.0, True
        nu = time.monotonic()
        vraag = self._vraag(self.vset, nu)
        if vraag <= self.iset:
            return self.vset, vraag, True
        laag, hoog = 0.0, self.vset
        for _ in range(30):
            midden = (laag + hoog) / 2
            if self._vraag(midden, nu) > self.iset:
                hoog = midden
            else:
                laag = midden
        return laag, self.iset, False

    def write(self, cmd):
        if cmd.startswith("VSET1:"):
            self.vset = float(cmd[6:])
        elif cmd.startswith("ISET1:"):
            self.iset = float(cmd[6:])
        elif cmd in ("OUT0", "OUT1"):
            if cmd == "OUT1" and not self.out:
                self.t_aan = time.monotonic()
            self.out = cmd == "OUT1"
        time.sleep(0.005)

    def query(self, cmd, max_wait=0.5):
        time.sleep(0.005)
        v, i, cv = self._meet()
        if self.out:
            v, i = max(0.0, v + random.gauss(0, 0.003)), max(0.0, i + random.gauss(0, 0.0004))
        return {"*IDN?": b"KORAD KA3005P DEMO", "VSET1?": f"{self.vset:05.2f}".encode(), "ISET1?": f"{self.iset:.3f}".encode(),
                "VOUT1?": f"{v:05.2f}".encode(), "IOUT1?": f"{i:.3f}".encode(),
                "STATUS?": bytes([(1 if cv else 0) | (0x40 if self.out else 0)])}.get(cmd, b"")
