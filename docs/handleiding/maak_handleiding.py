"""Builds the manual as PDF in every language, with Microsoft Edge in headless mode.

    py tests/proef_paneel.py nl          (and en, de: makes the screenshots)
    py docs/handleiding/maak_handleiding.py [nl en de]

The text is in bron/<language>.html, with these markers:
    [[Instellingen]]         a button; [[blauw:Instellen]] gives it a colour (blauw, groen, rood)
    ((Spanning))             a label on the screen, in bold
    {{NAAM}}, {{VRIJ}}       the name of the program and of the unrestricted project
    {ref:id}                 the number of the chapter with that id
    @@ name | caption        a screenshot; @@smal for a small one, @@plaat for the main window with numbers

Text inside [[ ]] and (( )) is the Dutch source text of the program. It is looked up in lang/<language>.json, so the
manual always uses the words on the screen. An unknown text stops the build.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

HIER = Path(__file__).resolve().parent
ROOT = HIER.parents[1]
AFDRUKKEN = ROOT / "tests" / "afdrukken"
EDGE = next((p for p in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")) if p.exists()), None)
TITEL = {"nl": "Handleiding", "en": "User manual", "de": "Handbuch"}
INHOUD = {"nl": "Inhoud", "en": "Contents", "de": "Inhalt"}
OPDRACHT = {"nl": "Voor Korad-voedingen", "en": "For Korad power supplies", "de": "Für Korad-Netzgeräte"}
MET = {"nl": "Idee en opdracht: Ronny Hullegie. Code: Claude (Anthropic). Gratis en zonder garantie, MIT-licentie.",
       "en": "Idea and direction: Ronny Hullegie. Code: Claude (Anthropic). Free and without warranty, MIT licence.",
       "de": "Idee und Vorgaben: Ronny Hullegie. Code: Claude (Anthropic). Kostenlos und ohne Gewährleistung, MIT-Lizenz."}
# plaats van de nummers op het hoofdvenster, in procenten van het beeld
BOLLEN = ((45.0, 5.6), (6.2, 15.8), (31.1, 6.3), (81.3, 6.3), (19.0, 16.3), (62.7, 16.4), (96.0, 16.3), (33.0, 49.2),
          (6.2, 81.0), (6.2, 87.8), (6.2, 94.3))

CSS = """
:root { --ink:#1D2228; --muted:#5C6470; --line:#D8DDE3; --soft:#F3F5F8; --blue:#3D7BF2; --red:#D9443B; --green:#1E9E55; --dark:#0F1216; }
@page { size:A4; margin:15mm 17mm 17mm 17mm;
        @bottom-center { content:"CurrentBench  ·  " counter(page); font:8.5pt Bahnschrift,"Segoe UI",sans-serif; color:#7A828E; } }
@page :first { margin:0; @bottom-center { content:none; } }
* { box-sizing:border-box; }
html { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
body { margin:0; color:var(--ink); font:10.2pt/1.5 "Segoe UI",Arial,sans-serif; }
h1,h2,h3 { font-family:Bahnschrift,"Segoe UI",sans-serif; }
h2 { font-size:19pt; font-weight:600; margin:0 0 4mm; }
h2 .n { color:var(--blue); margin-right:3mm; }
h3 { font-size:12.5pt; font-weight:600; margin:6mm 0 1.5mm; break-after:avoid; }
p { margin:0 0 2.6mm; }
section { break-before:page; }
section.vervolg { break-before:auto; margin-top:9mm; }
figure { margin:3mm 0 5mm; break-inside:avoid; }
figure img { width:100%; display:block; border-radius:2mm; border:.3mm solid #C9CFD7; }
figure.smal img { width:60%; }
figcaption { font-size:8.8pt; color:var(--muted); margin-top:1.5mm; }
.plaat { position:relative; }
.bol { position:absolute; width:5.6mm; height:5.6mm; margin:-2.8mm 0 0 -2.8mm; border-radius:50%; background:var(--blue); color:#fff;
       text-align:center; font:600 8.6pt/5.6mm Bahnschrift,sans-serif; border:.25mm solid #fff; }
ol,ul { margin:0 0 3mm; padding-left:6mm; }
li { margin:0 0 1.2mm; }
b { font-weight:600; }
code { font:9.2pt Consolas,monospace; background:var(--soft); padding:0 1mm; border-radius:.8mm; }
.knop { display:inline-block; font:600 8.8pt Bahnschrift,sans-serif; padding:.2mm 2mm; border-radius:1mm; background:#21262E; color:#E8EBF0; white-space:nowrap; }
.knop.blauw { background:var(--blue); color:#fff; } .knop.groen { background:var(--green); color:#fff; } .knop.rood { background:var(--red); color:#fff; }
.kader { background:var(--soft); border-radius:2mm; padding:3mm 4mm; margin:3mm 0 4mm; break-inside:avoid; }
.kader p:last-child { margin-bottom:0; }
.kader .kop { font:600 9.5pt Bahnschrift,sans-serif; text-transform:uppercase; letter-spacing:.04em; color:var(--blue); margin-bottom:1mm; }
.kader.let-op { background:#FDF3E3; } .kader.let-op .kop { color:#9A5F00; }
table { border-collapse:collapse; width:100%; margin:2mm 0 4mm; font-size:9.6pt; break-inside:avoid; }
th { text-align:left; font:600 8.6pt Bahnschrift,sans-serif; color:var(--muted); padding:1.5mm 2mm; border-bottom:.4mm solid var(--line); }
td { padding:1.6mm 2mm; border-bottom:.25mm solid var(--line); vertical-align:top; }
td.nw { white-space:nowrap; }
ol.callouts { list-style:none; padding:0; columns:2; column-gap:8mm; counter-reset:c; }
ol.callouts li { counter-increment:c; position:relative; padding-left:8mm; break-inside:avoid; margin-bottom:2mm; }
ol.callouts li::before { content:counter(c); position:absolute; left:0; top:.3mm; width:5.2mm; height:5.2mm; border-radius:50%; background:var(--blue);
                         color:#fff; text-align:center; font:600 8.4pt/5.2mm Bahnschrift,sans-serif; }
ol.stappen { counter-reset:s; list-style:none; padding-left:0; }
ol.stappen li { counter-increment:s; position:relative; padding-left:8mm; }
ol.stappen li::before { content:counter(s); position:absolute; left:0; top:0; font:600 10.5pt Bahnschrift,sans-serif; color:var(--blue); }
.cover { height:296mm; display:flex; flex-direction:column; break-before:auto; }
.cover .band { background:var(--dark); color:#E8EBF0; padding:26mm 20mm 12mm; }
.cover .kicker { font:10pt Bahnschrift,sans-serif; letter-spacing:.18em; text-transform:uppercase; color:#8D96A4; margin:0 0 4mm; }
.cover h1 { font-size:42pt; font-weight:600; margin:0; line-height:1.05; }
.cover .sub { font-size:13.5pt; color:#C5CBD4; margin:4mm 0 0; }
.cover .shot { background:var(--dark); padding:0 20mm 16mm; }
.cover .shot img { width:100%; display:block; border-radius:2mm; border:.3mm solid #2A3039; }
.cover .meta { margin-top:auto; padding:0 20mm 6mm; font-size:9pt; color:#7A828E; }
.inhoud { columns:2; column-gap:10mm; padding:0; list-style:none; counter-reset:h; }
.inhoud li { counter-increment:h; padding:1.2mm 0; border-bottom:.25mm solid var(--line); break-inside:avoid; }
.inhoud li::before { content:counter(h); display:inline-block; width:7mm; color:var(--blue); font:600 10pt Bahnschrift,sans-serif; }
"""


def plaatje(taal: str, naam: str, map_: Path, breedte: int = 1500) -> str:
    bron = AFDRUKKEN / f"{taal}_{naam}.png"
    if not bron.exists():
        sys.exit(f"screenshot missing: {bron}. Run tests/proef_paneel.py {taal} first.")
    uit = map_ / f"{naam}.jpg"
    if not uit.exists():
        im = Image.open(bron).convert("RGB")
        if im.width > breedte:
            im = im.resize((breedte, round(im.height * breedte / im.width)), Image.LANCZOS)
        im.save(uit, quality=86, optimize=True)
    return uit.as_uri()


def wacht_op(pdf: Path, sec: float = 90.0) -> Path:
    """Edge geeft zijn opdracht meteen terug en schrijft de PDF daarna: wachten tot het bestand niet meer groeit."""
    einde, vorige = time.time() + sec, -1
    while time.time() < einde:
        maat = pdf.stat().st_size if pdf.exists() else -1
        if maat > 0 and maat == vorige:
            return pdf
        vorige = maat
        time.sleep(1.0)
    sys.exit(f"Edge did not write {pdf}")


def bouw(taal: str, map_: Path) -> Path:
    tekst = (HIER / "bron" / f"{taal}.html").read_text(encoding="utf-8")
    catalogus = json.loads((ROOT / "lang" / f"{taal}.json").read_text(encoding="utf-8")) if taal != "nl" else None
    alle = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
    onbekend = set()

    def scherm(bron: str) -> str:
        if bron not in alle:
            onbekend.add(bron)
        return html.escape(bron if catalogus is None else catalogus.get(bron, bron), quote=False)

    def knop(m: re.Match) -> str:
        kleur, _, bron = m.group(1).rpartition(":")
        return f'<span class="knop {kleur}">{scherm(bron)}</span>'

    naam = "CurrentBench"
    vrij = "Vrij" if catalogus is None else catalogus["Vrij"]
    tekst = tekst.replace("{{NAAM}}", naam).replace("{{VRIJ}}", vrij)
    tekst = re.sub(r"\[\[(.+?)\]\]", knop, tekst)
    tekst = re.sub(r"\(\((.+?)\)\)", lambda m: f"<b>{scherm(m.group(1))}</b>", tekst)
    if onbekend:
        sys.exit("not a text of the program: " + "; ".join(sorted(onbekend)))

    def figuur(m: re.Match) -> str:
        soort, plaat, onderschrift = m.group(1), m.group(2).strip(), m.group(3).strip()
        img = f'<img src="{plaatje(taal, plaat, map_)}" alt="">'
        if soort == "plaat":
            bollen = "".join(f'<span class="bol" style="left:{x}%;top:{y}%">{n}</span>' for n, (x, y) in enumerate(BOLLEN, 1))
            img = f'<div class="plaat">{img}{bollen}</div>'
        return f'<figure class="{soort}">{img}<figcaption>{onderschrift}</figcaption></figure>'

    tekst = re.sub(r"^@@(\w*) *(\w+) *\| *(.+)$", figuur, tekst, flags=re.M)
    hoofdstukken = re.findall(r'<section id="([\w-]+)"[^>]*><h2>(.+?)</h2>', tekst)
    nummer = {sid: n for n, (sid, _) in enumerate(hoofdstukken, 1)}
    tekst = re.sub(r"\{ref:([\w-]+)\}", lambda m: str(nummer[m.group(1)]), tekst)
    for sid, kop in hoofdstukken:
        tekst = tekst.replace(f'id="{sid}"', f'id="{sid}" data-x', 1)
        tekst = re.sub(rf'(<section id="{sid}" data-x[^>]*><h2>)', rf'\1<span class="n">{nummer[sid]}</span>', tekst, count=1)
    tekst = tekst.replace(" data-x", "")
    inhoud = "".join(f"<li>{kop}</li>" for _, kop in hoofdstukken)
    pagina = f"""<!doctype html><html lang="{taal}"><head><meta charset="utf-8"><title>{naam} - {TITEL[taal]}</title><style>{CSS}</style></head><body>
<div class="cover"><div class="band"><p class="kicker">{TITEL[taal]}</p><h1>{naam}</h1><p class="sub">{OPDRACHT[taal]}</p></div>
<div class="shot"><img src="{plaatje(taal, 'hoofd_aan', map_)}" alt=""></div>
<div class="meta">{MET[taal]}</div></div>
<section><h2>{INHOUD[taal]}</h2><ol class="inhoud">{inhoud}</ol></section>
{tekst}</body></html>"""
    bestand = map_ / "handleiding.html"
    bestand.write_text(pagina, encoding="utf-8")
    pdf = HIER / f"handleiding-{taal}.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={map_ / 'edge'}",
                    f"--print-to-pdf={pdf}", bestand.as_uri()],
                   check=True, capture_output=True, timeout=120)
    return wacht_op(pdf)


def main() -> None:
    if EDGE is None:
        sys.exit("Microsoft Edge not found")
    for taal in sys.argv[1:] or ["nl", "en", "de"]:
        with tempfile.TemporaryDirectory(prefix="korad_handleiding_", ignore_cleanup_errors=True) as t:
            pdf = bouw(taal, Path(t))
        print("written:", pdf, f"{pdf.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
