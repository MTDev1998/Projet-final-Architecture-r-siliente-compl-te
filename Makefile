# Raccourcis (make up / make chaos / make dossier / make down). Sous Windows sans make : copier les commandes.
PY ?= python

up:            ## construit et démarre toute la stack (services, Prometheus, Grafana)
	docker compose up -d --build

down:          ## arrête et supprime les conteneurs
	docker compose down

avant:         ## démarre la stack sans aucun pattern (état « avant »)
	RESILIENCE=off docker compose up -d

chaos:         ## campagne complète avant / après puis figures et README
	$(PY) chaos/experiences.py --mode both
	$(PY) chaos/graphes.py
	$(PY) chaos/maj_readme.py

analyse:       ## disponibilité composite, SPOF, graphe de dépendances
	$(PY) analyse/archi.py
	$(PY) analyse/graphe.py

dossier:       ## régénère le dossier d'architecture Word
	$(PY) docs/gen_dossier.py

k8s:           ## régénère les manifestes Kubernetes
	$(PY) k8s/gen_k8s.py

dashboard:     ## régénère le tableau de bord Grafana
	$(PY) observability/grafana/gen_dashboard.py

.PHONY: up down avant chaos analyse dossier k8s dashboard
