"""Lokale koppeling van het Korad paneel (november 2026).

De seriele poort kan maar door een programma tegelijk open zijn. Met deze koppeling blijft het paneel de voeding
bedienen en kunnen scripts via het paneel meten en instellen, binnen dezelfde grenzen als de knoppen.

Veiligheid:
- luistert alleen op 127.0.0.1, dus niet op het netwerk (de telefoonpagina is iets anders);
- elke aanvraag heeft de code uit korad_instellingen.json nodig, in de kop X-Korad-Code;
- uitvoeren gebeurt in de hoofdthread van het paneel, met dezelfde controles als de knoppen;
- uitgang aanzetten en spanning verhogen onder spanning kan alleen met "akkoord": true; uitzetten kan altijd.

GET  /api/stand                  wat de voeding nu doet
GET  /api/metingen?sec=60        {"metingen": [[tijd, volt, ampere], ...]} van de laatste seconden
POST /api/zet       {"v": 5.0, "i": 0.5, "akkoord": false}   eerst de stroomgrens, dan de spanning
POST /api/aan       {"akkoord": true}
POST /api/uit       {}
POST /api/markering {"tekst": "..."}

Meekijken en bedienen (zie korad_acties.py):
GET  /api/scherm?venster=hoofd&breed=1600   PNG van een venster van het paneel
GET  /api/vensters                          welke vensters open staan
GET  /api/dialogen                          vragen die nu op de gebruiker wachten
GET  /api/acties                            alle opdrachten
POST /api/actie     {"actie": "...", "akkoord": false, ...}   geeft een nummer
GET  /api/actie?id=7                        uitslag van die opdracht
"""
from __future__ import annotations

from korad_taal import tr

import hmac
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

import korad_acties

HOST = "127.0.0.1"
KOPPEL_HOSTS = ("127.0.0.1", "localhost")      # andere namen in de Host-kop weigeren (DNS-rebinding)
MAX_BODY = 4000


def maak_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KoradKoppeling"

        def log_message(self, *a):
            pass

        def _stuur(self, status, obj):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _mag(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in KOPPEL_HOSTS:
                return False
            code = app.settings.get("api_code") or ""
            gegeven = self.headers.get("X-Korad-Code") or ""
            return bool(code) and hmac.compare_digest(gegeven.encode(), code.encode())

        def _in_paneel(self, functie):
            status, obj = app._api_uitvoeren(functie)
            if isinstance(obj, bytes):
                self.send_response(status)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(obj)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(obj)
            else:
                self._stuur(status, obj)

        def do_GET(self):
            if not self._mag():
                return self._stuur(403, {"fout": tr("geen toegang")})
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/stand":
                return self._in_paneel(app._api_stand)
            if u.path == "/api/metingen":
                try:
                    sec = float(urllib.parse.parse_qs(u.query).get("sec", ["60"])[0])
                except ValueError:
                    return self._stuur(400, {"fout": tr("sec is geen getal")})
                return self._in_paneel(lambda: app._api_metingen(sec))
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/api/scherm":
                try:
                    breed = int(q.get("breed", ["1800"])[0])
                except ValueError:
                    return self._stuur(400, {"fout": tr("breed is geen getal")})
                naam = q.get("venster", ["hoofd"])[0]
                return self._in_paneel(lambda: korad_acties.scherm(app, naam, max(200, min(breed, 4000))))
            if u.path == "/api/vensters":
                return self._in_paneel(lambda: (200, {"open": korad_acties.open_vensters(app)}))
            # deze drie lopen niet via de hoofdthread: ze moeten ook werken terwijl er een vraag openstaat
            if u.path == "/api/dialogen":
                return self._stuur(200, {"dialogen": korad_acties.dialogen()})
            if u.path == "/api/acties":
                return self._stuur(200, {"acties": korad_acties.lijst()})
            if u.path == "/api/actie":
                try:
                    r = korad_acties.uitslag(app, int(q.get("id", ["0"])[0]))
                except ValueError:
                    r = None
                return self._stuur(200 if r else 404, r or {"fout": tr("onbekend nummer")})
            self._stuur(404, {"fout": tr("niet gevonden")})

        def do_POST(self):
            if not self._mag():
                return self._stuur(403, {"fout": tr("geen toegang")})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._stuur(413, {"fout": tr("te groot")})
            try:
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                return self._stuur(400, {"fout": tr("geen geldige JSON")})
            acties = {"/api/zet": lambda: app._api_zet(data), "/api/aan": lambda: app._api_aan(data),
                      "/api/uit": app._api_uit, "/api/markering": lambda: app._api_markering(data),
                      "/api/actie": lambda: korad_acties.start(app, data)}
            actie = acties.get(urllib.parse.urlparse(self.path).path)
            if actie is None:
                return self._stuur(404, {"fout": tr("niet gevonden")})
            self._in_paneel(actie)

    return Handler
