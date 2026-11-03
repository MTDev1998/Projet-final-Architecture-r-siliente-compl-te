"""test_k8s.py -- déploie ShopFlow sur un cluster kind et vérifie le comportement lors des perturbations.
Prérequis : Docker Desktop, kind, kubectl ; images construites (docker compose build).
Usage : python k8s/test_k8s.py            -> k8s/compte_rendu_k8s.txt
Étapes : création du cluster (kind/kind-config.yaml), chargement des images, kubectl apply, boucle de requêtes
dans le cluster (pod « boucle » -> Service gateway), puis : delete d'un pod orders, rolling update du gateway
1.0 -> 2.0, drain d'un worker (PodDisruptionBudget). Le cluster est supprimé à la fin (--garder pour le conserver).
"""
import os, re, subprocess, sys, threading, time

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
KIND = os.environ.get("KIND", "kind")
CLUSTER = "shopflow-final"
PREFIXE_IMAGE = os.path.basename(RACINE).lower() + "-"
SERVICES = ["bank", "inventory", "payment", "orders", "gateway"]
TRACE, EVENEMENTS = [], []
T0 = time.monotonic()


def log(msg=""):
    ligne = f"[{time.strftime('%H:%M:%S')} +{time.monotonic() - T0:5.1f}s] {msg}" if msg else ""
    TRACE.append(ligne)
    print(ligne, flush=True)


def sh(cmd, affiche=True, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RACINE)
    out = (r.stdout + r.stderr).strip()
    if affiche:
        log(f"$ {cmd}")
        for l in out.splitlines():
            if "Image: " in l and "loading" in l:
                continue
            log("  " + l)
    if check and r.returncode:
        sys.exit(f"échec : {cmd}\n{out}")
    return out


def pods(sel="projet=shopflow"):
    return sh(f'kubectl get pods -l {sel} -o wide --no-headers', affiche=False)


def attendre_prets(sel, n, delai=180):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        lignes = [l for l in pods(sel).splitlines() if l.strip()]
        if len(lignes) == n and all(re.search(r"\s1/1\s+Running", l) for l in lignes):
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------- 1. cluster + images + déploiement
log("=== 1. Cluster kind, images, déploiement ===")
if CLUSTER not in sh(f'"{KIND}" get clusters', affiche=False):
    sh(f'"{KIND}" create cluster --config k8s/kind/kind-config.yaml --wait 120s', check=True)
sh("kubectl get nodes")
for s in SERVICES:
    sh(f"docker tag {PREFIXE_IMAGE}{s}:latest shopflow-{s}:1.0", affiche=False)
    sh(f"docker tag {PREFIXE_IMAGE}{s}:latest shopflow-{s}:2.0", affiche=False)
images = " ".join(f"shopflow-{s}:1.0 shopflow-{s}:2.0" for s in SERVICES)
sh(f'"{KIND}" load docker-image {images} --name {CLUSTER}', check=True)
sh("kubectl apply -f k8s/", check=True)
for s in SERVICES:
    sh(f"kubectl rollout status deployment/{s} --timeout=180s", check=True)
sh("kubectl get pods -o wide")
sh("kubectl get svc,pdb")

# ---------------------------------------------------------------- 2. boucle de requêtes dans le cluster
log("")
log("=== 2. Boucle de requêtes dans le cluster (pod boucle -> Service gateway, 1 requête / 0,2 s) ===")
code = (
    "import json,time,urllib.request,urllib.error,uuid\n"
    "i=0\n"
    "while True:\n"
    "  i+=1;t=time.time()\n"
    "  try:\n"
    "    if i%3:\n"
    "      d=json.dumps({'order_id':str(uuid.uuid4()),'sku':'A12','qty':1,'montant':19.9}).encode()\n"
    "      r=urllib.request.urlopen(urllib.request.Request('http://gateway:8000/checkout',data=d,headers={'X-Client-Id':'b%d'%(i%8),'Content-Type':'application/json'}),timeout=5)\n"
    "    else:\n"
    "      r=urllib.request.urlopen(urllib.request.Request('http://gateway:8000/products',headers={'X-Client-Id':'b%d'%(i%8)}),timeout=5)\n"
    "    r.read();c=r.status\n"
    "  except urllib.error.HTTPError as e: c=e.code\n"
    "  except Exception as e: c=0\n"
    "  print('%.3f %d'%(t,c),flush=True);time.sleep(0.2)\n")
with open(os.path.join(ICI, "_boucle.py"), "w") as f:
    f.write(code)
sh("kubectl delete pod boucle --ignore-not-found --force --grace-period=0", affiche=False)
sh("kubectl delete configmap boucle --ignore-not-found", affiche=False)
sh("kubectl create configmap boucle --from-file=boucle.py=k8s/_boucle.py", affiche=False)
with open(os.path.join(ICI, "_boucle_pod.yaml"), "w") as f:
    f.write("""apiVersion: v1
kind: Pod
metadata: {name: boucle}
spec:
  restartPolicy: Never
  nodeSelector: {node-role.kubernetes.io/control-plane: ""}
  tolerations: [{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}]
  containers:
  - name: boucle
    image: shopflow-gateway:1.0
    imagePullPolicy: IfNotPresent
    command: ["python", "/cfg/boucle.py"]
    volumeMounts: [{name: cfg, mountPath: /cfg}]
  volumes: [{name: cfg, configMap: {name: boucle}}]
""")
sh("kubectl apply -f k8s/_boucle_pod.yaml")
sh("kubectl wait --for=condition=Ready pod/boucle --timeout=60s")
time.sleep(8)

# ---------------------------------------------------------------- 3. delete d'un pod orders
log("")
log("=== 3. kubectl delete pod (orders) : recréation automatique, trafic maintenu par les 2 autres réplicas ===")
cible = pods("app=orders").split()[0]
t1 = time.time()
sh(f"kubectl delete pod {cible} --wait=false")
time.sleep(4)
sh("kubectl get pods -l app=orders -o wide --no-headers")
ok = attendre_prets("app=orders", 3)
t1f = time.time()
sh("kubectl get pods -l app=orders -o wide --no-headers")
log(f"-> 3 pods orders Ready à nouveau {t1f - t1:.1f} s après la suppression ({'ok' if ok else 'TIMEOUT'})")
EVENEMENTS.append(("delete pod orders", t1, t1f))
time.sleep(5)

# ---------------------------------------------------------------- 4. rolling update du gateway
log("")
log("=== 4. Rolling update gateway 1.0 -> 2.0 (maxUnavailable 0, maxSurge 1, drain 5 s sur SIGTERM) ===")
t2 = time.time()
sh("kubectl set image deployment/gateway gateway=shopflow-gateway:2.0")
sh("kubectl rollout status deployment/gateway --timeout=180s")
t2f = time.time()
sh("kubectl get pods -l app=gateway -o wide --no-headers")
log(f"-> rolling update terminé en {t2f - t2:.1f} s")
EVENEMENTS.append(("rolling update gateway", t2, t2f))
time.sleep(5)

# ---------------------------------------------------------------- 5. drain d'un worker
log("")
log("=== 5. kubectl drain d'un worker : les PDB (minAvailable 2 sur gateway et orders) limitent les évictions ===")
repartition = {}
for l in pods("projet=shopflow").splitlines():
    if "Running" in l:
        n = l.split()[6]
        repartition[n] = repartition.get(n, 0) + 1
noeud = max((n for n in repartition if "worker" in n), key=repartition.get)
log(f"Répartition des pods par nœud : {repartition} -> drain de {noeud}")
t3 = time.time()
sh(f"kubectl drain {noeud} --ignore-daemonsets --delete-emptydir-data --timeout=180s")
t3f = time.time()
sh("kubectl get pods -l projet=shopflow -o wide --no-headers")
sh("kubectl get pdb")
log(f"-> drain terminé en {t3f - t3:.1f} s")
EVENEMENTS.append(("drain + PDB", t3, t3f))
sh(f"kubectl uncordon {noeud}")
time.sleep(5)

# ---------------------------------------------------------------- 6. bilan
log("")
log("=== 6. Bilan de la boucle de requêtes (journal du pod boucle) ===")
journal = sh("kubectl logs boucle", affiche=False)
mesures = []
for l in journal.splitlines():
    try:
        t, c = l.split()
        mesures.append((float(t), int(c)))
    except ValueError:
        pass
ko = [m for m in mesures if not 200 <= m[1] < 300]
log(f"Requêtes totales : {len(mesures)}, en échec (hors 2xx) : {len(ko)}")
for nom, d, fn in EVENEMENTS:
    fen = [m for m in mesures if d - 1 <= m[0] <= fn + 1]
    kof = [m for m in fen if not 200 <= m[1] < 300]
    log(f"  pendant « {nom} » ({fn - d:.1f} s) : {len(fen)} requêtes, {len(kof)} échec(s)" + (f" : codes {sorted(set(c for _, c in kof))}" if kof else ""))

sh("kubectl delete pod boucle --wait=false", affiche=False)
sh("kubectl delete configmap boucle", affiche=False)
for f in ("_boucle.py", "_boucle_pod.yaml"):
    try:
        os.remove(os.path.join(ICI, f))
    except OSError:
        pass
if "--garder" not in sys.argv:
    sh(f'"{KIND}" delete cluster --name {CLUSTER}')
with open(os.path.join(ICI, "compte_rendu_k8s.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(TRACE) + "\n")
log("compte rendu écrit dans k8s/compte_rendu_k8s.txt")
