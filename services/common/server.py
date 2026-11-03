"""server.py -- socle HTTP commun : routage, JSON, métriques par requête, sondes de santé, arrêt propre.

Chaque service définit ses routes avec le décorateur @route("GET", "/chemin") puis appelle demarrer().
Fournis automatiquement : GET /metrics, /health/live, /health/ready, /health/startup, /health/deps.
"""
import json, os, signal, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import metrics as M

SERVICE = os.environ.get("SERVICE_NAME", "service")
STARTUP_DELAI = float(os.environ.get("STARTUP_DELAI", "2"))
DRAIN = float(os.environ.get("DRAIN", "5"))
DEMARRE_A = time.monotonic()
ETAT = {"arret": False}
ROUTES = []            # (methode, prefixe, handler)
DEPENDANCES = {}       # nom -> fonction () -> dict(etat)
PRET_SUPPLEMENTAIRE = []   # fonctions () -> liste de causes de non-readiness


def route(methode, prefixe):
    def deco(fn):
        ROUTES.append((methode, prefixe, fn))
        return fn
    return deco


def dependance_sante(nom):
    """Déclare une fonction de diagnostic de dépendance, exposée sur /health/deps (pas dans la readiness :
    une dépendance partagée ne doit pas sortir toutes les instances du pool en même temps)."""
    def deco(fn):
        DEPENDANCES[nom] = fn
        return fn
    return deco


class Requete:
    def __init__(self, handler):
        self.handler = handler
        u = urlparse(handler.path)
        self.chemin, self.query = u.path, parse_qs(u.query)
        self.entetes = handler.headers
        self.client = handler.headers.get("X-Client-Id") or handler.client_address[0]
        self._corps = None

    @property
    def corps(self):
        if self._corps is None:
            n = int(self.entetes.get("Content-Length") or 0)
            brut = self.handler.rfile.read(n) if n else b""
            self._corps = json.loads(brut) if brut else {}
        return self._corps


class Api(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"shopflow-{SERVICE}"

    def log_message(self, *a):
        pass

    def repondre(self, code, corps, entetes=None):
        data = json.dumps(corps).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (entetes or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(data)
        self._code = code

    def _traiter(self, methode):
        req = Requete(self)
        self._code = 500
        t0 = time.monotonic()
        libelle = "autre"
        M.EN_COURS.inc(service=SERVICE)
        try:
            if methode == "GET" and req.chemin == "/metrics":
                data = M.exposer().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                self._code, libelle = 200, "/metrics"
                return
            if req.chemin.startswith("/health/"):
                libelle = req.chemin
                return _sante(self, req.chemin)
            for m, prefixe, fn in ROUTES:
                if m == methode and (req.chemin == prefixe or req.chemin.startswith(prefixe.rstrip("/") + "/")):
                    libelle = prefixe
                    fn(self, req)
                    return
            self.repondre(404, {"error": "not found"})
        except (ConnectionError, BrokenPipeError, OSError) as e:   # le client a raccroché : rien à envoyer
            self._code = 499
        except Exception as e:                                      # dernier filet
            try:
                self.repondre(500, {"error": f"{type(e).__name__}: {e}"})
            except OSError:
                self._code = 499
        finally:
            M.EN_COURS.dec(service=SERVICE)
            if libelle != "/metrics" and not libelle.startswith("/health/"):
                M.REQUETES.inc(service=SERVICE, route=libelle, code=str(self._code))
                M.LATENCE.observe(time.monotonic() - t0, service=SERVICE, route=libelle)

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def do_DELETE(self):
        self._traiter("DELETE")


def _sante(h, chemin):
    demarre = time.monotonic() - DEMARRE_A >= STARTUP_DELAI
    if chemin == "/health/live":
        return h.repondre(200, {"status": "alive", "service": SERVICE})
    if chemin == "/health/startup":
        return h.repondre(200 if demarre else 503, {"status": "started" if demarre else "starting"})
    if chemin == "/health/deps":
        return h.repondre(200, {nom: fn() for nom, fn in DEPENDANCES.items()})
    if chemin == "/health/ready":
        causes = []
        if not demarre:
            causes.append("demarrage en cours")
        if ETAT["arret"]:
            causes.append("arret en cours")
        for fn in PRET_SUPPLEMENTAIRE:
            causes.extend(fn())
        return h.repondre(200 if not causes else 503, {"ready": not causes, "causes": causes, "service": SERVICE})
    h.repondre(404, {"error": "not found"})


def demarrer(port):
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.request_queue_size = 256
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer(("", port), Api)

    def arret(signum, frame):
        if ETAT["arret"]:
            return
        ETAT["arret"] = True
        print(f"[{SERVICE}] signal {signum} : readiness en échec, drain {DRAIN:.0f} s", flush=True)

        def fin():
            time.sleep(DRAIN)
            srv.shutdown()
        threading.Thread(target=fin, daemon=True).start()

    for s in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, s):
            signal.signal(getattr(signal, s), arret)
    print(f"[{SERVICE}] écoute sur :{port} (résilience {'ON' if os.environ.get('RESILIENCE', 'on') != 'off' else 'OFF'})", flush=True)
    srv.serve_forever()
    srv.server_close()
    print(f"[{SERVICE}] arrêté proprement", flush=True)
