"""Where CurrentBench keeps its files.

Everything a user creates goes to one data folder, never into the program folder, so the panel also works as an
installed program or a single .exe:
    1. the environment variable KORAD_DATA, used by the tests;
    2. the program folder, if a file portable.txt is next to the program (for a USB stick);
    3. otherwise the folder "CurrentBench" in the user's application data.

The demo (--demo) keeps its own subfolder, so simulated measurements never mix with real ones. Language and appearance
are shared with the normal panel.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BEVROREN = bool(getattr(sys, "frozen", False))      # True in een kant-en-klare .exe
PROGRAMMA = Path(sys.executable).parent if BEVROREN else Path(__file__).resolve().parent
_BRON = Path(getattr(sys, "_MEIPASS", PROGRAMMA))    # meegeleverde bestanden: vertalingen en icoon
DEMO = "--demo" in sys.argv or os.environ.get("KORAD_DEMO") == "1"


def _hoofdmap() -> Path:
    eigen = os.environ.get("KORAD_DATA")
    if eigen:
        return Path(eigen)
    if (PROGRAMMA / "portable.txt").exists():
        return PROGRAMMA
    appdata = os.environ.get("APPDATA")
    return (Path(appdata) if appdata else Path.home()) / "CurrentBench"


HOOFDMAP = _hoofdmap()
DATA = HOOFDMAP / "demo" if DEMO else HOOFDMAP
INSTELLINGEN = HOOFDMAP / "korad_instellingen.json"      # taal en weergave komen altijd hiervandaan, ook in de demo
try:
    DATA.mkdir(parents=True, exist_ok=True)
except OSError:      # opslaan meldt dat later zelf; starten moet altijd lukken
    pass


def bestand(naam: str) -> Path:
    """Een bestand of map van de gebruiker."""
    return DATA / naam


def bron(naam: str) -> Path:
    """Een bestand dat met het programma wordt meegeleverd."""
    return _BRON / naam


def herstart_opdracht(demo: bool) -> list[str]:
    """De opdracht die het paneel opnieuw start."""
    opdracht = [sys.executable] if BEVROREN else [sys.executable, str(PROGRAMMA / "korad_paneel.py")]
    return opdracht + (["--demo"] if demo else [])
