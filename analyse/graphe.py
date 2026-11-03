"""graphe.py -- graphe de dépendances de ShopFlow résilient (matplotlib) -> ../docs/graphe_dependances.png"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "graphe_dependances.png")
fig, ax = plt.subplots(figsize=(12, 6.4))
ax.set_xlim(0, 12.3)
ax.set_ylim(0, 6.9)
ax.axis("off")

N = {  # x, y, w, libellé, sous-titre, couleur
    "client":    (0.3, 4.5, 1.4, "Clients\n(web, mobile)", "retry borné + backoff,\nrespect de Retry-After", "#eeeeee"),
    "gateway":   (2.4, 4.5, 1.9, "gateway :8000", "rate limiting 429\nload shedding 503\ncache résilient\ntimeouts", "#dbeafe"),
    "orders":    (5.1, 4.5, 1.9, "orders :8001", "bulkhead par dépendance\ntimeout + retry\ncircuit breakers\nfallback paiement différé", "#dbeafe"),
    "inventory": (7.9, 5.3, 1.8, "inventory :8002 ×2", "réservation idempotente", "#dcfce7"),
    "payment":   (7.9, 3.4, 1.8, "payment :8003 ×2", "timeout 1 s, retry ×3\ncircuit breaker 5/10 s\nclé d'idempotence", "#dcfce7"),
    "bank":      (10.3, 3.4, 1.6, "banque externe\n:8080", "instable (/admin)\n99,9 %", "#fde2e2"),
    "prom":      (2.4, 1.2, 1.9, "Prometheus :9090", "scrape /metrics 5 s\nrègles SLO + alertes", "#fef3c7"),
    "grafana":   (5.1, 1.2, 1.9, "Grafana :3000", "tableau de bord\nShopFlow — résilience", "#fef3c7"),
}
for k, (x, y, w, lib, sous, col) in N.items():
    hh = 1.1 if k in ("prom", "grafana", "client", "bank") else 1.25
    ax.add_patch(FancyBboxPatch((x, y), w, hh, boxstyle="round,pad=0.04", fc=col, ec="#555", lw=1.4))
    ax.text(x + w / 2, y + hh - 0.22, lib, ha="center", va="center", fontsize=9, weight="bold")
    ax.text(x + w / 2, y + 0.42 if hh > 1.2 else y + 0.33, sous, ha="center", va="center", fontsize=6.8, color="#333")


def fl(a, b, txt, ya=0.6, yb=0.6, style="-", col="#333", dx=0, dy=0.1):
    xa, ya0, wa = N[a][:3]
    xb, yb0, wb = N[b][:3]
    p1, p2 = (xa + wa, ya0 + ya), (xb, yb0 + yb)
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=12, lw=1.3, ls=style, color=col))
    ax.text((p1[0] + p2[0]) / 2 + dx, (p1[1] + p2[1]) / 2 + dy, txt, fontsize=6.8, ha="center", color="#1a4d8f",
            bbox=dict(fc="white", ec="none", pad=0.4))


fl("client", "gateway", "HTTPS sync")
fl("gateway", "orders", "POST /checkout\ntimeout 4 s", dy=0.22)
fl("orders", "inventory", "1. POST /reserve\ntimeout 0,5 s, retry ×2", ya=0.9, yb=0.5, dy=0.3)
fl("orders", "payment", "2. POST /pay\ntimeout 2 s, bulkhead 8", ya=0.3, yb=0.7, dy=-0.35)
fl("payment", "bank", "POST /payments\nIdempotency-Key, timeout 1 s", ya=0.6, yb=0.6, dy=0.28)
# gateway -> inventory (cache)
ax.add_patch(FancyArrowPatch((N["gateway"][0] + 1.9, N["gateway"][1] + 1.15), (N["inventory"][0], N["inventory"][1] + 0.95),
                             arrowstyle="-|>", mutation_scale=12, lw=1.1, ls="--", color="#555", connectionstyle="arc3,rad=-0.25"))
ax.text(5.3, 6.55, "GET /products (cache 5 s, stale-if-error 300 s)", fontsize=6.8, color="#1a4d8f", ha="center", bbox=dict(fc="white", ec="none", pad=0.4))
# rejeu asynchrone
ax.text(6.05, 4.2, "travailleur asynchrone :\nrejoue les paiements « pending » toutes les 3 s", fontsize=6.5, ha="center", color="#7c2d12",
        bbox=dict(fc="#fff7ed", ec="#fdba74", pad=0.4))
# observabilité
for s in ("gateway", "orders", "inventory", "payment", "bank"):
    x, y, w = N[s][:3]
    ax.add_patch(FancyArrowPatch((x + w / 2, y), (N["prom"][0] + 1.0, N["prom"][1] + 1.1), arrowstyle="-", lw=0.6, ls=":", color="#b45309"))
ax.text(1.0, 2.6, "/metrics\n(scrape)", fontsize=6.5, color="#b45309")
ax.add_patch(FancyArrowPatch((N["prom"][0] + 1.9, N["prom"][1] + 0.55), (N["grafana"][0], N["grafana"][1] + 0.55), arrowstyle="-|>", mutation_scale=10, lw=1, color="#b45309"))
ax.text(0.3, 0.35, "Légende : bleu = services avec patterns de protection ; vert = étages redondés (2 réplicas) ; rouge = dépendance externe instable ; "
        "jaune = observabilité.\nTous les appels métier sont synchrones (HTTP) ; seul le rejeu des paiements différés est asynchrone.", fontsize=7, color="#333")
ax.set_title("ShopFlow résilient — graphe de dépendances et patterns par lien", fontsize=11)
fig.tight_layout()
os.makedirs(os.path.dirname(OUT), exist_ok=True)
fig.savefig(OUT, dpi=160)
print("écrit", os.path.abspath(OUT))
