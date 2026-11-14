"""Build CurrentBench for Windows, so it runs without Python.

    <python with pyinstaller, pyserial and pillow> tools/maak_exe.py [output folder] [--onefile]

Default: a folder CurrentBench/ with CurrentBench.exe and its files, plus CurrentBench-<version>-windows.zip to hand
out. A folder starts faster than a single file and virus scanners trust it more: a single file unpacks itself on every
start, which is also what malware does. With --onefile you get that single CurrentBench.exe anyway.

Translations, the icon and the manuals travel with the program; user data goes to the folder described in
korad_paden.py. Output folder default: dist/ next to the program.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
EEN_BESTAND = "--onefile" in sys.argv
UIT = Path(ARGS[0]).resolve() if ARGS else ROOT / "dist"
WERK = UIT / "_bouw"


def versie() -> str:
    m = re.search(r'^VERSIE = "([^"]+)"', (ROOT / "korad_paneel.py").read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1) if m else "0"


def data(bron: str, doel: str) -> str:
    return f"{ROOT / bron};{doel}"


def main() -> int:
    opdracht = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile" if EEN_BESTAND else "--onedir",
        "--windowed", "--name", "CurrentBench", "--icon", str(ROOT / "korad.ico"),
        "--distpath", str(UIT), "--workpath", str(WERK), "--specpath", str(WERK),
        "--add-data", data("lang", "lang"),
        "--add-data", data("korad.ico", "."),
        "--add-data", data("LICENSE", "."),
    ]
    for pdf in sorted((ROOT / "docs" / "handleiding").glob("handleiding-*.pdf")):
        opdracht += ["--add-data", f"{pdf};docs/handleiding"]
    opdracht.append(str(ROOT / "korad_paneel.py"))
    klaar = subprocess.run(opdracht, cwd=ROOT)
    if klaar.returncode != 0:
        return klaar.returncode
    if EEN_BESTAND:
        exe = UIT / "CurrentBench.exe"
        print(f"built: {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
        return 0
    map_ = UIT / "CurrentBench"
    shutil.copy2(ROOT / "LICENSE", map_ / "LICENSE.txt")
    zip_ = shutil.make_archive(str(UIT / f"CurrentBench-{versie()}-windows"), "zip", root_dir=UIT, base_dir="CurrentBench")
    print(f"built: {map_ / 'CurrentBench.exe'}")
    print(f"built: {zip_} ({Path(zip_).stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
