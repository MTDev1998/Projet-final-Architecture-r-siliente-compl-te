# ShopFlow résilient — Projet final « Architecture résiliente complète »

M2 LDF · Patterns de résilience · **MOUSSAOUI Tarek**

Application e-commerce de démonstration composée de 5 services HTTP (Python 3.12, bibliothèque standard
uniquement), instrumentée pour Prometheus et Grafana, livrée avec une campagne de chaos engineering
« avant / après patterns » et des manifestes Kubernetes.

```
clients -> gateway -> orders -> inventory (x2)
                             -> payment (x2) -> banque externe instable
```

## Lancer tout en une commande

```bash
docker compose up -d --build
```

| Point d'accès | URL |
|---|---|
| API (gateway) | http://localhost:8000 — `GET /products`, `POST /checkout`, `GET /orders/<id>`, `GET /health/ready`, `GET /metrics` |
| Banque simulée (injection de pannes) | http://localhost:8080/admin?fail_rate=0.3&latency=2&down=0&fail_after=0 |
| Prometheus (règles SLO + alertes) | http://localhost:9090/alerts |
| Grafana (tableau de bord provisionné) | http://localhost:3000 (admin / admin, lecture anonyme autorisée) |

Exemple :

```bash
curl -s -H "X-Client-Id: demo" http://localhost:8000/products
curl -s -X POST -H "X-Client-Id: demo" -H "Content-Type: application/json" \
     -d '{"order_id":"demo-1","sku":"A12","qty":1,"montant":19.9}' http://localhost:8000/checkout
```

Arrêt : `docker compose down`. Mode « avant » (tous les patterns désactivés) : `RESILIENCE=off docker compose up -d`.

## Campagne de chaos (7 expériences, avant / après)

```bash
python chaos/experiences.py            # ~15 min : redémarre la stack en off puis en on, joue a..g, écrit chaos/resultats/
python chaos/graphes.py                # courbes Prometheus de la campagne -> docs/
```

Expériences : (a) banque 30 % d'erreurs, (b) banque indisponible, (c) banque lente 3 s, (d) perte d'une instance
inventory, (e) crash d'orders, (f) réponses perdues après débit (idempotence), (g) client abusif.

<!-- resultats:debut -->
## Résultats de la dernière campagne (avant / après patterns)

| Exp | Expérience | SLI panne AVANT | SLI panne APRÈS | p95 AVANT | p95 APRÈS | 5xx AVANT | 5xx APRÈS | Arrêt auto AVANT | Détection / récup. APRÈS | Hypothèse (après) |
|---|---|---|---|---|---|---|---|---|---|---|
| a | Banque : 30 % d'erreurs transitoires (503) | 77.7% | **100.0%** | 125 ms | 234 ms | 137 | 0 | non | 0.1 s / 1.3 s | validée |
| b | Banque totalement indisponible 20 s | 33.2% | **99.5%** | 63 ms | 47 ms | 127 | 0 | oui (t+5.0 s) | 0.7 s / 1.6 s | validée |
| c | Banque lente : latence de 3 s | 41.7% | **98.2%** | 3250 ms | 47 ms | 0 | 0 | oui (t+5.0 s) | 1.2 s / 4.9 s | validée |
| d | Perte d'une instance d'inventory (1 sur 2) | 99.8% | **100.0%** | 125 ms | 110 ms | 1 | 0 | non | - / 0.0 s | validée |
| e | Crash du service orders (instance unique, SPOF) | 48.6% | **29.9%** | 3969 ms | 31 ms | 18 | 178 | oui (t+5.4 s) | 0.3 s / 9.4 s | invalidée |
| f | Banque : 30 % de réponses perdues après débit | 81.3% | **100.0%** | 125 ms | 219 ms | 116 | 0 | non | - / 0.0 s | validée |
| g | Client abusif : 100 req/s avec un seul X-Client-Id | 100.0% | **100.0%** | 125 ms | 125 ms | 0 | 0 | non | - / 0.0 s | validée |

Détail des fiches : `chaos/resultats/comparaison.md` ; figures : `docs/chaos_*.png` ; analyse complète : `docs/Dossier_architecture_MOUSSAOUI_Tarek.docx`.
<!-- resultats:fin -->

## Contenu du dépôt

| Dossier | Contenu |
|---|---|
| `services/common/` | socle commun : `metrics.py` (format Prometheus), `resilience.py` (timeout, retry, circuit breaker, bulkhead, rate limiting, load shedding, cache stale-if-error), `server.py` (routage, sondes, arrêt propre) |
| `services/<nom>/app.py` | gateway, orders, inventory, payment, bank |
| `services/Dockerfile` | image commune (slim, non root, HEALTHCHECK, CMD exec) |
| `docker-compose.yml` | 5 services (inventory et payment ×2), healthchecks, restart, Prometheus, Grafana |
| `observability/` | `prometheus.yml` (découverte DNS), `alerts.yml` (SLO 99,5 %, burn rate, latence, circuits), dashboard Grafana (`gen_dashboard.py`) |
| `chaos/` | `experiences.py` (campagne automatisée), `graphes.py`, `resultats/` (JSON, `comparaison.md`) |
| `analyse/` | `archi.py` (disponibilité composite, SPOF), `graphe.py` (graphe de dépendances) |
| `k8s/` | Deployments (3 réplicas gateway/orders), Services, PodDisruptionBudgets, `gen_k8s.py`, `test_k8s.py`, `kind/kind-config.yaml` |
| `docs/` | **Dossier d'architecture** (`Dossier_architecture_MOUSSAOUI_Tarek.docx`), figures |

## Patterns mis en œuvre (chacun relié à un risque de l'AMDEC, voir le dossier)

| Pattern | Où | Paramètres |
|---|---|---|
| Timeout | tous les appels sortants | gateway→orders 4 s, orders→inventory 0,5 s, orders→payment 2 s, payment→banque 1 s |
| Retry + backoff + jitter, Retry-After | payment→banque, orders→inventory | 3 / 2 tentatives, base 0,1 s, plafond 0,5–2 s |
| Circuit breaker | payment→banque, orders→payment/inventory, gateway→orders | 5 / 3 / 5 / 10 échecs, réouverture 10 / 10 / 5 / 5 s |
| Bulkhead | orders | 16 places inventory, 8 places payment |
| Fallback / dégradation gracieuse | orders (paiement différé 202 + rejeu asynchrone), gateway (catalogue périmé `X-Degraded: stale`) | rejeu toutes les 3 s |
| Rate limiting | gateway | token bucket 20 jetons, 10/s par `X-Client-Id`, 429 + Retry-After |
| Load shedding | gateway | 32 requêtes simultanées, 25 % réservées à `/checkout`, 503 + Retry-After |
| Health checks | tous | `/health/live`, `/ready`, `/startup`, `/deps` ; drain 5 s sur SIGTERM |
| Cache résilient | gateway | TTL 5 s, stale-if-error 300 s |
| Idempotence | payment→banque, inventory, orders | `Idempotency-Key` = `order_id` |

## Kubernetes (bonus, vérifié sur kind)

```bash
python k8s/gen_k8s.py          # régénère les manifestes (3 réplicas gateway/orders, 2 inventory/payment, sondes, PDB, anti-affinité)
python k8s/test_k8s.py         # crée le cluster kind, charge les images, déploie, teste delete pod / rolling update / drain, écrit k8s/compte_rendu_k8s.txt
```

Déploiement manuel : `kind create cluster --config k8s/kind/kind-config.yaml`, tag des images en `shopflow-<service>:1.0`,
`kind load docker-image ... --name shopflow-final`, `kubectl apply -f k8s/`. Résultats mesurés dans `k8s/compte_rendu_k8s.txt`
et dans le dossier d'architecture (chapitre 7.2).
