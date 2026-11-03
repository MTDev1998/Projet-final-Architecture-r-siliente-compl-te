"""metrics.py -- registre de métriques minimal au format texte Prometheus (bibliothèque standard).

Chaque pattern de résilience expose ses métriques ici : compteurs (Counter), jauges (Gauge) et
histogrammes de latence (Histogram). Le texte produit par `exposer()` est servi sur /metrics.
"""
import threading

_LOCK = threading.Lock()
_REGISTRE = []
BUCKETS_DEFAUT = (0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)


def _labels_str(labels, valeurs):
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in zip(labels, valeurs)) + "}"


class _Base:
    type_prom = "untyped"

    def __init__(self, nom, aide, labels=()):
        self.nom, self.aide, self.labels = nom, aide, tuple(labels)
        self.valeurs = {}
        with _LOCK:
            _REGISTRE.append(self)

    def _cle(self, kw):
        return tuple(str(kw.get(l, "")) for l in self.labels)


class Counter(_Base):
    type_prom = "counter"

    def inc(self, n=1, **kw):
        cle = self._cle(kw)
        with _LOCK:
            self.valeurs[cle] = self.valeurs.get(cle, 0) + n

    def lignes(self):
        for cle, v in sorted(self.valeurs.items()):
            yield f"{self.nom}{_labels_str(self.labels, cle)} {v}"


class Gauge(_Base):
    type_prom = "gauge"

    def set(self, v, **kw):
        with _LOCK:
            self.valeurs[self._cle(kw)] = v

    def inc(self, n=1, **kw):
        cle = self._cle(kw)
        with _LOCK:
            self.valeurs[cle] = self.valeurs.get(cle, 0) + n

    def dec(self, n=1, **kw):
        self.inc(-n, **kw)

    def lignes(self):
        for cle, v in sorted(self.valeurs.items()):
            yield f"{self.nom}{_labels_str(self.labels, cle)} {v}"


class Histogram(_Base):
    type_prom = "histogram"

    def __init__(self, nom, aide, labels=(), buckets=BUCKETS_DEFAUT):
        super().__init__(nom, aide, labels)
        self.buckets = tuple(sorted(buckets))

    def observe(self, v, **kw):
        cle = self._cle(kw)
        with _LOCK:
            h = self.valeurs.setdefault(cle, {"n": 0, "somme": 0.0, "b": [0] * len(self.buckets)})
            h["n"] += 1
            h["somme"] += v
            for i, borne in enumerate(self.buckets):
                if v <= borne:
                    h["b"][i] += 1

    def lignes(self):
        for cle, h in sorted(self.valeurs.items()):
            cumul = 0
            for i, borne in enumerate(self.buckets):
                cumul = h["b"][i]
                yield f"{self.nom}_bucket{_labels_str(self.labels + ('le',), cle + (repr(float(borne)),))} {cumul}"
            yield f"{self.nom}_bucket{_labels_str(self.labels + ('le',), cle + ('+Inf',))} {h['n']}"
            yield f"{self.nom}_sum{_labels_str(self.labels, cle)} {h['somme']:.6f}"
            yield f"{self.nom}_count{_labels_str(self.labels, cle)} {h['n']}"


def exposer():
    """Rend toutes les métriques au format texte Prometheus 0.0.4."""
    out = []
    with _LOCK:
        metriques = list(_REGISTRE)
    for m in metriques:
        out.append(f"# HELP {m.nom} {m.aide}")
        out.append(f"# TYPE {m.nom} {m.type_prom}")
        out.extend(m.lignes())
    return "\n".join(out) + "\n"


# --- métriques communes à tous les services -------------------------------------------------
REQUETES = Counter("http_requests_total", "Requêtes HTTP reçues", ("service", "route", "code"))
LATENCE = Histogram("http_request_duration_seconds", "Durée des requêtes HTTP", ("service", "route"))
EN_COURS = Gauge("http_requests_in_flight", "Requêtes en cours de traitement", ("service",))
APPELS_SORTANTS = Counter("outbound_requests_total", "Appels sortants vers une dépendance", ("service", "dependance", "resultat"))
LATENCE_SORTANTE = Histogram("outbound_request_duration_seconds", "Durée des appels sortants", ("service", "dependance"))
