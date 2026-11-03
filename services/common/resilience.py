"""resilience.py -- patterns de résilience réutilisés par tous les services (bibliothèque standard).

Patterns : timeout, retry (backoff exponentiel + jitter, respect de Retry-After), circuit breaker,
bulkhead, rate limiting (token bucket), load shedding à priorités, cache résilient (stale-if-error).
Chaque pattern expose ses métriques. La variable d'environnement RESILIENCE=off désactive tous les
patterns (mode « avant ») pour mesurer leur apport lors des expériences de chaos.
"""
import json, os, random, socket, threading, time, urllib.error, urllib.request

from . import metrics as M

ACTIF = os.environ.get("RESILIENCE", "on").lower() != "off"
SERVICE = os.environ.get("SERVICE_NAME", "service")

# ---------------------------------------------------------------- métriques des patterns
BREAKER_ETAT = M.Gauge("circuit_breaker_state", "0 = fermé, 1 = semi-ouvert, 2 = ouvert", ("service", "dependance"))
BREAKER_OUVERTURES = M.Counter("circuit_breaker_opened_total", "Ouvertures du circuit", ("service", "dependance"))
BREAKER_REJETS = M.Counter("circuit_breaker_rejected_total", "Appels refusés circuit ouvert", ("service", "dependance"))
RETRIES = M.Counter("retries_total", "Nouvelles tentatives effectuées", ("service", "dependance"))
TIMEOUTS = M.Counter("timeouts_total", "Appels sortants en timeout", ("service", "dependance"))
BULKHEAD_EN_COURS = M.Gauge("bulkhead_in_flight", "Appels en cours dans le cloisonnement", ("service", "dependance"))
BULKHEAD_REJETS = M.Counter("bulkhead_rejected_total", "Appels refusés : cloisonnement plein", ("service", "dependance"))
RATE_LIMITED = M.Counter("rate_limited_total", "Requêtes refusées 429", ("service",))
SHED = M.Counter("load_shed_total", "Requêtes délestées 503", ("service", "prioritaire"))
SHED_EN_COURS = M.Gauge("load_shedder_in_flight", "Requêtes admises par le load shedder", ("service",))
CACHE = M.Counter("cache_requests_total", "Résultats du cache résilient", ("service", "resultat"))
FALLBACKS = M.Counter("fallback_total", "Réponses dégradées servies", ("service", "type"))


# ---------------------------------------------------------------- erreurs
class ErreurTransitoire(ConnectionError):
    """Erreur sur laquelle un retry a un sens (5xx, 429, connexion impossible)."""

    def __init__(self, message, code=0, retry_after=None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class CircuitOuvert(ErreurTransitoire):
    pass


class BulkheadPlein(ErreurTransitoire):
    pass


# ---------------------------------------------------------------- appel HTTP avec timeout
def appel_http(url, timeout=1.0, methode="GET", corps=None, entetes=None, dependance="dep"):
    """Appel HTTP JSON. Renvoie (code, json, entetes). Lève ErreurTransitoire (429/5xx/réseau),
    TimeoutError (délai dépassé) ou urllib.error.HTTPError (4xx permanent)."""
    if not ACTIF:
        timeout = 30.0                      # mode « avant » : pas de timeout court
    data = json.dumps(corps).encode() if corps is not None else None
    h = {"Content-Type": "application/json", **(entetes or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=methode)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            brut = r.read()
            M.APPELS_SORTANTS.inc(service=SERVICE, dependance=dependance, resultat="ok")
            return r.status, (json.loads(brut) if brut else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        M.APPELS_SORTANTS.inc(service=SERVICE, dependance=dependance, resultat=str(e.code))
        if e.code in (429, 502, 503, 504):
            raise ErreurTransitoire(f"HTTP {e.code}", e.code, e.headers.get("Retry-After")) from e
        raise
    except (socket.timeout, TimeoutError) as e:
        TIMEOUTS.inc(service=SERVICE, dependance=dependance)
        M.APPELS_SORTANTS.inc(service=SERVICE, dependance=dependance, resultat="timeout")
        raise TimeoutError(f"timeout {timeout}s sur {dependance}") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            TIMEOUTS.inc(service=SERVICE, dependance=dependance)
            M.APPELS_SORTANTS.inc(service=SERVICE, dependance=dependance, resultat="timeout")
            raise TimeoutError(f"timeout {timeout}s sur {dependance}") from e
        M.APPELS_SORTANTS.inc(service=SERVICE, dependance=dependance, resultat="connexion")
        raise ErreurTransitoire(str(e.reason)) from e
    finally:
        M.LATENCE_SORTANTE.observe(time.monotonic() - t0, service=SERVICE, dependance=dependance)


# ---------------------------------------------------------------- retry
def avec_retry(fn, tentatives=3, base=0.1, plafond=2.0, dependance="dep"):
    """Exécute fn() avec retry borné, backoff exponentiel + jitter complet, respect de Retry-After."""
    if not ACTIF:
        tentatives = 1
    for t in range(tentatives):
        try:
            return fn()
        except (ErreurTransitoire, TimeoutError) as e:
            if isinstance(e, (CircuitOuvert, BulkheadPlein)) or t == tentatives - 1:
                raise
            ra = getattr(e, "retry_after", None)
            try:
                delai = min(float(ra), plafond)
            except (TypeError, ValueError):
                delai = random.uniform(0, min(plafond, base * 2 ** t))
            RETRIES.inc(service=SERVICE, dependance=dependance)
            time.sleep(delai)


# ---------------------------------------------------------------- circuit breaker
class CircuitBreaker:
    """Ouvre après `seuil` échecs consécutifs ; réessaie une sonde après `delai` s (semi-ouvert)."""

    def __init__(self, dependance, seuil=5, delai=10.0):
        self.dependance, self.seuil, self.delai = dependance, seuil, delai
        self.echecs, self.etat, self.ouvert_depuis = 0, "ferme", 0.0
        self.lock = threading.Lock()
        self._publier()

    def _publier(self):
        BREAKER_ETAT.set({"ferme": 0, "semi": 1, "ouvert": 2}[self.etat], service=SERVICE, dependance=self.dependance)

    def appeler(self, fn):
        if not ACTIF:
            return fn()
        with self.lock:
            if self.etat == "ouvert":
                if time.monotonic() - self.ouvert_depuis < self.delai:
                    BREAKER_REJETS.inc(service=SERVICE, dependance=self.dependance)
                    raise CircuitOuvert(f"circuit {self.dependance} ouvert", 503,
                                        max(1, int(self.delai - (time.monotonic() - self.ouvert_depuis))))
                self.etat = "semi"
                self._publier()
        try:
            resultat = fn()
        except (ErreurTransitoire, TimeoutError):
            with self.lock:
                self.echecs += 1
                if self.etat == "semi" or self.echecs >= self.seuil:
                    if self.etat != "ouvert":
                        BREAKER_OUVERTURES.inc(service=SERVICE, dependance=self.dependance)
                    self.etat, self.ouvert_depuis = "ouvert", time.monotonic()
                self._publier()
            raise
        with self.lock:
            self.echecs, self.etat = 0, "ferme"
            self._publier()
        return resultat


# ---------------------------------------------------------------- bulkhead
class Bulkhead:
    """Cloisonnement : au plus `max_en_cours` appels simultanés vers une dépendance, attente bornée."""

    def __init__(self, dependance, max_en_cours=8, attente=0.05):
        self.dependance, self.attente = dependance, attente
        self.sem = threading.BoundedSemaphore(max_en_cours)

    def appeler(self, fn):
        if not ACTIF:
            return fn()
        if not self.sem.acquire(timeout=self.attente):
            BULKHEAD_REJETS.inc(service=SERVICE, dependance=self.dependance)
            raise BulkheadPlein(f"bulkhead {self.dependance} plein", 503, 1)
        BULKHEAD_EN_COURS.inc(service=SERVICE, dependance=self.dependance)
        try:
            return fn()
        finally:
            BULKHEAD_EN_COURS.dec(service=SERVICE, dependance=self.dependance)
            self.sem.release()


# ---------------------------------------------------------------- rate limiting
class TokenBucket:
    def __init__(self, capacite, debit):
        self.capacite, self.debit = capacite, debit
        self.jetons, self.dernier = float(capacite), time.monotonic()
        self.lock = threading.Lock()

    def consommer(self):
        """0 si autorisé, sinon le temps d'attente (s) avant le prochain jeton."""
        with self.lock:
            maintenant = time.monotonic()
            self.jetons = min(self.capacite, self.jetons + (maintenant - self.dernier) * self.debit)
            self.dernier = maintenant
            if self.jetons >= 1:
                self.jetons -= 1
                return 0.0
            return (1 - self.jetons) / self.debit


class RateLimiter:
    """Un token bucket par client (X-Client-Id ou IP)."""

    def __init__(self, capacite=20, debit=10.0):
        self.capacite, self.debit, self.buckets, self.lock = capacite, debit, {}, threading.Lock()

    def attente(self, client):
        if not ACTIF:
            return 0.0
        with self.lock:
            b = self.buckets.get(client)
            if b is None:
                b = self.buckets[client] = TokenBucket(self.capacite, self.debit)
        a = b.consommer()
        if a > 0:
            RATE_LIMITED.inc(service=SERVICE)
        return a


# ---------------------------------------------------------------- load shedding
class LoadShedder:
    """Au plus `capacite` requêtes simultanées ; une part est réservée aux requêtes prioritaires."""

    def __init__(self, capacite=16, reserve=0.25):
        self.capacite = capacite
        self.seuil_normal = int(capacite * (1 - reserve))
        self.en_cours, self.lock = 0, threading.Lock()

    def entrer(self, prioritaire=False):
        if not ACTIF:
            return True
        with self.lock:
            if self.en_cours < (self.capacite if prioritaire else self.seuil_normal):
                self.en_cours += 1
                SHED_EN_COURS.set(self.en_cours, service=SERVICE)
                return True
        SHED.inc(service=SERVICE, prioritaire=str(prioritaire).lower())
        return False

    def sortir(self):
        if not ACTIF:
            return
        with self.lock:
            self.en_cours -= 1
            SHED_EN_COURS.set(self.en_cours, service=SERVICE)


# ---------------------------------------------------------------- cache résilient
class CacheResilient:
    """Cache avec TTL de fraîcheur et TTL « stale-if-error » : si la source échoue, on sert la valeur
    périmée (réponse dégradée) tant qu'elle a moins de `stale` secondes."""

    def __init__(self, ttl=5.0, stale=300.0):
        self.ttl, self.stale, self.donnees, self.lock = ttl, stale, {}, threading.Lock()

    def obtenir(self, cle, charger):
        """Renvoie (valeur, degrade)."""
        maintenant = time.monotonic()
        with self.lock:
            entree = self.donnees.get(cle)
        if ACTIF and entree and maintenant - entree[1] < self.ttl:
            CACHE.inc(service=SERVICE, resultat="hit")
            return entree[0], False
        try:
            valeur = charger()
        except (ErreurTransitoire, TimeoutError):
            if ACTIF and entree and maintenant - entree[1] < self.stale:
                CACHE.inc(service=SERVICE, resultat="stale")
                FALLBACKS.inc(service=SERVICE, type="cache_stale")
                return entree[0], True
            CACHE.inc(service=SERVICE, resultat="miss_erreur")
            raise
        with self.lock:
            self.donnees[cle] = (valeur, time.monotonic())
        CACHE.inc(service=SERVICE, resultat="miss")
        return valeur, False
