"""bank -- API bancaire externe simulée, volontairement instable (dépendance hors de notre contrôle).

Pilotage des pannes : GET /admin?fail_rate=0.3&latency=2&down=1&fail_after=0.2
  fail_rate  : probabilité de 503 avant traitement           latency : latence moyenne (s)
  down       : 1 = totalement indisponible                   fail_after : probabilité de 503 APRÈS débit (réponse perdue)
POST /payments (Idempotency-Key) débite ; GET /admin renvoie aussi le nombre de débits (preuve d'idempotence).
"""
import os, random, threading, time
from common import server
from common.server import route

CONFIG = {"fail_rate": 0.0, "fail_after": 0.0, "latency": 0.05, "down": 0}
CHARGES, PAYMENTS, LOCK = [], {}, threading.Lock()


def _instable(h):
    if CONFIG["down"]:
        h.repondre(503, {"error": "service down"}, {"Retry-After": 5})
        return True
    time.sleep(CONFIG["latency"] * random.uniform(0.5, 1.5))
    if random.random() < CONFIG["fail_rate"]:
        h.repondre(503, {"error": "erreur transitoire"})
        return True
    return False


@route("GET", "/admin")
def admin(h, req):
    for k in CONFIG:
        if k in req.query:
            CONFIG[k] = float(req.query[k][0])
    h.repondre(200, {**CONFIG, "charges": len(CHARGES), "cles_idempotence": len(PAYMENTS)})


@route("GET", "/health")
def health(h, req):
    h.repondre(200, {"status": "up"})


@route("POST", "/payments")
def payments(h, req):
    corps = req.corps
    if _instable(h):
        return
    cle = req.entetes.get("Idempotency-Key")
    with LOCK:
        if cle and cle in PAYMENTS:
            return h.repondre(200, {**PAYMENTS[cle], "rejeu": True})     # pas de nouveau débit
        paiement = {"id": len(CHARGES) + 1, "montant": corps.get("montant"), "order_id": corps.get("order_id")}
        CHARGES.append(paiement)
        if cle:
            PAYMENTS[cle] = paiement
    if random.random() < CONFIG["fail_after"]:
        return h.repondre(503, {"error": "réponse perdue"})            # débité, mais le client ne le sait pas
    h.repondre(201, paiement)


if __name__ == "__main__":
    server.demarrer(int(os.environ.get("PORT", "8080")))
