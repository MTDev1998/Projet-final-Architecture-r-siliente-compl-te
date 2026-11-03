"""payment -- encaissement via l'API bancaire externe (instable).

POST /pay {"order_id", "montant"} -> 201 payé | 503 + Retry-After (banque indisponible, circuit ouvert)
Patterns : timeout 1 s, retry x3 (sûr grâce à la clé d'idempotence = order_id), circuit breaker (5 échecs, 10 s).
La readiness ne dépend PAS de la banque (dépendance partagée) ; son état est exposé sur /health/deps.
"""
import os
from common import server, resilience as R
from common.server import route, dependance_sante

BANK_URL = os.environ.get("BANK_URL", "http://bank:8080")
breaker = R.CircuitBreaker("bank", seuil=5, delai=10.0)


@route("POST", "/pay")
def pay(h, req):
    c = req.corps
    order_id, montant = c.get("order_id"), c.get("montant")

    def appel():
        return R.appel_http(f"{BANK_URL}/payments", timeout=1.0, methode="POST",
                            corps={"order_id": order_id, "montant": montant},
                            entetes={"Idempotency-Key": str(order_id)}, dependance="bank")
    try:
        # plafond 0,5 s : on respecte Retry-After de la banque sans dépasser le budget de temps d'orders (2 s)
        code, corps, _ = R.avec_retry(lambda: breaker.appeler(appel), tentatives=3, base=0.1, plafond=0.5, dependance="bank")
        h.repondre(201, {"order_id": order_id, "montant": montant, "status": "paid", "bank_ref": corps.get("id")})
    except R.CircuitOuvert as e:
        h.repondre(503, {"error": "banque indisponible (circuit ouvert)", "order_id": order_id}, {"Retry-After": e.retry_after})
    except (R.ErreurTransitoire, TimeoutError) as e:
        h.repondre(503, {"error": f"banque en erreur : {e}", "order_id": order_id}, {"Retry-After": 2})


@dependance_sante("bank")
def etat_bank():
    try:
        code, corps, _ = R.appel_http(f"{BANK_URL}/health", timeout=0.3, dependance="bank_health")
        return {"etat": "up", "breaker": breaker.etat}
    except Exception as e:
        return {"etat": f"down ({type(e).__name__})", "breaker": breaker.etat}


if __name__ == "__main__":
    server.demarrer(int(os.environ.get("PORT", "8003")))
