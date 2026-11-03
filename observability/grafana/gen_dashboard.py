"""gen_dashboard.py -- génère dashboards/shopflow.json (tableau de bord Grafana provisionné).
Usage : python gen_dashboard.py
"""
import json, os

DS = {"type": "prometheus", "uid": "prometheus"}
panels, y = [], 0
_id = [0]


def panel(titre, exprs, kind="timeseries", w=12, h=7, unit=None, x=0, extra=None, legend=None):
    _id[0] += 1
    p = {
        "id": _id[0], "type": kind, "title": titre, "datasource": DS,
        "gridPos": {"x": x, "y": panel.y, "w": w, "h": h},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": (legend[i] if legend else "{{service}} {{dependance}} {{code}} {{status}} {{resultat}} {{type}}"), "datasource": DS}
                    for i, e in enumerate(exprs)],
        "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    }
    if extra:
        p.update(extra)
    panels.append(p)
    return p


panel.y = 0
# Ligne 1 : SLO
panel("SLI disponibilité gateway (5 min) — SLO 99,5 %", ["slo:gateway_availability:ratio_rate5m"], kind="stat", w=6, h=5,
      unit="percentunit", legend=["disponibilité"],
      extra={"fieldConfig": {"defaults": {"unit": "percentunit", "decimals": 3, "min": 0.9, "max": 1,
                                          "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 0.995}, {"color": "green", "value": 0.999}]}}, "overrides": []},
             "options": {"colorMode": "background", "graphMode": "area", "reduceOptions": {"calcs": ["lastNotNull"]}}})
panel("Budget d'erreur consommé (fenêtre 5 min, budget 0,5 %)", ["(1 - slo:gateway_availability:ratio_rate5m) / 0.005"], kind="gauge", w=6, h=5, x=6,
      unit="percentunit", legend=["part du budget"],
      extra={"fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 2, "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 0.5}, {"color": "red", "value": 1}]}}, "overrides": []}})
panel("Commandes en attente de paiement", ["sum(orders_pending_payment)"], kind="stat", w=6, h=5, x=12, legend=["en attente"],
      extra={"options": {"colorMode": "value", "graphMode": "area", "reduceOptions": {"calcs": ["lastNotNull"]}},
             "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 5}, {"color": "red", "value": 20}]}}, "overrides": []}})
panel("Alertes actives", ["ALERTS{alertstate=\"firing\"}"], kind="stat", w=6, h=5, x=18, legend=["{{alertname}}"],
      extra={"options": {"colorMode": "background", "textMode": "name", "reduceOptions": {"calcs": ["lastNotNull"]}},
             "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}]}, "noValue": "aucune"}, "overrides": []}})
panel.y = 5
# Ligne 2 : trafic et latence
panel("Gateway — requêtes/s par code HTTP", ["sum by (code) (rate(http_requests_total{service=\"gateway\"}[1m]))"], unit="reqps", legend=["{{code}}"],
      extra={"fieldConfig": {"defaults": {"unit": "reqps", "custom": {"stacking": {"mode": "normal"}, "fillOpacity": 30}}, "overrides": [
          {"matcher": {"id": "byRegexp", "options": "2.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
          {"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
          {"matcher": {"id": "byRegexp", "options": "429"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}]}})
panel("Latence p95 des requêtes entrantes par service", ["histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket[1m])))"],
      x=12, unit="s", legend=["{{service}}"])
panel.y = 12
# Ligne 3 : dépendances
panel("Latence p95 des appels sortants (service → dépendance)", ["histogram_quantile(0.95, sum by (le, service, dependance) (rate(outbound_request_duration_seconds_bucket[1m])))"],
      unit="s", legend=["{{service}} → {{dependance}}"])
panel("État des circuit breakers (0 fermé, 1 semi-ouvert, 2 ouvert)", ["max by (service, dependance) (circuit_breaker_state)"], x=12, kind="state-timeline",
      legend=["{{service}} → {{dependance}}"],
      extra={"fieldConfig": {"defaults": {"custom": {"fillOpacity": 70}, "mappings": [{"type": "value", "options": {"0": {"text": "fermé", "color": "green"}, "1": {"text": "semi-ouvert", "color": "orange"}, "2": {"text": "ouvert", "color": "red"}}}]}, "overrides": []},
             "options": {"showValue": "never", "legend": {"displayMode": "list", "placement": "bottom"}}})
panel.y = 19
# Ligne 4 : patterns de contention
panel("Timeouts et retries par seconde", ["sum by (service, dependance) (rate(timeouts_total[1m]))", "sum by (service, dependance) (rate(retries_total[1m]))"],
      legend=["timeout {{service}}→{{dependance}}", "retry {{service}}→{{dependance}}"], unit="ops")
panel("Rejets : rate limiting (429), load shedding (503), bulkhead, circuit ouvert", [
    "sum(rate(rate_limited_total[1m]))", "sum by (prioritaire) (rate(load_shed_total[1m]))",
    "sum by (service, dependance) (rate(bulkhead_rejected_total[1m]))", "sum by (service, dependance) (rate(circuit_breaker_rejected_total[1m]))"],
    x=12, legend=["rate limited", "shed prioritaire={{prioritaire}}", "bulkhead {{service}}→{{dependance}}", "circuit ouvert {{service}}→{{dependance}}"], unit="ops")
panel.y = 26
# Ligne 5 : dégradation gracieuse
panel("Cache résilient et réponses dégradées", ["sum by (service, resultat) (rate(cache_requests_total[1m]))", "sum by (service, type) (rate(fallback_total[1m]))"],
      legend=["cache {{resultat}}", "fallback {{type}}"], unit="ops")
panel("Commandes par statut (par seconde)", ["sum by (status) (rate(orders_total[1m]))"], x=12, legend=["{{status}}"], unit="ops",
      extra={"fieldConfig": {"defaults": {"unit": "ops", "custom": {"stacking": {"mode": "normal"}, "fillOpacity": 30}}, "overrides": []}})
panel.y = 33
panel("Occupation : requêtes en cours, load shedder, bulkheads", ["sum by (service) (http_requests_in_flight)", "sum(load_shedder_in_flight)", "sum by (service, dependance) (bulkhead_in_flight)"],
      legend=["en cours {{service}}", "shedder", "bulkhead {{service}}→{{dependance}}"], w=24)

dashboard = {
    "uid": "shopflow-resilience", "title": "ShopFlow — résilience", "tags": ["shopflow", "slo"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "editable": True, "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
    "panels": panels,
}
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards", "shopflow.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=1, ensure_ascii=False)
print("écrit", out, f"({len(panels)} panneaux)")
