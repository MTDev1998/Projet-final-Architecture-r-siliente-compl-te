"""graphes.py -- trace les courbes Prometheus de la campagne de chaos -> docs/chaos_*.png
Usage : python graphes.py   (après experiences.py ; lit resultats/fenetre_campagne.json et resultats_*.json)
"""
import json, os, urllib.parse, urllib.request
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ICI = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(ICI), "docs")
PROM = os.environ.get("PROM", "http://127.0.0.1:9090")
os.makedirs(DOCS, exist_ok=True)

with open(os.path.join(ICI, "resultats", "fenetre_campagne.json"), encoding="utf-8") as f:
    fen = json.load(f)
res = {}
for mode in ("off", "on"):
    with open(os.path.join(ICI, "resultats", f"resultats_{mode}.json"), encoding="utf-8") as f:
        res[mode] = json.load(f)


def query_range(expr, debut, fin, pas="5s"):
    q = urllib.parse.urlencode({"query": expr, "start": debut, "end": fin, "step": pas})
    with urllib.request.urlopen(f"{PROM}/api/v1/query_range?{q}", timeout=30) as r:
        data = json.load(r)["data"]["result"]
    series = []
    for s in data:
        xs = [datetime.fromtimestamp(float(t)) for t, _ in s["values"]]
        ys = [float(v) if v not in ("NaN", "+Inf", "-Inf") else float("nan") for _, v in s["values"]]
        series.append((s["metric"], xs, ys))
    return series


def annoter(ax, mode):
    for r in res[mode]:
        ax.axvspan(datetime.fromtimestamp(r["t_inj"]), datetime.fromtimestamp(r["t_res"]), color="#fca5a5", alpha=0.25)
        ax.annotate(r["num"], (datetime.fromtimestamp((r["t_inj"] + r["t_res"]) / 2), 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, -10), textcoords="offset points", ha="center", fontsize=8, weight="bold")


def figure(nom, titre, courbes, ylabel, ylim=None, log=False):
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.8), sharey=True)
    for ax, mode in zip(axes, ("off", "on")):
        debut, fin = res[mode][0]["t_inj"] - 15, res[mode][-1]["t_fin"] + 5
        for expr, label, kw in courbes:
            for metric, xs, ys in query_range(expr, debut, fin):
                ax.plot(xs, ys, label=label.format(**metric) if metric else label, lw=1.3, **kw)
        annoter(ax, mode)
        ax.set_title(f"{'AVANT (RESILIENCE=off)' if mode == 'off' else 'APRÈS (RESILIENCE=on)'}", fontsize=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.grid(alpha=.3)
        if ylim:
            ax.set_ylim(*ylim)
        if log:
            ax.set_yscale("log")
    axes[0].set_ylabel(ylabel)
    h, l = axes[1].get_legend_handles_labels()
    if h:
        seen = {}
        for hh, ll in zip(h, l):
            seen.setdefault(ll, hh)
        axes[1].legend(seen.values(), seen.keys(), fontsize=7, loc="lower right")
    fig.suptitle(titre, fontsize=11)
    fig.tight_layout()
    out = os.path.join(DOCS, nom)
    fig.savefig(out, dpi=150)
    print("écrit", out)


figure("chaos_sli.png", "SLI de disponibilité du gateway (règle d'enregistrement, fenêtre 5 min) — zones rouges = pannes injectées (a..g)",
       [("slo:gateway_availability:ratio_rate5m", "disponibilité 5 min", {"color": "#1d4ed8"}),
        ("vector(0.995)", "SLO 99,5 %", {"color": "black", "ls": "--", "lw": 1})], "disponibilité", ylim=(0.5, 1.01))
figure("chaos_codes.png", "Gateway : requêtes par seconde selon le code HTTP",
       [("sum by (code) (rate(http_requests_total{service=\"gateway\"}[30s]))", "{code}", {})], "req/s")
figure("chaos_p95.png", "Latence p95 des appels sortants (service → dépendance)",
       [("histogram_quantile(0.95, sum by (le, service, dependance) (rate(outbound_request_duration_seconds_bucket{dependance=~\"bank|payment|inventory|orders\"}[30s])))",
         "{service}→{dependance}", {})], "secondes", log=True)
figure("chaos_breakers.png", "État des circuit breakers (0 fermé, 1 semi-ouvert, 2 ouvert) et commandes en attente de paiement",
       [("max by (service, dependance) (circuit_breaker_state)", "breaker {service}→{dependance}", {}),
        ("sum(orders_pending_payment) / 10", "commandes en attente ÷ 10", {"color": "#b45309", "ls": ":"})], "état / commandes÷10")
figure("chaos_rejets.png", "Protections déclenchées par seconde : 429 (rate limiting), 503 délestage, bulkhead, circuit ouvert, retries",
       [("sum(rate(rate_limited_total[30s]))", "rate limited (429)", {"color": "#f59e0b"}),
        ("sum(rate(load_shed_total[30s]))", "load shed (503)", {"color": "#dc2626"}),
        ("sum(rate(bulkhead_rejected_total[30s]))", "bulkhead plein", {"color": "#7c3aed"}),
        ("sum(rate(circuit_breaker_rejected_total[30s]))", "circuit ouvert", {"color": "#0f766e"}),
        ("sum(rate(retries_total[30s]))", "retries", {"color": "#2563eb", "ls": "--"})], "événements/s")
