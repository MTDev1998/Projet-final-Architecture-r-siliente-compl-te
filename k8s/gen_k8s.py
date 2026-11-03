"""gen_k8s.py -- génère les manifestes Kubernetes (bonus) : un Deployment + Service par service,
PodDisruptionBudget pour gateway et orders. Usage : python gen_k8s.py  (écrit *.yaml dans ce dossier)
Déploiement : kind create cluster --config k8s/kind/kind-config.yaml ; kind load docker-image <images> ; kubectl apply -f k8s/
"""
import os

ICI = os.path.dirname(os.path.abspath(__file__))
SERVICES = {
    # nom : (port, réplicas, variables d'environnement, pdb)
    "bank":      (8080, 1, {}, False),
    "inventory": (8002, 2, {}, False),
    "payment":   (8003, 2, {"BANK_URL": "http://bank:8080"}, False),
    "orders":    (8001, 3, {"INVENTORY_URL": "http://inventory:8002", "PAYMENT_URL": "http://payment:8003"}, True),
    "gateway":   (8000, 3, {"ORDERS_URL": "http://orders:8001", "INVENTORY_URL": "http://inventory:8002"}, True),
}


def deployment(nom, port, replicas, env, pdb):
    envs = "\n".join(f"            - name: {k}\n              value: \"{v}\"" for k, v in {"PORT": str(port), "SERVICE_NAME": nom, "RESILIENCE": "on", **env}.items())
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {nom}
  labels: {{app: {nom}, projet: shopflow}}
spec:
  replicas: {replicas}
  selector:
    matchLabels: {{app: {nom}}}
  strategy:
    type: RollingUpdate
    rollingUpdate: {{maxUnavailable: 0, maxSurge: 1}}
  template:
    metadata:
      labels: {{app: {nom}, projet: shopflow}}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "{port}"
        prometheus.io/path: "/metrics"
    spec:
      terminationGracePeriodSeconds: 30
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels: {{app: {nom}}}
                topologyKey: kubernetes.io/hostname
      containers:
        - name: {nom}
          image: shopflow-{nom}:1.0
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: {port}
          env:
{envs}
          resources:
            requests: {{cpu: "100m", memory: "96Mi"}}
            limits: {{cpu: "500m", memory: "256Mi"}}
          startupProbe:
            httpGet: {{path: /health/startup, port: {port}}}
            periodSeconds: 2
            failureThreshold: 15
          livenessProbe:
            httpGet: {{path: /health/live, port: {port}}}
            periodSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet: {{path: /health/ready, port: {port}}}
            periodSeconds: 5
            failureThreshold: 2
---
apiVersion: v1
kind: Service
metadata:
  name: {nom}
  labels: {{app: {nom}, projet: shopflow}}
spec:
  selector: {{app: {nom}}}
  ports:
    - port: {port}
      targetPort: {port}
  type: {"NodePort" if nom == "gateway" else "ClusterIP"}
""" + (f"""---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {nom}-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels: {{app: {nom}}}
""" if pdb else "")


for nom, (port, rep, env, pdb) in SERVICES.items():
    with open(os.path.join(ICI, f"{nom}.yaml"), "w", encoding="utf-8") as f:
        f.write(deployment(nom, port, rep, env, pdb))
    print("écrit", f"{nom}.yaml")
os.makedirs(os.path.join(ICI, "kind"), exist_ok=True)
with open(os.path.join(ICI, "kind", "kind-config.yaml"), "w", encoding="utf-8") as f:
    f.write("kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nname: shopflow-final\nnodes:\n  - role: control-plane\n  - role: worker\n  - role: worker\n")
print("écrit kind/kind-config.yaml")
