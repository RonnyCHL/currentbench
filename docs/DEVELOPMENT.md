# Development notes

## Layout

| File | Purpose |
|---|---|
| `korad_paneel.py` | The application: serial link, windows, chart, test functions |
| `korad_paden.py` | Where data and bundled files are, and how to restart |
| `korad_voeding.py` | Serial protocol and model recognition |
| `korad_demo.py` | The simulated supply used by `--demo` |
| `korad_analyse.py` | Calculations without a screen: restart counter, fingerprints, marker parsing |
| `korad_koppeling.py` | Local HTTP API on 127.0.0.1 |
| `korad_acties.py` | The actions the API can start, with the same limits as the buttons |
| `korad_klant.py` | Python client and command line for the API |
| `korad_taal.py` | Language, number and date handling |
| `lang/*.json` | Translations |
| `qrcodegen.py` | Third-party QR code library (MIT) |
| `tools/maak_icoon.py` | Draws `korad.ico` |

Names and comments in the code are Dutch.

## Data and bundled files

Never build a path from `__file__`. Use `korad_paden.bestand()` for anything a user creates and `korad_paden.bron()` for
files that ship with the program. That keeps the panel working from Program Files and as a single .exe.

The demo stores its data in the subfolder `demo`. Language and appearance are shared with the normal panel; nothing else is.

## Models and limits

`korad_voeding.herken()` turns the `*IDN?` reply into a name and a range. To add a model, extend the patterns or the
Tenma table and add a case to `tests/proef_voeding.py`. Two-channel models are left out on purpose, because they use
other commands.

`MAX_V` and `MAX_A` hold the range of the connected supply and change when it connects. Always read limits through
`App._limits()`. It returns the lower of the project limit and the range of the supply, so a project made for a
60 V supply cannot exceed the limits of a 30 V one. An unknown device is only accepted after it has answered the Korad
queries and the user has confirmed it and entered its range.

## Translating text

The Dutch text in the code is the key. `tr()` returns the translation, or the Dutch text if there is none.

```python
tr("Verbonden met {0} op {1}", idn, poort)
```

Use `dec()` for a number that is already text, and `nl()` or `nlf()` to format a number. They follow the decimal
separator of the chosen language. The phone page marks its texts as `@@text@@`; `web_pagina()` fills them in.

To add a language, copy `lang/en.json`, translate the values and add the language to `TALEN`, `_MAANDEN`, `_DATUM`,
`_EENHEDEN_GESPROKEN` and `_STEM_VOORKEUR` in `korad_taal.py`. If the language uses a decimal comma, also add it to
`KOMMA_TALEN`.

## Never translate a stored or compared value

This is the main trap. A translated value that is saved or compared breaks behaviour without an error. In one case, a
guard set to turn the output off would only have warned.

- Stored guard and step values stay Dutch: `stroom`, `boven`, `uitgang uit`, `sprong`, `aan`.
- Use `Keuze` for a choice list. It shows the translation and returns the fixed value.
- Dictionary keys, icon keys, API parameters, CSV headers and file names stay untranslated.
- If text is compared after it has been translated, translate both sides: `msg == tr("Klaar")`.

## Markers are parsed

`korad_analyse.py` reads step bands and marker colours from the marker text, in the current language. A translation
must therefore start with the same word as the fixed entries for `stap`, `testprogramma`, `nachttest`, `opstartcurve`,
`accu`, `noodstop`, `stroomdip`, `afdruk` and `alarm`. `GOED`, `FOUT`, `ronde`, `Klaar`, `Gestopt`, `binnen de band`
and `buiten de band` must also keep their exact translations.

## Appearance

The colours are set near the top of `korad_paneel.py`. The light theme replaces them when the program starts, so a
change of language or appearance needs a restart. `_herstart_na_keuze()` offers that. Use `Knop` through `_btn()`: it
picks a readable text colour for each button colour.

## Manual

The text is in `docs/handleiding/bron/<language>.html`. Run the panel test in every language first, because it makes the
screenshots, then `py docs/handleiding/maak_handleiding.py`. Button names inside `[[ ]]` and `(( ))` are looked up in
`lang/`, so the manual always uses the words on the screen.

## Film

`py tools/maak_film.py <language>` records the demo live and adds the screenshots. It needs `imageio-ffmpeg`, or `FFMPEG` set to
an ffmpeg.exe, and the screenshots of the panel test in that language, also with `licht`.

## Tests

```
py tests/proef_paneel.py [nl|en|de] [licht]
py tests/proef_demo.py [nl|en|de]
py tests/proef_voeding.py
py tests/proef_analyse.py
py tests/proef_vertaling.py
```

`proef_paneel.py` uses a simulated supply and a temporary folder. It opens every window, runs the main functions and
writes screenshots to `tests/afdrukken/`. In English and German it reports text that still looks Dutch. Run it in every
language after changing text or a stored value. The environment variables `KORAD_TAAL` and `KORAD_THEMA` override the
saved choices, and `KORAD_DATA` sets the data folder.

The tests do not replace a check on a real supply.
