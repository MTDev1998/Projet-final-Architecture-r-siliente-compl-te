"""inventory -- stock des produits (état en mémoire, réservation idempotente par order_id).

GET  /products            catalogue avec stock
GET  /stock/<sku>         stock d'un produit
POST /reserve             {"order_id", "sku", "qty"}  -> réserve (idempotent : même order_id = même réponse)
POST /release             {"order_id"}                -> libère une réservation (compensation)
"""
import os, random, threading, time
from common import server
from common.server import route

STOCK = {"A12": 120, "B07": 80, "C33": 50, "D01": 500}
PRIX = {"A12": 19.9, "B07": 49.0, "C33": 129.0, "D01": 4.5}
RESERVATIONS, LOCK = {}, threading.Lock()
LATENCE = float(os.environ.get("LATENCE_BASE", "0.02"))


@route("GET", "/products")
def products(h, req):
    time.sleep(LATENCE * random.uniform(0.5, 1.5))
    with LOCK:
        h.repondre(200, {"products": [{"sku": s, "prix": PRIX[s], "stock": q} for s, q in STOCK.items()]})


@route("GET", "/stock")
def stock(h, req):
    sku = req.chemin.rsplit("/", 1)[-1]
    time.sleep(LATENCE * random.uniform(0.5, 1.5))
    if sku not in STOCK:
        return h.repondre(404, {"error": "sku inconnu"})
    h.repondre(200, {"sku": sku, "stock": STOCK[sku]})


@route("POST", "/reserve")
def reserve(h, req):
    c = req.corps
    order_id, sku, qty = c.get("order_id"), c.get("sku"), int(c.get("qty", 1))
    time.sleep(LATENCE * random.uniform(0.5, 1.5))
    if sku not in STOCK:
        return h.repondre(404, {"error": "sku inconnu"})
    with LOCK:
        if order_id in RESERVATIONS:
            return h.repondre(200, {**RESERVATIONS[order_id], "rejeu": True})
        if STOCK[sku] < qty:
            return h.repondre(409, {"error": "stock insuffisant", "stock": STOCK[sku]})
        STOCK[sku] -= qty
        if STOCK[sku] < 5:                       # réassort automatique (fil rouge pédagogique)
            STOCK[sku] += 100
        RESERVATIONS[order_id] = {"order_id": order_id, "sku": sku, "qty": qty, "reserved": True}
        h.repondre(201, RESERVATIONS[order_id])


@route("POST", "/release")
def release(h, req):
    order_id = req.corps.get("order_id")
    with LOCK:
        r = RESERVATIONS.pop(order_id, None)
        if r:
            STOCK[r["sku"]] += r["qty"]
    h.repondre(200, {"released": bool(r)})


if __name__ == "__main__":
    server.demarrer(int(os.environ.get("PORT", "8002")))
