"""orders -- création des commandes : réservation du stock (inventory) puis paiement (payment).

POST /orders {"order_id", "client_id", "sku", "qty", "montant"}
   -> 201 {"status": "paid"}            stock réservé et paiement accepté
   -> 202 {"status": "pending_payment"} stock réservé, paiement indisponible : commande acceptée, paiement
                                        rejoué en arrière-plan (dégradation gracieuse + découplage asynchrone)
   -> 503 + Retry-After                 stock indisponible (pas de vente sans stock)
GET /orders/<id>, GET /orders/stats
Patterns : bulkhead par dépendance, timeout, retry, circuit breaker, fallback « paiement différé ».
"""
import os, threading, time
from common import server, resilience as R, metrics as M
from common.server import route, dependance_sante

INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://inventory:8002")
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://payment:8003")

bulk_inv = R.Bulkhead("inventory", max_en_cours=16)
bulk_pay = R.Bulkhead("payment", max_en_cours=8)
cb_inv = R.CircuitBreaker("inventory", seuil=5, delai=5.0)
cb_pay = R.CircuitBreaker("payment", seuil=3, delai=10.0)

COMMANDES, LOCK = {}, threading.Lock()
EN_ATTENTE = M.Gauge("orders_pending_payment", "Commandes en attente de paiement", ("service",))
STATUTS = M.Counter("orders_total", "Commandes par statut final", ("service", "status"))


def reserver(order_id, sku, qty):
    def appel():
        return R.appel_http(f"{INVENTORY_URL}/reserve", timeout=0.5, methode="POST",
                            corps={"order_id": order_id, "sku": sku, "qty": qty}, dependance="inventory")
    return R.avec_retry(lambda: bulk_inv.appeler(lambda: cb_inv.appeler(appel)), tentatives=2, dependance="inventory")


def payer(order_id, montant):
    def appel():
        return R.appel_http(f"{PAYMENT_URL}/pay", timeout=2.0, methode="POST",
                            corps={"order_id": order_id, "montant": montant}, dependance="payment")
    return bulk_pay.appeler(lambda: cb_pay.appeler(appel))        # pas de retry ici : payment en fait déjà


@route("POST", "/orders")
def creer(h, req):
    c = req.corps
    order_id = str(c.get("order_id") or f"o-{int(time.time() * 1000)}")
    sku, qty, montant = c.get("sku", "A12"), int(c.get("qty", 1)), float(c.get("montant", 10))
    with LOCK:
        if order_id in COMMANDES:                                   # idempotence côté commande
            return h.repondre(200, {**COMMANDES[order_id], "rejeu": True})
    # 1) stock : obligatoire
    try:
        code, corps, _ = reserver(order_id, sku, qty)
    except (R.ErreurTransitoire, TimeoutError) as e:
        STATUTS.inc(service=server.SERVICE, status="rejected_stock")
        return h.repondre(503, {"error": f"stock indisponible : {e}", "order_id": order_id},
                          {"Retry-After": getattr(e, "retry_after", None) or 2})
    except Exception as e:                                         # 409 stock insuffisant, 404 sku
        STATUTS.inc(service=server.SERVICE, status="refused")
        return h.repondre(getattr(e, "code", 400), {"error": str(e), "order_id": order_id})
    commande = {"order_id": order_id, "client_id": c.get("client_id"), "sku": sku, "qty": qty, "montant": montant}
    # 2) paiement : dégradable
    try:
        payer(order_id, montant)
        commande["status"] = "paid"
        STATUTS.inc(service=server.SERVICE, status="paid")
        code = 201
    except (R.ErreurTransitoire, TimeoutError) as e:
        if not R.ACTIF:                                            # mode « avant » : pas de fallback
            STATUTS.inc(service=server.SERVICE, status="failed_payment")
            return h.repondre(503, {"error": f"paiement impossible : {e}", "order_id": order_id}, {"Retry-After": 2})
        commande["status"] = "pending_payment"
        commande["raison"] = str(e)
        R.FALLBACKS.inc(service=server.SERVICE, type="pending_payment")
        STATUTS.inc(service=server.SERVICE, status="pending_payment")
        code = 202
    with LOCK:
        COMMANDES[order_id] = commande
        EN_ATTENTE.set(sum(1 for o in COMMANDES.values() if o["status"] == "pending_payment"), service=server.SERVICE)
    h.repondre(code, commande, {"X-Degraded": "pending_payment"} if code == 202 else None)


@route("GET", "/orders/stats")
def stats(h, req):
    with LOCK:
        comptes = {}
        for o in COMMANDES.values():
            comptes[o["status"]] = comptes.get(o["status"], 0) + 1
    h.repondre(200, {"total": len(COMMANDES), "par_statut": comptes})


@route("GET", "/orders")
def lire(h, req):
    oid = req.chemin.rsplit("/", 1)[-1]
    with LOCK:
        o = COMMANDES.get(oid)
    h.repondre(200, o) if o else h.repondre(404, {"error": "commande inconnue"})


def rejouer_paiements():
    """Travailleur d'arrière-plan : rejoue les paiements en attente (découplage asynchrone)."""
    while True:
        time.sleep(3)
        with LOCK:
            attente = [o for o in COMMANDES.values() if o["status"] == "pending_payment"]
        for o in attente[:20]:
            try:
                payer(o["order_id"], o["montant"])
                with LOCK:
                    o["status"], o["paid_late"] = "paid", True
                STATUTS.inc(service=server.SERVICE, status="paid_late")
            except Exception:
                break                                                # la banque est encore en panne : on réessaiera
        with LOCK:
            EN_ATTENTE.set(sum(1 for o in COMMANDES.values() if o["status"] == "pending_payment"), service=server.SERVICE)


@dependance_sante("inventory")
def etat_inventory():
    try:
        R.appel_http(f"{INVENTORY_URL}/health/ready", timeout=0.3, dependance="inventory_health")
        return {"etat": "up", "breaker": cb_inv.etat}
    except Exception as e:
        return {"etat": f"down ({type(e).__name__})", "breaker": cb_inv.etat}


@dependance_sante("payment")
def etat_payment():
    try:
        R.appel_http(f"{PAYMENT_URL}/health/ready", timeout=0.3, dependance="payment_health")
        return {"etat": "up", "breaker": cb_pay.etat}
    except Exception as e:
        return {"etat": f"down ({type(e).__name__})", "breaker": cb_pay.etat}


if __name__ == "__main__":
    threading.Thread(target=rejouer_paiements, daemon=True).start()
    server.demarrer(int(os.environ.get("PORT", "8001")))
