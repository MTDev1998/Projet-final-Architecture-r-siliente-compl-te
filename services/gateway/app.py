"""gateway -- point d'entrée HTTP public de ShopFlow.

GET  /products         catalogue (cache résilient : stale-if-error -> X-Degraded: stale)
POST /checkout         passe une commande (prioritaire pour le load shedder) -> orders
GET  /orders/<id>      suivi de commande -> orders
Patterns : rate limiting par client (429 + Retry-After), load shedding à priorités (503 + Retry-After),
timeouts, cache résilient, readiness qui ne dépend que de l'état local.
"""
import os, time
from common import server, resilience as R
from common.server import route, dependance_sante

ORDERS_URL = os.environ.get("ORDERS_URL", "http://orders:8001")
INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://inventory:8002")

limiteur = R.RateLimiter(capacite=int(os.environ.get("RL_CAPACITE", "20")), debit=float(os.environ.get("RL_DEBIT", "10")))
delesteur = R.LoadShedder(capacite=int(os.environ.get("SHED_CAPACITE", "32")), reserve=0.25)
cache_produits = R.CacheResilient(ttl=5.0, stale=300.0)
cb_orders = R.CircuitBreaker("orders", seuil=10, delai=5.0)


def proteger(h, req, prioritaire):
    """Rate limiting puis load shedding. Renvoie True si la requête peut être traitée."""
    attente = limiteur.attente(req.client)
    if attente > 0:
        h.repondre(429, {"error": "trop de requêtes"}, {"Retry-After": max(1, int(attente + 0.999))})
        return False
    if not delesteur.entrer(prioritaire):
        h.repondre(503, {"error": "service saturé, réessayez"}, {"Retry-After": 1})
        return False
    return True


@route("GET", "/products")
def products(h, req):
    if not proteger(h, req, prioritaire=False):
        return
    try:
        try:
            valeur, degrade = cache_produits.obtenir(
                "products", lambda: R.appel_http(f"{INVENTORY_URL}/products", timeout=0.8, dependance="inventory")[1])
            h.repondre(200, valeur, {"X-Degraded": "stale"} if degrade else None)
        except (R.ErreurTransitoire, TimeoutError) as e:
            h.repondre(503, {"error": f"catalogue indisponible : {e}"}, {"Retry-After": 2})
    finally:
        delesteur.sortir()


@route("POST", "/checkout")
def checkout(h, req):
    if not proteger(h, req, prioritaire=True):
        return
    try:
        corps = dict(req.corps)
        corps.setdefault("client_id", req.client)
        try:
            code, rep, ent = cb_orders.appeler(
                lambda: R.appel_http(f"{ORDERS_URL}/orders", timeout=4.0, methode="POST", corps=corps, dependance="orders"))
            h.repondre(code, rep, {"X-Degraded": ent["X-Degraded"]} if ent.get("X-Degraded") else None)
        except R.CircuitOuvert as e:
            h.repondre(503, {"error": "commandes indisponibles (circuit ouvert)"}, {"Retry-After": e.retry_after})
        except (R.ErreurTransitoire, TimeoutError) as e:
            h.repondre(503, {"error": f"commande impossible : {e}"}, {"Retry-After": getattr(e, "retry_after", None) or 2})
    finally:
        delesteur.sortir()


@route("GET", "/orders")
def suivi(h, req):
    if not proteger(h, req, prioritaire=False):
        return
    try:
        oid = req.chemin.rsplit("/", 1)[-1]
        try:
            code, rep, _ = R.appel_http(f"{ORDERS_URL}/orders/{oid}", timeout=1.0, dependance="orders")
            h.repondre(code, rep)
        except (R.ErreurTransitoire, TimeoutError) as e:
            h.repondre(503, {"error": str(e)}, {"Retry-After": 2})
        except Exception as e:
            h.repondre(getattr(e, "code", 500), {"error": str(e)})
    finally:
        delesteur.sortir()


@dependance_sante("orders")
def etat_orders():
    try:
        R.appel_http(f"{ORDERS_URL}/health/ready", timeout=0.3, dependance="orders_health")
        return {"etat": "up", "breaker": cb_orders.etat}
    except Exception as e:
        return {"etat": f"down ({type(e).__name__})", "breaker": cb_orders.etat}


if __name__ == "__main__":
    server.demarrer(int(os.environ.get("PORT", "8000")))
