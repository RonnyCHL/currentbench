"""Build CurrentBench.exe: one file that runs without Python.

    <python with pyinstaller, pyserial and pillow> tools/maak_exe.py [output folder]

The result is <output folder>/CurrentBench.exe (default: dist/ next to the program). Translations, the icon and the
manuals travel inside the .exe; user data goes to the folder described in korad_paden.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "dist"
WERK = UIT / "_bouw"


def data(bron: str, doel: str) -> str:
    return f"{ROOT / bron};{doel}"


def main() -> int:
    opdracht = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "CurrentBench", "--icon", str(ROOT / "korad.ico"),
        "--distpath", str(UIT), "--workpath", str(WERK), "--specpath", str(WERK),
        "--add-data", data("lang", "lang"),
        "--add-data", data("korad.ico", "."),
        "--add-data", data("LICENSE", "."),
    ]
    for pdf in sorted((ROOT / "docs" / "handleiding").glob("handleiding-*.pdf")):
        opdracht += ["--add-data", f"{pdf};docs/handleiding"]
    opdracht.append(str(ROOT / "korad_paneel.py"))
    klaar = subprocess.run(opdracht, cwd=ROOT)
    exe = UIT / "CurrentBench.exe"
    if klaar.returncode == 0 and exe.exists():
        print(f"built: {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return klaar.returncode


if __name__ == "__main__":
    sys.exit(main())
