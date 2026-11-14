"""Language support for the Korad panel.

The source text in the code is Dutch. tr("...") looks that text up in lang/<language>.json and returns the
translation, or the Dutch text if there is none. Texts with values use numbered fields:
    tr("Verbonden met {0} op {1}", idn, poort)

The language is chosen once, when the program starts:
    1. the environment variable KORAD_TAAL (nl, en or de), used by the tests;
    2. "taal" in korad_instellingen.json, set in the Settings window;
    3. the language of Windows; English if that is not Dutch or German.

To add a language: copy lang/en.json, translate the values and add the language to TALEN below.
"""
from __future__ import annotations

import json
import os

import korad_paden

MAP = korad_paden.bron("lang")
INSTELLINGEN = korad_paden.INSTELLINGEN
TALEN = {"nl": "Nederlands", "en": "English", "de": "Deutsch"}
KOMMA_TALEN = ("nl", "de")     # talen met een komma als decimaalteken

_MAANDEN = {
    "nl": ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"),
}
_DATUM = {"nl": "{d} {m} {j}", "en": "{m} {d}, {j}", "de": "{d}. {m} {j}"}
_EENHEDEN_GESPROKEN = {
    "nl": {"mAh": "milliampère-uur", "mA": "milliampère", "Wh": "wattuur", "V": "volt", "A": "ampère", "W": "watt",
           "Ω": "ohm", "%": "procent"},
    "en": {"mAh": "milliamp hours", "mA": "milliamps", "Wh": "watt hours", "V": "volts", "A": "amps", "W": "watts",
           "Ω": "ohms", "%": "percent"},
    "de": {"mAh": "Milliamperestunden", "mA": "Milliampere", "Wh": "Wattstunden", "V": "Volt", "A": "Ampere",
           "W": "Watt", "Ω": "Ohm", "%": "Prozent"},
}
_STEM_VOORKEUR = {"nl": "nl-NL", "en": "en-US", "de": "de-DE"}   # de stem die de voorkeur heeft in Windows

_taal = "nl"
_catalogus: dict[str, str] = {}


def windows_taal() -> str:
    """De taal van Windows als die wordt ondersteund, anders Engels."""
    try:
        import ctypes
        taal_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "en"
    return {0x13: "nl", 0x07: "de"}.get(taal_id, "en")


def gekozen_taal() -> str:
    """Welke taal er bij deze start hoort."""
    code = os.environ.get("KORAD_TAAL", "")
    if code not in TALEN:
        try:
            code = json.loads(INSTELLINGEN.read_text(encoding="utf-8")).get("taal", "")
        except (OSError, ValueError, AttributeError):
            code = ""
    return code if code in TALEN else windows_taal()


def gekozen_thema() -> str:
    """Donker of licht; de variabele KORAD_THEMA gaat voor (voor de tests)."""
    code = os.environ.get("KORAD_THEMA", "")
    if code not in ("donker", "licht"):
        try:
            code = json.loads(INSTELLINGEN.read_text(encoding="utf-8")).get("thema", "")
        except (OSError, ValueError, AttributeError):
            code = ""
    return "licht" if code == "licht" else "donker"


def laad(code: str) -> None:
    """Zet de taal en leest de vertalingen."""
    global _taal, _catalogus
    _taal = code if code in TALEN else "en"
    _catalogus = {}
    if _taal != "nl":
        try:
            _catalogus = json.loads((MAP / f"{_taal}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalogus = {}


def huidig() -> str:
    return _taal


def tr(bron: str, *waarden) -> str:
    """De vertaling van een Nederlandse brontekst, met de waarden ingevuld."""
    tekst = _catalogus.get(bron, bron)
    if not waarden:
        return tekst
    try:
        return tekst.format(*waarden)
    except (IndexError, KeyError, ValueError):      # een fout in een vertaling mag het paneel nooit laten vallen
        return bron.format(*waarden)


def dec(tekst) -> str:
    """Een getal als tekst met het decimaalteken van de gekozen taal."""
    tekst = str(tekst)
    return tekst.replace(".", ",") if _taal in KOMMA_TALEN else tekst


def datum(dag: int, maand: int, jaar: int) -> str:
    return _DATUM[_taal].format(d=dag, m=_MAANDEN[_taal][maand - 1], j=jaar)


def eenheden_gesproken() -> dict[str, str]:
    return _EENHEDEN_GESPROKEN[_taal]


def stem_voorkeur() -> str:
    return _STEM_VOORKEUR[_taal]


laad(gekozen_taal())
