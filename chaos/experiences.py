"""experiences.py -- campagne de chaos engineering automatisée sur la stack Docker Compose.

Usage : python experiences.py [--mode on|off|both] [--exp a,b,c,...]
  - redémarre la stack dans le mode demandé (RESILIENCE=on / off), attend qu'elle soit saine ;
  - pour chaque expérience : mesure de référence, injection, mesure pendant la panne (avec critère
    d'arrêt automatique), restauration, mesure de récupération ;
  - écrit resultats/resultats_<mode>.json et, en mode both, resultats/comparaison.md.

SLI : part des requêtes du gateway servies (2xx, réponse nominale ou dégradée) en moins de 1 s.
Critère d'arrêt : SLI < 50 % sur les 5 dernières secondes -> la panne est annulée immédiatement.
"""
import argparse, json, os, random, statistics, subprocess, sys, threading, time, urllib.error, urllib.request, uuid

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
GATEWAY = os.environ.get("GATEWAY", "http://127.0.0.1:8000")
BANK = os.environ.get("BANK", "http://127.0.0.1:8080")
DUREE_REF, DUREE_PANNE, DUREE_RECUP = 10, 20, 15
NB_CLIENTS, PAUSE, LIMITE_LAT = 6, 0.12, 1.0
SEUIL_ARRET, FENETRE_ARRET, SEUIL_HYP = 0.5, 5.0, 0.95


# ---------------------------------------------------------------- utilitaires
def http(methode, url, corps=None, entetes=None, timeout=5.0):
    data = json.dumps(corps).encode() if corps is not None else None
    req = urllib.request.Request(url, data=data, method=methode, headers={"Content-Type": "application/json", **(entetes or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            brut = r.read()
            return r.status, (json.loads(brut) if brut else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        brut = e.read()
        try:
            return e.code, (json.loads(brut) if brut else None), dict(e.headers)
        except ValueError:
            return e.code, None, dict(e.headers)


def compose(*args, **kw):
    env = dict(os.environ, **kw.pop("env", {}))
    return subprocess.run(["docker", "compose", *args], cwd=RACINE, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def admin(**kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    code, corps, _ = http("GET", f"{BANK}/admin?{q}", timeout=3)
    return corps


def admin_reset():
    admin(fail_rate=0, fail_after=0, down=0, latency=0.05)


def attendre_gateway(delai=120):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            if http("GET", f"{GATEWAY}/health/ready", timeout=2)[0] == 200 and http("GET", f"{BANK}/health", timeout=2)[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def demarrer_stack(mode):
    print(f"\n### Démarrage de la stack en mode RESILIENCE={mode}", flush=True)
    r = compose("up", "-d", "--remove-orphans", env={"RESILIENCE": mode})
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    if not attendre_gateway():
        sys.exit("le gateway ne devient pas prêt")
    time.sleep(3)
    admin_reset()


def conteneurs(service):
    r = compose("ps", "--format", "{{.Name}}", service)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


# ---------------------------------------------------------------- générateur de charge
class Charge:
    """NB_CLIENTS clients indépendants : 70 % de POST /checkout, 30 % de GET /products."""

    def __init__(self):
        self.actif = threading.Event()
        self.ech = []
        self.lock = threading.Lock()
        self.threads = []

    def _client(self, i):
        cid = f"client-{i}"
        while self.actif.is_set():
            t0 = time.monotonic()
            if random.random() < 0.7:
                corps = {"order_id": str(uuid.uuid4()), "sku": random.choice(["A12", "B07", "C33", "D01"]), "qty": 1, "montant": 19.9}
                code, rep, ent = self._appel("POST", "/checkout", corps, cid)
                kind = "checkout"
            else:
                code, rep, ent = self._appel("GET", "/products", None, cid)
                kind = "products"
            lat = time.monotonic() - t0
            degrade = bool(ent.get("X-Degraded")) or code == 202
            with self.lock:
                self.ech.append({"t": time.time(), "kind": kind, "code": code, "lat": lat, "degrade": degrade})
            time.sleep(PAUSE)

    def _appel(self, methode, chemin, corps, cid):
        try:
            return http(methode, GATEWAY + chemin, corps, {"X-Client-Id": cid}, timeout=5)
        except Exception as e:
            return 0, None, {}

    def demarrer(self):
        self.actif.set()
        self.threads = [threading.Thread(target=self._client, args=(i,), daemon=True) for i in range(NB_CLIENTS)]
        for t in self.threads:
            t.start()

    def arreter(self):
        self.actif.clear()
        for t in self.threads:
            t.join(timeout=6)

    def fenetre(self, debut, fin):
        with self.lock:
            return [e for e in self.ech if debut <= e["t"] < fin]


def servi(e):
    return 200 <= e["code"] < 300 and e["lat"] < LIMITE_LAT


def sli(ech):
    return sum(1 for e in ech if servi(e)) / len(ech) if ech else 0.0


def resume(ech):
    lat = sorted(e["lat"] for e in ech)
    co = [e for e in ech if e["kind"] == "checkout"]
    return {
        "n": len(ech), "sli": sli(ech),
        "nominal": sum(1 for e in ech if servi(e) and not e["degrade"]) / len(ech) if ech else 0.0,
        "degrade": sum(1 for e in ech if servi(e) and e["degrade"]) / len(ech) if ech else 0.0,
        "erreurs_5xx": sum(1 for e in ech if e["code"] >= 500 or e["code"] == 0),
        "r429": sum(1 for e in ech if e["code"] == 429),
        "p95_ms": lat[min(int(len(lat) * 0.95), len(lat) - 1)] * 1000 if lat else 0.0,
        "sli_checkout": sli(co),
    }


# ---------------------------------------------------------------- expériences
def tuer(service, nb=1):
    noms = conteneurs(service)[:nb]
    for n in noms:
        subprocess.run(["docker", "kill", n], capture_output=True)
    return noms


def relancer(service):
    compose("up", "-d", "--no-deps", service, env={"RESILIENCE": MODE_COURANT})


MODE_COURANT = "on"
ABUS = {"actif": threading.Event(), "codes": []}


def client_abusif():
    while ABUS["actif"].is_set():
        try:
            code = http("GET", f"{GATEWAY}/products", None, {"X-Client-Id": "abusif"}, timeout=5)[0]
        except Exception:
            code = 0
        ABUS["codes"].append(code)
        time.sleep(0.01)


EXPERIENCES = {
    "a": dict(titre="Banque : 30 % d'erreurs transitoires (503)",
              hypothese="le retry (3 tentatives, backoff + jitter) absorbe les erreurs : SLI >= 95 %, aucune commande perdue",
              panne="flaky bank : fail_rate=0.3 pendant 20 s", rayon="payment -> bank ; 100 % des paiements",
              injecter=lambda: admin(fail_rate=0.3), restaurer=lambda: admin(fail_rate=0)),
    "b": dict(titre="Banque totalement indisponible 20 s",
              hypothese="circuit breaker + fallback « paiement différé » : les commandes sont acceptées (202), SLI >= 95 %, puis rejouées",
              panne="flaky bank : down=1 pendant 20 s", rayon="payment -> bank ; 100 % des paiements",
              injecter=lambda: admin(down=1), restaurer=lambda: admin(down=0)),
    "c": dict(titre="Banque lente : latence de 3 s",
              hypothese="timeout 1 s + breaker : pas de cascade, p95 du gateway < 1 s après ouverture du circuit, SLI >= 95 %",
              panne="flaky bank : latency=3 pendant 20 s", rayon="payment -> bank ; menace les pools de payment et orders",
              injecter=lambda: admin(latency=3), restaurer=lambda: admin(latency=0.05)),
    "d": dict(titre="Perte d'une instance d'inventory (1 sur 2)",
              hypothese="la redondance + retry masquent la perte : SLI >= 95 %, aucune erreur visible",
              panne="docker kill d'un conteneur inventory ; relance après 20 s", rayon="orders -> inventory (2 réplicas)",
              injecter=lambda: tuer("inventory", 1), restaurer=lambda: relancer("inventory")),
    "e": dict(titre="Crash du service orders (instance unique, SPOF)",
              hypothese="le gateway échoue vite (timeout + breaker) sans se bloquer ; /products reste servi ; récupération < 10 s après relance",
              panne="docker kill orders ; relance après 20 s", rayon="gateway -> orders ; 100 % des commandes",
              injecter=lambda: tuer("orders", 1), restaurer=lambda: relancer("orders")),
    "f": dict(titre="Banque : 30 % de réponses perdues après débit",
              hypothese="la clé d'idempotence évite tout double débit : nombre de débits banque = nombre de commandes payées",
              panne="flaky bank : fail_after=0.3 pendant 20 s", rayon="payment -> bank ; cohérence financière",
              injecter=lambda: admin(fail_after=0.3), restaurer=lambda: admin(fail_after=0)),
    "g": dict(titre="Client abusif : 100 req/s avec un seul X-Client-Id",
              hypothese="le rate limiting isole l'abuseur (429) : SLI des autres clients >= 95 %",
              panne="thread envoyant 100 req/s sur /products pendant 20 s", rayon="gateway ; tous les clients",
              injecter=lambda: (ABUS["actif"].set(), threading.Thread(target=client_abusif, daemon=True).start()),
              restaurer=lambda: ABUS["actif"].clear()),
}


def jouer(num, exp, charge):
    print(f"\n=== Expérience {num} — {exp['titre']} [mode {MODE_COURANT}]", flush=True)
    admin_reset()
    ABUS["codes"].clear()
    time.sleep(2)
    etat_bank_avant = admin() or {}
    stats_avant = http("GET", f"{GATEWAY}/orders/stats", None, {"X-Client-Id": "chaos"})[1] or {}

    t_ref = time.time()
    time.sleep(DUREE_REF)
    t_inj = time.time()
    exp["injecter"]()
    arret = None
    while time.time() - t_inj < DUREE_PANNE:
        time.sleep(0.5)
        if time.time() - t_inj >= FENETRE_ARRET:
            recents = charge.fenetre(time.time() - FENETRE_ARRET, time.time())
            if recents and sli(recents) < SEUIL_ARRET:
                arret = time.time() - t_inj
                print(f"   !! critère d'arrêt : SLI < {SEUIL_ARRET:.0%} sur {FENETRE_ARRET:.0f} s -> panne annulée à t+{arret:.1f} s", flush=True)
                break
    t_res = time.time()
    exp["restaurer"]()
    time.sleep(DUREE_RECUP)
    t_fin = time.time()

    ref, pan, rec = charge.fenetre(t_ref, t_inj), charge.fenetre(t_inj, t_res), charge.fenetre(t_res, t_fin)
    detect = next((e["t"] - t_inj for e in pan if not (servi(e) and not e["degrade"])), None)
    recup = None
    for e in rec:                       # premier instant suivi de 3 s sans réponse non nominale
        if servi(e) and not e["degrade"]:
            suivants = [x for x in rec if e["t"] <= x["t"] < e["t"] + 3]
            if all(servi(x) and not x["degrade"] for x in suivants):
                recup = e["t"] - t_res
                break
    etat_bank_apres = admin() or {}
    stats_apres = http("GET", f"{GATEWAY}/orders/stats", None, {"X-Client-Id": "chaos"})[1] or {}
    r = {"num": num, "mode": MODE_COURANT, "titre": exp["titre"], "hypothese": exp["hypothese"], "panne": exp["panne"],
         "rayon": exp["rayon"], "ref": resume(ref), "panne_mesure": resume(pan), "recup": resume(rec),
         "detection_s": detect, "recuperation_s": recup, "arret_s": arret,
         "debits_banque": (etat_bank_apres.get("charges", 0) - etat_bank_avant.get("charges", 0)),
         "commandes": {k: stats_apres.get("par_statut", {}).get(k, 0) - stats_avant.get("par_statut", {}).get(k, 0)
                       for k in set(stats_apres.get("par_statut", {})) | set(stats_avant.get("par_statut", {}))},
         "abus_429": ABUS["codes"].count(429), "abus_total": len(ABUS["codes"]),
         "t_inj": t_inj, "t_res": t_res, "t_fin": t_fin}
    r["validee"] = r["panne_mesure"]["sli"] >= SEUIL_HYP and arret is None
    if num == "f":
        payes = r["commandes"].get("paid", 0) + r["commandes"].get("paid_late", 0)
        r["validee"] = r["validee"] and r["debits_banque"] <= payes + r["commandes"].get("pending_payment", 0)
    pm = r["panne_mesure"]
    print(f"   référence SLI {r['ref']['sli']:.1%} ({r['ref']['n']} req) | panne SLI {pm['sli']:.1%} "
          f"(nominal {pm['nominal']:.1%}, dégradé {pm['degrade']:.1%}, 5xx {pm['erreurs_5xx']}, p95 {pm['p95_ms']:.0f} ms) "
          f"| récup SLI {r['recup']['sli']:.1%} | détection {detect if detect is None else round(detect, 1)} s "
          f"| récupération {recup if recup is None else round(recup, 1)} s | hypothèse {'VALIDÉE' if r['validee'] else 'INVALIDÉE'}", flush=True)
    if num == "f":
        print(f"   débits banque pendant l'expérience : {r['debits_banque']} ; commandes : {r['commandes']}", flush=True)
    if num == "g":
        print(f"   client abusif : {r['abus_total']} requêtes, {r['abus_429']} x 429", flush=True)
    return r


def campagne(mode, exps):
    global MODE_COURANT
    MODE_COURANT = mode
    demarrer_stack(mode)
    charge = Charge()
    charge.demarrer()
    time.sleep(3)
    resultats = []
    try:
        for num in exps:
            resultats.append(jouer(num, EXPERIENCES[num], charge))
    finally:
        charge.arreter()
        ABUS["actif"].clear()
        admin_reset()
    os.makedirs(os.path.join(ICI, "resultats"), exist_ok=True)
    with open(os.path.join(ICI, "resultats", f"resultats_{mode}.json"), "w", encoding="utf-8") as f:
        json.dump(resultats, f, indent=1, ensure_ascii=False)
    return resultats


def comparaison(off, on):
    lignes = ["# Campagne de chaos — avant (RESILIENCE=off) / après (RESILIENCE=on)", "",
              f"SLI = part des requêtes du gateway servies (2xx) en moins de {LIMITE_LAT:.0f} s ; critère d'arrêt : SLI < {SEUIL_ARRET:.0%} sur {FENETRE_ARRET:.0f} s ; hypothèse validée si SLI pendant la panne >= {SEUIL_HYP:.0%} sans arrêt.", "",
              "| Exp | Expérience | SLI panne AVANT | SLI panne APRÈS | p95 AVANT | p95 APRÈS | 5xx AVANT | 5xx APRÈS | Arrêt auto AVANT | Détection / récup. APRÈS | Hypothèse (après) |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a, b in zip(off, on):
        pa, pb = a["panne_mesure"], b["panne_mesure"]
        f = lambda x: "-" if x is None else f"{x:.1f} s"
        lignes.append(f"| {a['num']} | {a['titre']} | {pa['sli']:.1%} | **{pb['sli']:.1%}** | {pa['p95_ms']:.0f} ms | {pb['p95_ms']:.0f} ms | {pa['erreurs_5xx']} | {pb['erreurs_5xx']} | "
                      f"{'oui (t+' + str(round(a['arret_s'], 1)) + ' s)' if a['arret_s'] else 'non'} | {f(b['detection_s'])} / {f(b['recuperation_s'])} | {'validée' if b['validee'] else 'invalidée'} |")
    lignes += ["", "## Fiches d'expérience (mode après)", ""]
    for a, b in zip(off, on):
        pb = b["panne_mesure"]
        lignes += [f"### Expérience {b['num']} — {b['titre']}", "",
                   f"- **État stable (SLI mesuré)** : {b['ref']['sli']:.1%} sur {b['ref']['n']} requêtes (avant : {a['ref']['sli']:.1%})",
                   f"- **Hypothèse** : {b['hypothese']}",
                   f"- **Panne injectée** : {b['panne']}",
                   f"- **Rayon d'impact** : {b['rayon']}",
                   f"- **Critère d'arrêt** : SLI < {SEUIL_ARRET:.0%} sur {FENETRE_ARRET:.0f} s -> après : {'DÉCLENCHÉ à t+%.1f s' % b['arret_s'] if b['arret_s'] else 'non déclenché'} ; avant : {'déclenché à t+%.1f s' % a['arret_s'] if a['arret_s'] else 'non déclenché'}",
                   f"- **Résultat mesuré (après)** : SLI {pb['sli']:.1%} (nominal {pb['nominal']:.1%}, dégradé {pb['degrade']:.1%}), {pb['erreurs_5xx']} erreurs 5xx, p95 {pb['p95_ms']:.0f} ms ; récupération SLI {b['recup']['sli']:.1%}",
                   f"- **Résultat mesuré (avant)** : SLI {a['panne_mesure']['sli']:.1%}, {a['panne_mesure']['erreurs_5xx']} erreurs 5xx, p95 {a['panne_mesure']['p95_ms']:.0f} ms",
                   f"- **Temps de détection / récupération (après)** : {f(b['detection_s'])} / {f(b['recuperation_s'])}",
                   f"- **Hypothèse validée ?** : {'Oui' if b['validee'] else 'Non'}"]
        if b["num"] == "f":
            lignes.append(f"- **Idempotence** : débits banque après = {b['debits_banque']} pour commandes {b['commandes']} ; avant = {a['debits_banque']} pour {a['commandes']}")
        if b["num"] == "g":
            lignes.append(f"- **Client abusif** : après {b['abus_429']} x 429 sur {b['abus_total']} ; avant {a['abus_429']} x 429 sur {a['abus_total']}")
        lignes.append("")
    return "\n".join(lignes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both", choices=["on", "off", "both"])
    ap.add_argument("--exp", default=",".join(EXPERIENCES))
    args = ap.parse_args()
    exps = [e.strip() for e in args.exp.split(",") if e.strip()]
    debut = time.time()
    if args.mode == "both":
        off = campagne("off", exps)
        on = campagne("on", exps)
        md = comparaison(off, on)
        with open(os.path.join(ICI, "resultats", "comparaison.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(ICI, "resultats", "fenetre_campagne.json"), "w", encoding="utf-8") as f:
            json.dump({"debut": debut, "fin": time.time()}, f)
        print("\n" + md)
    else:
        campagne(args.mode, exps)
    print(f"\nCampagne terminée en {(time.time() - debut) / 60:.1f} min ; résultats dans chaos/resultats/")
