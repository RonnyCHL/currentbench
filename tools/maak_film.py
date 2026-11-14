"""Makes a one-minute film of the program: the demo running live, then the screenshots.

    py tests/proef_paneel.py en           (and: py tests/proef_paneel.py en licht; makes the screenshots)
    py -m pip install imageio-ffmpeg      (or set FFMPEG to an ffmpeg.exe)
    py tools/maak_film.py en

Writes docs/film/currentbench-<language>.mp4. The live part uses the built-in demo with a simulated supply and says so.
"""
from __future__ import annotations

import ctypes
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

TAAL = next((a for a in sys.argv[1:] if a in ("nl", "en", "de")), "en")
WORK = Path(tempfile.mkdtemp(prefix="korad_film_"))
os.environ.update(KORAD_TAAL=TAAL, KORAD_THEMA="donker", KORAD_DEMO="1", KORAD_DATA=str(WORK))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import korad_paneel as kp  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

B, H, FPS = 1920, 1080, 30
BALK = 136                      # hoogte van de tekstbalk onderin
ACHTER = (15, 18, 22)
TEKST_KLEUR = (232, 235, 240)
GRIJS = (141, 150, 164)
BLAUW = (61, 123, 242)
FONT = "C:/Windows/Fonts/bahnschrift.ttf"
AFDRUKKEN = ROOT / "tests" / "afdrukken"
UIT = ROOT / "docs" / "film" / f"currentbench-{TAAL}.mp4"
SEC_DIA, SEC_TITEL, SEC_EIND, SEC_FADE = 2.7, 3.0, 3.5, 0.3

TEKSTEN = {
    "en": {"sub": "For Korad power supplies", "demo": "Free and open source. Shown with the built-in demo: a simulated supply.",
           "live": ("Live meters and chart: see exactly what your circuit draws", "Switch-on: the inrush current is right there in the chart",
                    "Current limit reached: the status bar turns amber at once", "Emergency stop: Esc always turns the output off"),
           "dia": ("Projects: your own limits. Anything above them is refused", "Guards: \"current above 300 mA for 5 s, output off\"",
                   "Test programs with steps, ramps and pass or fail", "Startup curve: faults show up at just a few volts",
                   "Component tester: diodes, LEDs and small resistors", "Overnight test, with notifications and a report",
                   "Compare two logs, with the differences in a table", "Bench mode: readable from across the room",
                   "Your phone as a remote: watch, and turn the output off", "English, Dutch and German", "Light or dark"),
           "eind": ("Try it without a power supply", "Choose DEMO in the port list", "Idea and direction: Ronny Hullegie, ronnyhullegie.nl. Code: Claude (Anthropic). Free, MIT licence.")},
    "nl": {"sub": "Voor Korad-voedingen", "demo": "Gratis en open source. Getoond met de ingebouwde demo: een nagebootste voeding.",
           "live": ("Live meters en grafiek: zie precies wat je schakeling trekt", "Inschakelen: de inschakelpiek staat meteen in de grafiek",
                    "Stroomgrens bereikt: de statusbalk wordt meteen amber", "Noodstop: Esc zet de uitgang altijd uit"),
           "dia": ("Projecten: je eigen grenzen. Alles daarboven wordt geweigerd", "Bewaking: \"stroom boven 300 mA, 5 s lang, uitgang uit\"",
                   "Testprogramma's met stappen, hellingen en goed of fout", "Opstartcurve: fouten zie je al bij een paar volt",
                   "Onderdelentester: diodes, leds en kleine weerstanden", "Nachttest, met meldingen en een rapport",
                   "Twee logs vergelijken, met de verschillen in een tabel", "Werkbankstand: leesbaar van een afstand",
                   "Je telefoon als afstandsbediening: kijken en uitzetten", "Nederlands, Engels en Duits", "Licht of donker"),
           "eind": ("Probeer het zonder voeding", "Kies DEMO in de poortlijst", "Idee en opdracht: Ronny Hullegie, ronnyhullegie.nl. Code: Claude (Anthropic). Gratis, MIT-licentie.")},
    "de": {"sub": "Für Korad-Netzgeräte", "demo": "Kostenlos und Open Source. Gezeigt mit der eingebauten Demo: ein simuliertes Netzgerät.",
           "live": ("Live-Anzeigen und Diagramm: sieh genau, was deine Schaltung zieht", "Einschalten: der Einschaltstrom steht sofort im Diagramm",
                    "Stromgrenze erreicht: die Statusleiste wird sofort gelb", "Not-Aus: Esc schaltet den Ausgang immer aus"),
           "dia": ("Projekte: deine eigenen Grenzen. Alles darüber wird abgelehnt", "Überwachung: \"Strom über 300 mA, 5 s lang, Ausgang aus\"",
                   "Testprogramme mit Schritten, Rampen und Gut oder Fehler", "Anlaufkurve: Fehler siehst du schon bei wenigen Volt",
                   "Bauteiltester: Dioden, LEDs und kleine Widerstände", "Nachttest, mit Meldungen und einem Bericht",
                   "Zwei Logs vergleichen, mit den Unterschieden in einer Tabelle", "Werkbankmodus: aus der Ferne lesbar",
                   "Dein Telefon als Fernbedienung: ansehen und ausschalten", "Deutsch, Englisch und Niederländisch", "Hell oder dunkel"),
           "eind": ("Probiere es ohne Netzgerät aus", "Wähle DEMO in der Portliste", "Idee und Vorgaben: Ronny Hullegie, ronnyhullegie.nl. Code: Claude (Anthropic). Kostenlos, MIT-Lizenz.")},
}[TAAL]
DIAS = ("projecten", "bewaking", "programma", "opstartcurve_uitslag", "onderdeel_uitslag", "nachttest", "vergelijken_uitslag", "werkbank",
        "telefoon", "instellingen", "licht_hoofd")


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


U32, G32 = ctypes.windll.user32, ctypes.windll.gdi32


def venster_beeld(hwnd: int) -> Image.Image:
    r = wintypes.RECT()
    U32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = U32.GetWindowDC(hwnd)
    mdc = G32.CreateCompatibleDC(hdc)
    bmp = G32.CreateCompatibleBitmap(hdc, w, h)
    G32.SelectObject(mdc, bmp)
    U32.PrintWindow(hwnd, mdc, 2)
    buf = ctypes.create_string_buffer(w * h * 4)
    G32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    G32.DeleteObject(bmp)
    G32.DeleteDC(mdc)
    U32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


def opname() -> tuple[list[tuple[float, bytes]], list[float]]:
    """De demo live opnemen. Geeft de beelden met hun tijd en de tijden waarop elk onderschrift begint."""
    kp.App._say = lambda self, text: None
    kp.App._beep = lambda self, kind: None
    app = kp.App()
    uit: dict = {"beelden": [], "stappen": []}

    def ui(f):
        klaar = threading.Event()
        app.after(0, lambda: (f(), klaar.set()))
        klaar.wait(20)

    def zet(v, i):
        def doe():
            for veld, waarde in ((app.v_entry, v), (app.i_entry, i)):
                veld.delete(0, "end")
                veld.insert(0, waarde)
            app._apply()
        ui(doe)

    def draad():
        while not app.dev or app.vset is None:
            time.sleep(0.1)
        zet("3.3", "1.0")
        ui(app._toggle_out)
        for v, wacht in (("5", 5), ("9", 5), ("12", 6)):
            time.sleep(wacht)
            kp.messagebox.askyesno = lambda *a, **k: True
            zet(v, "1.0")
        time.sleep(3)
        hwnd = int(app.wm_frame(), 16)
        stop, t0 = threading.Event(), time.time()

        def filmer():
            while not stop.is_set():
                t = time.time() - t0
                im = venster_beeld(hwnd)
                im.thumbnail((B, H - BALK), Image.BILINEAR)
                b = io.BytesIO()
                im.save(b, "JPEG", quality=90)
                uit["beelden"].append((t, b.getvalue()))
                time.sleep(max(0.0, 1 / 20 - (time.time() - t0 - t)))

        f = threading.Thread(target=filmer, daemon=True)
        f.start()
        uit["stappen"].append(0.0)
        time.sleep(4.5)
        uit["stappen"].append(time.time() - t0)
        ui(app._toggle_out)
        time.sleep(1.2)
        ui(app._toggle_out)
        time.sleep(3.8)
        uit["stappen"].append(time.time() - t0)
        zet("12", "0.1")
        time.sleep(5.0)
        kp.messagebox.askyesno = lambda *a, **k: True
        zet("12", "1.0")
        time.sleep(1.5)
        uit["stappen"].append(time.time() - t0)
        ui(lambda: app._emergency_stop("Esc"))
        time.sleep(4.0)
        stop.set()
        f.join(3)
        uit["einde"] = time.time() - t0
        app.after(0, app.destroy)

    app.after(600, threading.Thread(target=draad, daemon=True).start)
    app.mainloop()
    return uit["beelden"], uit["stappen"], uit["einde"]


def lettertype(maat: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, maat)


def tekst_midden(d: ImageDraw.ImageDraw, y: int, tekst: str, maat: int, kleur) -> None:
    f = lettertype(maat)
    d.text(((B - d.textlength(tekst, font=f)) / 2, y), tekst, font=f, fill=kleur)


def icoon(maat: int) -> Image.Image:
    im = Image.open(ROOT / "korad.ico")
    im.size = (256, 256)
    return im.convert("RGBA").resize((maat, maat), Image.LANCZOS)


def kaart(regels) -> Image.Image:
    vel = Image.new("RGB", (B, H), ACHTER)
    ic = icoon(190)
    vel.paste(ic, ((B - 190) // 2, 215), ic)
    d = ImageDraw.Draw(vel)
    for y, tekst, maat, kleur in regels:
        tekst_midden(d, y, tekst, maat, kleur)
    return vel


def met_balk(onderschrift: str) -> Image.Image:
    vel = Image.new("RGB", (B, H), ACHTER)
    d = ImageDraw.Draw(vel)
    d.rectangle((0, H - BALK, B, H), fill=(23, 27, 33))
    d.rectangle((0, H - BALK, B, H - BALK + 3), fill=BLAUW)
    tekst_midden(d, H - BALK + 44, onderschrift, 46, TEKST_KLEUR)
    return vel


def plak(vel: Image.Image, beeld: Image.Image) -> Image.Image:
    uit = vel.copy()
    uit.paste(beeld, ((B - beeld.width) // 2, (H - BALK - beeld.height) // 2))
    return uit


def dia_beeld(naam: str, zoom: float) -> Image.Image:
    bron = DIA_BRON.setdefault(naam, Image.open(AFDRUKKEN / f"{TAAL}_{naam}.png").convert("RGB"))
    maat = min((B - 90) / bron.width, (H - BALK - 50) / bron.height) * zoom
    return bron.resize((round(bron.width * maat), round(bron.height * maat)), Image.BICUBIC)


DIA_BRON: dict[str, Image.Image] = {}


def film(beelden, stappen, einde) -> None:
    exe = os.environ.get("FFMPEG")
    if not exe:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    UIT.parent.mkdir(parents=True, exist_ok=True)
    proces = subprocess.Popen([exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{B}x{H}", "-r", str(FPS), "-i", "-",
                               "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(UIT)],
                              stdin=subprocess.PIPE)
    vorige = [None]

    def schrijf(im: Image.Image) -> None:
        proces.stdin.write(im.tobytes())
        vorige[0] = im

    def fade_naar(eerste: Image.Image) -> None:
        if vorige[0] is None:
            return
        for n in range(1, round(SEC_FADE * FPS)):
            schrijf(Image.blend(vorige[0], eerste, n / (SEC_FADE * FPS)))

    titel = kaart(((435, "CurrentBench", 96, TEKST_KLEUR), (560, TEKSTEN["sub"], 44, GRIJS), (680, TEKSTEN["demo"], 30, GRIJS)))
    for _ in range(round(SEC_TITEL * FPS)):
        schrijf(titel)

    balken = [met_balk(t) for t in TEKSTEN["live"]]
    ontleed = {}

    def live(t: float) -> Image.Image:
        i = min(range(len(beelden)), key=lambda k: abs(beelden[k][0] - t))
        if i not in ontleed:
            ontleed.clear()
            ontleed[i] = Image.open(io.BytesIO(beelden[i][1])).convert("RGB")
        stap = sum(1 for s in stappen if s <= t) - 1
        return plak(balken[max(stap, 0)], ontleed[i])

    fade_naar(live(0.0))
    for n in range(round(einde * FPS)):
        schrijf(live(n / FPS))

    for naam, onderschrift in zip(DIAS, TEKSTEN["dia"]):
        balk = met_balk(onderschrift)
        fade_naar(plak(balk, dia_beeld(naam, 1.0)))
        totaal = round(SEC_DIA * FPS)
        for n in range(totaal):
            schrijf(plak(balk, dia_beeld(naam, 1.0 + 0.03 * n / totaal)))

    a, b, c = TEKSTEN["eind"]
    eind = kaart(((435, a, 84, TEKST_KLEUR), (560, b, 44, GRIJS), (680, c, 28, GRIJS)))
    fade_naar(eind)
    for _ in range(round(SEC_EIND * FPS)):
        schrijf(eind)
    proces.stdin.close()
    proces.wait()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    beelden, stappen, einde = opname()
    print(f"opname: {len(beelden)} beelden in {einde:.1f} s ({len(beelden) / einde:.1f} per seconde)")
    film(beelden, stappen, einde)
    shutil.rmtree(WORK, ignore_errors=True)
    print("written:", UIT, f"{UIT.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
