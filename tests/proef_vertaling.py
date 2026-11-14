"""Checks the translation files against the code, without opening a window.

    py tests/proef_vertaling.py

Every text in the code must have a translation, and a translation must keep the same {0} fields, HTML tags and line
breaks as its Dutch source.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
VELD = re.compile(r"(?<!\{)\{\d+(?:![rsa])?(?::[^{}]*)?\}(?!\})")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")

gebruikt = set()
for bestand in ROOT.glob("korad_*.py"):
    for knoop in ast.walk(ast.parse(bestand.read_text(encoding="utf-8"))):
        if isinstance(knoop, ast.Call) and isinstance(knoop.func, ast.Name) and knoop.func.id == "tr" and knoop.args:
            eerste = knoop.args[0]
            if isinstance(eerste, ast.Constant) and isinstance(eerste.value, str):
                gebruikt.add(eerste.value)
paneel = (ROOT / "korad_paneel.py").read_text(encoding="utf-8")
gebruikt |= set(re.findall(r"@@(.+?)@@", paneel[paneel.index("WEB_PAGE = r"):paneel.index("def web_pagina")]))

fouten = []
for taal in ("en", "de"):
    catalogus = json.loads((ROOT / "lang" / f"{taal}.json").read_text(encoding="utf-8"))
    fouten += [f"{taal}: missing: {k[:80]}" for k in sorted(gebruikt - set(catalogus))]
    for bron, vertaling in catalogus.items():
        if sorted(VELD.findall(bron)) != sorted(VELD.findall(vertaling)):
            fouten.append(f"{taal}: fields differ: {bron[:80]}")
        if sorted(TAG.findall(bron)) != sorted(TAG.findall(vertaling)):
            fouten.append(f"{taal}: tags differ: {bron[:80]}")
        if bron.count("\n") != vertaling.count("\n"):
            fouten.append(f"{taal}: line breaks differ: {bron[:80]}")
    print(f"{taal}: {len(catalogus)} texts, {len(gebruikt)} used in the code")
for fout in fouten:
    print("FAIL", fout)
print("RESULT:", "all good" if not fouten else f"{len(fouten)} problems")
sys.exit(1 if fouten else 0)
