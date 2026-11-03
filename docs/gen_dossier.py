# -*- coding: utf-8 -*-
"""gen_dossier.py -- génère le dossier d'architecture (Word) à partir des résultats réels du dépôt.
Usage : python docs/gen_dossier.py   (après analyse/archi.py, chaos/experiences.py et chaos/graphes.py)
"""
import json, os, re
from datetime import date
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
OUT = os.path.join(ICI, "Dossier_architecture_MOUSSAOUI_Tarek.docx")
AUTEUR = "MOUSSAOUI Tarek"


def lire(*p):
    with open(os.path.join(RACINE, *p), encoding="utf-8") as f:
        return f.read()


def charger_json(*p):
    with open(os.path.join(RACINE, *p), encoding="utf-8") as f:
        return json.load(f)


RES = {m: charger_json("chaos", "resultats", f"resultats_{m}.json") for m in ("off", "on")}
DISPO = lire("analyse", "resultats_dispo.txt")

doc = Document()
for s in doc.sections:
    s.page_height, s.page_width = Cm(29.7), Cm(21.0)
    s.left_margin = s.right_margin = Cm(2.2)
    s.top_margin = s.bottom_margin = Cm(2.0)
st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
for niveau, taille in ((1, 16), (2, 13), (3, 11.5)):
    h = doc.styles[f"Heading {niveau}"]
    h.font.name, h.font.size, h.font.color.rgb = "Calibri", Pt(taille), RGBColor(0x1F, 0x3A, 0x5F)
    h.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


# ----------------------------------------------------------------------------- helpers
def para(texte, size=None, bold=False, italic=False, after=6, align=None, style=None):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(after)
    if align:
        p.alignment = align
    for i, part in enumerate(texte.split("**")):
        if part:
            r = p.add_run(part)
            r.bold, r.italic = bold or i % 2 == 1, italic
            if size:
                r.font.size = Pt(size)
    return p


def puces(items):
    for it in items:
        para(it, after=2, style="List Bullet")


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def tableau(lignes, largeurs, size=8.5, entete=True):
    t = doc.add_table(rows=len(lignes), cols=len(lignes[0]))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, ligne in enumerate(lignes):
        for j, val in enumerate(ligne):
            c = t.cell(i, j)
            c.width = Cm(largeurs[j])
            c.paragraphs[0].text = ""
            c.paragraphs[0].paragraph_format.space_after = Pt(1)
            for k, part in enumerate(str(val).split("**")):
                if part:
                    r = c.paragraphs[0].add_run(part)
                    r.font.size = Pt(size)
                    r.bold = (entete and i == 0) or k % 2 == 1
            if entete and i == 0:
                shade(c, "DCE6F1")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def code(texte, size=7.5):
    for ligne in texte.strip("\n").splitlines():
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        pPr = p._p.get_or_add_pPr()
        shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), "F1F3F5")
        pPr.append(shd)
        r = p.add_run(ligne if ligne.strip() else " ")
        r.font.name, r.font.size = "Consolas", Pt(size)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def image(nom, largeur=16.5, legende=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(os.path.join(ICI, nom), width=Cm(largeur))
    if legende:
        para(legende, size=8.5, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=8)


def saut():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def f_s(x):
    return "–" if x is None else f"{x:.1f} s"


def pm(r):
    return r["panne_mesure"]


R_OFF = {r["num"]: r for r in RES["off"]}
R_ON = {r["num"]: r for r in RES["on"]}

# ============================================================================= page de titre
for _ in range(6):
    doc.add_paragraph()
para("Dossier d'architecture", size=28, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
para("ShopFlow résilient — Projet final « Architecture résiliente complète »", size=15, align=WD_ALIGN_PARAGRAPH.CENTER, after=30)
para("Patterns de résilience · M2 LDF · Formatrice : Suzanne KOKOS", size=11, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
para(f"Auteur : **{AUTEUR}**", size=12, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
para(date.today().strftime("%d/%m/%Y"), size=11, align=WD_ALIGN_PARAGRAPH.CENTER, after=40)
para("Dépôt : dossier Projet-final-Architecture-r-siliente-compl-te (README, docker compose up -d --build)", size=9.5, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
saut()

# ============================================================================= sommaire
doc.add_heading("Sommaire", 1)
puces(["1. Contexte, objectifs et SLO", "2. Architecture", "3. Analyse des risques : disponibilité, SPOF, AMDEC",
       "4. Patterns de résilience et paramètres justifiés", "5. Observabilité : métriques, tableau de bord, alertes",
       "6. Campagne de chaos engineering : résultats avant / après", "7. Déploiement : Docker Compose et Kubernetes",
       "8. Limites et perspectives", "Annexes : commandes, structure du dépôt"])

# ============================================================================= 1. contexte
doc.add_heading("1. Contexte, objectifs et SLO", 1)
para("ShopFlow est l'application e-commerce fil rouge du module. Le jour 1 a montré, sur ses logs, comment une "
     "banque lente transforme 25 % d'erreurs de paiement en 60 % d'erreurs pour les clients (défaillance en cascade, "
     "tempête de retries). Le projet final reconstruit ShopFlow de bout en bout pour démontrer, preuves à l'appui, "
     "qu'une application distribuée continue de rendre un service acceptable face à des pannes réalistes et qu'elle "
     "est prête à être exploitée en production.")
para("**Périmètre** : le parcours « passer une commande » (catalogue, réservation de stock, paiement) et son "
     "exploitation (santé, métriques, alertes, déploiement). Cinq services HTTP en Python 3.12 sans dépendance externe, "
     "dont une dépendance instable simulée : l'API bancaire.")
doc.add_heading("Objectifs de niveau de service", 2)
tableau([["Indicateur", "Définition", "Objectif"],
         ["SLI de disponibilité", "part des requêtes du gateway répondues sans erreur serveur (code autre que 5xx) ; les 429 (clients abusifs) sont exclus du dénominateur", "**SLO 99,5 %** sur 5 min glissantes, budget d'erreur 0,5 %"],
         ["SLI de latence (chaos)", "part des requêtes servies (2xx, nominale ou dégradée) en moins de 1 s", "≥ 95 % pendant une panne (hypothèse des expériences)"],
         ["Cohérence financière", "nombre de débits bancaires = nombre de commandes payées", "aucun double débit, quelle que soit la panne"],
         ["Dégradation", "une commande est acceptée (202 « paiement en attente ») plutôt que refusée quand la banque est indisponible", "paiement rejoué automatiquement dès le retour de la banque"]],
        [3.6, 8.6, 4.4])
para("Ces objectifs se traduisent directement en règles Prometheus (chapitre 5) et en hypothèses d'expériences (chapitre 6).")

# ============================================================================= 2. architecture
doc.add_heading("2. Architecture", 1)
image("graphe_dependances.png", 16.5, "Figure 1 — Graphe de dépendances et patterns portés par chaque lien.")
doc.add_heading("Services", 2)
tableau([["Service", "Port", "Rôle", "État", "Réplicas (compose / k8s)"],
         ["gateway", "8000", "point d'entrée public : GET /products, POST /checkout, GET /orders/<id> ; protège le système (rate limiting, load shedding) et dégrade le catalogue (cache)", "cache en mémoire, buckets par client", "1 / 3"],
         ["orders", "8001", "crée la commande : réserve le stock puis déclenche le paiement ; travailleur asynchrone qui rejoue les paiements différés", "commandes en mémoire", "1 / 3"],
         ["inventory", "8002", "catalogue et stock ; réservation idempotente par order_id", "stock en mémoire", "2 / 2"],
         ["payment", "8003", "encaisse auprès de la banque avec clé d'idempotence", "sans état", "2 / 2"],
         ["bank", "8080", "API bancaire externe simulée, instable et pilotable (/admin : erreurs, latence, indisponibilité, réponses perdues)", "débits en mémoire", "1 / 1"],
         ["prometheus", "9090", "collecte /metrics toutes les 5 s, règles SLO et alertes", "séries temporelles", "1"],
         ["grafana", "3000", "tableau de bord « ShopFlow — résilience » provisionné", "–", "1"]],
        [2.2, 1.2, 7.6, 3.2, 2.4])
doc.add_heading("Flux d'une commande", 2)
puces(["Le client appelle **POST /checkout** sur le gateway avec un en-tête X-Client-Id et un order_id unique.",
       "Le gateway applique le rate limiting (token bucket par client) puis le load shedding (place prioritaire réservée à /checkout) et transmet à orders avec un timeout de 4 s.",
       "orders réserve le stock : appel à inventory cloisonné (bulkhead 16), timeout 0,5 s, 2 tentatives, circuit breaker. Sans stock, la commande est refusée (503 + Retry-After) : on ne vend pas sans stock.",
       "orders déclenche le paiement : appel à payment cloisonné (bulkhead 8), timeout 2 s, circuit breaker. payment appelle la banque avec Idempotency-Key = order_id, timeout 1 s, 3 tentatives, circuit breaker.",
       "Si le paiement échoue ou si le circuit est ouvert, orders **accepte quand même la commande** (202, status pending_payment, en-tête X-Degraded) ; un travailleur rejoue les paiements en attente toutes les 3 s. C'est la dégradation gracieuse qui sort la banque du chemin critique d'acceptation.",
       "GET /products passe par un cache résilient : valeur fraîche 5 s, valeur périmée servie jusqu'à 300 s si inventory ne répond pas (X-Degraded: stale)."])
doc.add_heading("Choix techniques", 2)
puces(["**Bibliothèque standard uniquement** (http.server, urllib, threading) : les patterns sont écrits à la main dans services/common/resilience.py, ce qui rend leurs paramètres et leurs métriques explicites.",
       "**Socle commun** (services/common/server.py) : routage, métriques par requête, sondes /health/live, /ready, /startup, /deps, arrêt propre sur SIGTERM (readiness en échec puis drain de 5 s).",
       "**Interrupteur RESILIENCE=off** : désactive tous les patterns (timeouts de 30 s, pas de retry, breakers inactifs, pas de bulkhead, pas de fallback, pas de rate limiting ni de délestage, cache inactif). Il sert uniquement à mesurer l'apport des patterns dans la campagne de chaos (état « avant »).",
       "**Idempotence de bout en bout** : order_id sert de clé d'idempotence pour la commande, la réservation de stock et le débit bancaire, ce qui rend les retries sûrs."])

# ============================================================================= 3. risques
saut()
doc.add_heading("3. Analyse des risques", 1)
doc.add_heading("3.1 Disponibilité théorique et SPOF", 2)
para("Hypothèses : une instance de nos services est disponible à 99,5 % (ordre de grandeur mesuré au jour 2 pour un "
     "processus Python sans redondance), la banque externe à 99,9 %, pannes indépendantes. Série = produit des "
     "disponibilités, parallèle = 1 − produit des indisponibilités (script analyse/archi.py).")
code(DISPO, size=7)
puces(["En Docker Compose, **gateway et orders sont des SPOF** : chacun coûte 43 h d'indisponibilité par an ; la cible à 99,9 % n'est pas atteignable sans les redonder.",
       "La **banque externe** reste un SPOF à 99,9 % tant qu'elle est synchrone dans le chemin critique : même avec tout le reste parfait, le parcours plafonne sous 99,9 %. Le fallback « paiement différé » la sort du chemin d'acceptation : la commande est acceptée, seul le débit est différé.",
       "Les manifestes Kubernetes (3 réplicas pour gateway et orders, PodDisruptionBudget) portent l'acceptation des commandes à 99,995 % théoriques.",
       "Hypothèse d'indépendance discutable : les réplicas partagent la même image, le même hôte Docker et la même banque. Les expériences (d), (e) et (b) testent précisément ces pannes corrélées."])
doc.add_heading("3.2 AMDEC", 2)
para("Gravité G, occurrence O, détectabilité D notées de 1 à 5 (D = 5 : très difficile à détecter) ; criticité C = G × O × D. "
     "Chaque risque est relié aux patterns du chapitre 4 et à une expérience du chapitre 6.")
AMDEC = [
    ("R1", "banque", "latence > 1 s (défaillance temporelle)", "threads de payment puis d'orders bloqués, cascade de 503 sur tout le site (incident du jour 1)", 5, 4, 4, "timeout 1 s, circuit breaker, bulkhead payment, fallback paiement différé", "c"),
    ("R2", "banque", "indisponible (503 / connexion refusée)", "aucun paiement possible", 4, 3, 2, "circuit breaker + fallback 202 + rejeu asynchrone", "b"),
    ("R3", "banque", "erreurs transitoires 30 %", "commandes refusées aléatoirement", 3, 4, 3, "retry ×3 backoff + jitter (sûr grâce à l'idempotence)", "a"),
    ("R4", "banque", "réponse perdue après débit (omission)", "double débit lors du retry : risque financier et juridique", 5, 2, 5, "clé d'idempotence order_id, rejeu renvoie le même débit", "f"),
    ("R5", "orders", "crash de l'instance unique (SPOF)", "aucune commande acceptée ; état en mémoire perdu", 5, 2, 1, "fail-fast au gateway (timeout + breaker), restart auto, 3 réplicas + PDB en k8s", "e"),
    ("R6", "inventory", "perte d'une instance", "réservations lentes ou en échec", 3, 3, 2, "2 réplicas, retry ×2, timeout 0,5 s, bulkhead", "d"),
    ("R7", "inventory", "indisponible", "catalogue vide, aucune réservation", 4, 2, 2, "cache stale-if-error pour /products ; refus rapide 503 + Retry-After pour /checkout", "d"),
    ("R8", "clients", "tempête de retries / client abusif", "saturation du gateway, latence pour tous", 4, 3, 3, "rate limiting par client (429 + Retry-After), load shedding prioritaire, Retry-After respecté", "g"),
    ("R9", "gateway", "saturation (pic de charge)", "files d'attente, timeouts clients, effondrement", 4, 2, 3, "load shedding 32 / 25 % réservés à /checkout, timeouts", "g"),
    ("R10", "tous", "instance en « gray failure » (health check vert, erreurs)", "trafic envoyé à une instance malade", 3, 2, 5, "readiness réelle (démarrage, arrêt, état local), métriques par instance, alertes SLO", "e"),
    ("R11", "orders", "pool de threads saturé par une dépendance lente", "toutes les requêtes bloquées, y compris celles sans paiement", 5, 3, 4, "bulkheads séparés inventory (16) / payment (8), timeouts", "c"),
]
tableau([["ID", "Composant", "Mode de défaillance", "Effet", "G", "O", "D", "C", "Patterns / actions", "Exp."]] +
        [[i, c_, m, e, g, o, d, g * o * d, a, x] for i, c_, m, e, g, o, d, a, x in AMDEC],
        [0.9, 1.6, 3.0, 4.0, 0.6, 0.6, 0.6, 0.7, 4.0, 0.8], size=7.5)
top = sorted(AMDEC, key=lambda r: -(r[4] * r[5] * r[6]))[:3]
para("Les criticités les plus élevées sont " + ", ".join(f"**{r[0]}** ({r[4] * r[5] * r[6]})" for r in top) +
     " : comme au jour 1, ce sont les défaillances temporelles et les pannes difficiles à détecter qui dominent, pas les arrêts francs. "
     "L'ordre des chantiers du projet en découle : timeouts et cloisonnement d'abord, puis fallback, idempotence et protection contre la surcharge.")

# ============================================================================= 4. patterns
saut()
doc.add_heading("4. Patterns de résilience et paramètres justifiés", 1)
para("Dix patterns du module sont mis en œuvre (le minimum demandé est six). Le tableau relie chacun au risque de "
     "l'AMDEC qu'il traite et justifie ses paramètres.")
tableau([["Pattern", "Où", "Paramètres", "Risque", "Justification"],
         ["Timeout", "tous les appels sortants", "gateway→orders 4 s ; orders→inventory 0,5 s ; orders→payment 2 s ; payment→banque 1 s", "R1, R11", "budgets emboîtés : 1 s banque × 3 tentatives plafonnées à 0,5 s d'attente < 2 s orders→payment ; 0,5 s + 2 s < 4 s gateway→orders. Une lenteur en bout de chaîne ne peut pas bloquer l'entrée."],
         ["Retry + backoff + jitter", "payment→banque (×3), orders→inventory (×2)", "base 0,1 s, jitter complet, plafond 0,5 s / 2 s, respect de Retry-After", "R3", "retry seulement sur erreurs transitoires (429, 5xx, timeout) et seulement sur des appels idempotents ; borné pour ne pas amplifier la charge (jour 1 : × 2,25)."],
         ["Circuit breaker", "payment→banque 5 échecs / 10 s ; orders→payment 3 / 10 s ; orders→inventory 5 / 5 s ; gateway→orders 10 / 5 s", "seuil d'échecs consécutifs, délai de réouverture, sonde semi-ouverte", "R1, R2, R5", "échouer vite quand la dépendance est tombée au lieu de payer un timeout à chaque appel ; délai court (5–10 s) pour une récupération rapide."],
         ["Bulkhead", "orders", "16 places pour inventory, 8 pour payment, attente 50 ms", "R11", "une banque lente ne peut occuper que 8 threads : les réservations de stock et les lectures continuent (le jour 1, un pool unique a tout bloqué)."],
         ["Fallback / dégradation gracieuse", "orders : 202 pending_payment + rejeu asynchrone (3 s) ; gateway : catalogue périmé", "statut explicite, en-tête X-Degraded", "R2, R7", "mieux vaut une commande acceptée et payée plus tard qu'un 503 ; préparé avec le métier (statut visible par le client)."],
         ["Rate limiting", "gateway", "token bucket 20 jetons, 10 jetons/s par X-Client-Id, 429 + Retry-After arrondi", "R8", "capacité = rafale tolérée (20), débit = usage normal d'un client ; les autres clients ne sont pas touchés."],
         ["Load shedding", "gateway", "32 requêtes simultanées, 25 % réservées à /checkout, 503 + Retry-After: 1", "R8, R9", "rejet immédiat sans file d'attente ; les commandes (chiffre d'affaires) passent avant le catalogue."],
         ["Health checks", "tous", "/health/live (processus), /ready (démarrage, arrêt, état local), /startup (2 s), /deps (diagnostic) ; drain 5 s sur SIGTERM", "R10", "la readiness ne teste pas les dépendances partagées (sinon toutes les instances sortent du pool ensemble) ; les dépendances sont visibles sur /health/deps et dans les métriques."],
         ["Cache résilient", "gateway /products", "TTL 5 s, stale-if-error 300 s", "R7", "le catalogue change peu : une valeur de 5 min est préférable à une erreur ; le client est informé (X-Degraded: stale)."],
         ["Idempotence", "banque, inventory, orders", "Idempotency-Key = order_id", "R4", "rend les retries sûrs et empêche le double débit lors d'une réponse perdue."]],
        [2.4, 3.0, 4.0, 1.2, 6.0], size=7.5)
doc.add_heading("Extraits de code", 2)
src = lire("services", "common", "resilience.py")
code(src[src.index("class CircuitBreaker"):src.index("# ---------------------------------------------------------------- bulkhead")].rstrip(), size=6.8)
para("Le cœur du circuit breaker : état fermé / ouvert / semi-ouvert, compteur d'échecs consécutifs, publication de "
     "l'état en métrique Prometheus (circuit_breaker_state) et Retry-After calculé sur le temps restant avant la "
     "prochaine sonde.", size=9.5, italic=True)
src_o = lire("services", "orders", "app.py")
code(src_o[src_o.index("    # 2) paiement : dégradable"):src_o.index("    with LOCK:\n        COMMANDES[order_id] = commande")].rstrip(), size=6.8)
para("Le fallback d'orders : quand payment échoue ou que son circuit est ouvert, la commande est acceptée en "
     "pending_payment (202) et comptée comme réponse dégradée ; en mode RESILIENCE=off, le même code renvoie 503.", size=9.5, italic=True)

# ============================================================================= 5. observabilité
saut()
doc.add_heading("5. Observabilité : métriques, tableau de bord, alertes", 1)
doc.add_heading("5.1 Métriques exposées (format Prometheus, /metrics de chaque service)", 2)
tableau([["Métrique", "Type", "Pattern / usage"],
         ["http_requests_total{service,route,code}", "counter", "SLI de disponibilité, débit par code"],
         ["http_request_duration_seconds{service,route}", "histogram", "latence p95 entrante"],
         ["outbound_requests_total / outbound_request_duration_seconds{service,dependance}", "counter / histogram", "latence et résultat des appels sortants : indicateur avancé (cause avant symptôme)"],
         ["timeouts_total, retries_total{service,dependance}", "counter", "timeout, retry"],
         ["circuit_breaker_state / _opened_total / _rejected_total", "gauge / counter", "circuit breaker (0 fermé, 1 semi-ouvert, 2 ouvert)"],
         ["bulkhead_in_flight / bulkhead_rejected_total", "gauge / counter", "bulkhead"],
         ["rate_limited_total, load_shed_total{prioritaire}, load_shedder_in_flight", "counter / gauge", "rate limiting, load shedding"],
         ["cache_requests_total{resultat=hit|stale|miss}, fallback_total{type}", "counter", "cache résilient, dégradation gracieuse"],
         ["orders_pending_payment, orders_total{status}", "gauge / counter", "métier : commandes en attente, statuts finaux"]],
        [7.0, 2.4, 7.2], size=8)
doc.add_heading("5.2 Tableau de bord Grafana", 2)
para("Le tableau de bord « ShopFlow — résilience » est provisionné automatiquement (observability/grafana, généré par "
     "gen_dashboard.py, 13 panneaux) : SLI et budget d'erreur, requêtes par code, latences p95 entrantes et sortantes, "
     "états des circuit breakers (frise), timeouts et retries, rejets (429, délestage, bulkhead, circuit ouvert), cache et "
     "fallbacks, commandes par statut, occupation des pools. Les figures du chapitre 6 sont tracées à partir des mêmes "
     "requêtes PromQL.")
doc.add_heading("5.3 Règles et alertes (observability/prometheus/alerts.yml)", 2)
tableau([["Règle", "Expression (résumé)", "Rôle"],
         ["slo:gateway_availability:ratio_rate5m", "1 − 5xx / (requêtes hors 429) sur 5 min", "SLI enregistré, affiché et alerté"],
         ["ShopFlowSLOAvailability (page)", "SLI < 0,995 pendant 1 min", "symptôme : le SLO est violé, on appelle l'astreinte"],
         ["ShopFlowErrorBudgetBurnFast (page)", "(1 − SLI) > 14,4 × 0,005 pendant 2 min", "burn rate : le budget d'erreur mensuel partirait en 2 jours"],
         ["ShopFlowDependencyLatency (ticket)", "p95 sortant service→dépendance > 1 s pendant 1 min", "cause avant symptôme (jour 1 : la latence de la banque précède de 8 min les erreurs du gateway)"],
         ["ShopFlowCircuitOpen (ticket)", "circuit_breaker_state == 2 pendant 30 s", "une dépendance est isolée"],
         ["ShopFlowPendingPayments (ticket)", "orders_pending_payment > 20 pendant 2 min", "le mode dégradé dure : action métier"]],
        [5.2, 5.6, 5.8], size=8)

# ============================================================================= 6. chaos
saut()
doc.add_heading("6. Campagne de chaos engineering", 1)
doc.add_heading("6.1 Méthode", 2)
puces(["**Générateur de charge** : 6 clients indépendants (X-Client-Id distincts), 70 % de POST /checkout avec order_id unique, 30 % de GET /products, environ 35 requêtes/s au total, pendant toute la campagne.",
       "**SLI** : part des requêtes servies (2xx, réponse nominale ou dégradée) en moins de 1 s ; on distingue nominal / dégradé / erreur.",
       "**Protocole par expérience** : 10 s de référence, injection, 20 s de panne, restauration, 15 s de récupération. Temps de détection = première réponse non nominale ; temps de récupération = premier instant suivi de 3 s de réponses nominales.",
       "**Critère d'arrêt automatique** : SLI < 50 % sur les 5 dernières secondes → la panne est annulée immédiatement.",
       "**Avant / après** : la campagne entière est jouée d'abord avec RESILIENCE=off (aucun pattern) puis avec RESILIENCE=on. Script : chaos/experiences.py ; résultats bruts : chaos/resultats/."])
doc.add_heading("6.2 Résultats", 2)
lignes = [["Exp", "Panne injectée", "SLI avant", "SLI après", "p95 avant", "p95 après", "5xx avant", "5xx après", "Arrêt auto avant", "Détect. / récup. après", "Hyp."]]
for n in "abcdefg":
    a, b = R_OFF[n], R_ON[n]
    lignes.append([n, b["titre"], f"{pm(a)['sli']:.1%}", f"**{pm(b)['sli']:.1%}**", f"{pm(a)['p95_ms']:.0f} ms", f"{pm(b)['p95_ms']:.0f} ms",
                   str(pm(a)["erreurs_5xx"]), str(pm(b)["erreurs_5xx"]), f"t+{a['arret_s']:.1f} s" if a["arret_s"] else "non",
                   f"{f_s(b['detection_s'])} / {f_s(b['recuperation_s'])}", "✔" if b["validee"] else "✘"])
tableau(lignes, [0.8, 4.2, 1.3, 1.3, 1.3, 1.3, 1.1, 1.1, 1.5, 2.1, 0.7], size=7.5)
image("chaos_sli.png", 16.5, "Figure 2 — SLI de disponibilité (règle Prometheus 5 min) pendant la campagne, avant (gauche) et après (droite). Zones rouges : pannes injectées a..g.")
image("chaos_codes.png", 16.5, "Figure 3 — Requêtes par seconde selon le code HTTP vues par le gateway.")
image("chaos_p95.png", 16.5, "Figure 4 — Latence p95 des appels sortants (échelle log) : les timeouts bornent la latence vue par les appelants.")
image("chaos_breakers.png", 16.5, "Figure 5 — États des circuit breakers et commandes en attente de paiement.")
image("chaos_rejets.png", 16.5, "Figure 6 — Protections déclenchées : 429, délestage, bulkhead, circuit ouvert, retries.")
doc.add_heading("6.3 Fiches d'expérience", 2)
for n in "abcdefg":
    a, b = R_OFF[n], R_ON[n]
    doc.add_heading(f"Expérience {n} — {b['titre']}", 3)
    lig = [["Rubrique", "Avant (RESILIENCE=off)", "Après (RESILIENCE=on)"],
           ["État stable (SLI mesuré)", f"{a['ref']['sli']:.1%} ({a['ref']['n']} req)", f"{b['ref']['sli']:.1%} ({b['ref']['n']} req)"],
           ["Hypothèse", b["hypothese"], ""],
           ["Panne injectée / rayon d'impact", b["panne"] + " — " + b["rayon"], ""],
           ["Critère d'arrêt (SLI < 50 % sur 5 s)", f"déclenché à t+{a['arret_s']:.1f} s" if a["arret_s"] else "non déclenché", f"déclenché à t+{b['arret_s']:.1f} s" if b["arret_s"] else "non déclenché"],
           ["Résultat mesuré pendant la panne", f"SLI {pm(a)['sli']:.1%} (nominal {pm(a)['nominal']:.1%}, dégradé {pm(a)['degrade']:.1%}), {pm(a)['erreurs_5xx']} erreurs 5xx, {pm(a)['r429']} x 429, p95 {pm(a)['p95_ms']:.0f} ms",
            f"SLI {pm(b)['sli']:.1%} (nominal {pm(b)['nominal']:.1%}, dégradé {pm(b)['degrade']:.1%}), {pm(b)['erreurs_5xx']} erreurs 5xx, {pm(b)['r429']} x 429, p95 {pm(b)['p95_ms']:.0f} ms"],
           ["Récupération (SLI après restauration)", f"{a['recup']['sli']:.1%}", f"{b['recup']['sli']:.1%}"],
           ["Temps de détection / de récupération", f"{f_s(a['detection_s'])} / {f_s(a['recuperation_s'])}", f"{f_s(b['detection_s'])} / {f_s(b['recuperation_s'])}"],
           ["Hypothèse validée ?", "Oui" if a["validee"] else "Non", "**Oui**" if b["validee"] else "**Non**"]]
    if n == "f":
        lig.append(["Idempotence (débits banque vs commandes)", f"{a['debits_banque']} débits ; {a['commandes']}", f"{b['debits_banque']} débits ; {b['commandes']}"])
    if n == "g":
        lig.append(["Client abusif", f"{a['abus_total']} req, {a['abus_429']} x 429", f"{b['abus_total']} req, {b['abus_429']} x 429"])
    tableau(lig, [4.2, 6.2, 6.2], size=7.5)
doc.add_heading("6.4 Enseignements", 2)
ens = []
a, b = R_OFF["c"], R_ON["c"]
ens.append(f"**La lenteur est plus dangereuse que la panne** : avec la banque à 3 s et sans patterns, le SLI tombe à {pm(a)['sli']:.0%} et le critère d'arrêt {'se déclenche' if a['arret_s'] else 'ne se déclenche pas'} ; avec timeout + breaker + bulkhead, le SLI reste à {pm(b)['sli']:.0%} et le p95 passe de {pm(a)['p95_ms']:.0f} ms à {pm(b)['p95_ms']:.0f} ms.")
a, b = R_OFF["b"], R_ON["b"]
ens.append(f"**Le fallback transforme une panne en mode dégradé** : banque indisponible, {pm(b)['degrade']:.0%} des requêtes sont servies en dégradé (202) contre {pm(a)['erreurs_5xx']} erreurs 5xx avant ; les paiements en attente sont rejoués automatiquement au retour de la banque.")
a, b = R_OFF["f"], R_ON["f"]
ens.append(f"**L'idempotence est indispensable au retry** : {b['debits_banque']} débits pour {b['commandes'].get('paid', 0) + b['commandes'].get('paid_late', 0)} commandes payées après, aucun double débit malgré les réponses perdues.")
a, b = R_OFF["g"], R_ON["g"]
ens.append(f"**Le rate limiting isole l'abuseur** : {b['abus_429']} de ses {b['abus_total']} requêtes reçoivent un 429 et le SLI des autres clients reste à {pm(b)['sli']:.0%} (avant : {pm(a)['sli']:.0%}, {a['abus_total']} requêtes abusives toutes servies).")
a, b = R_OFF["e"], R_ON["e"]
ens.append(f"**Un SPOF reste un SPOF** : le crash d'orders fait tomber les commandes dans les deux modes (SLI après {pm(b)['sli']:.0%}) ; les patterns limitent l'impact (échec rapide, /products toujours servi, récupération en {f_s(b['recuperation_s'])}) mais seule la redondance (manifestes Kubernetes) corrige le risque R5.")
ens.append("**Le critère d'arrêt a joué son rôle** : il a annulé les pannes " + ", ".join(n for n in "abcdefg" if R_OFF[n]["arret_s"]) + " en mode avant, preuve qu'une expérience non protégée peut dépasser son rayon d'impact prévu.")
puces(ens)

# ============================================================================= 7. déploiement
saut()
doc.add_heading("7. Déploiement", 1)
doc.add_heading("7.1 Docker Compose (obligatoire)", 2)
puces(["Une image commune (services/Dockerfile) : python:3.12-slim, utilisateur non root, CMD en forme exec (le processus reçoit SIGTERM), HEALTHCHECK sur /health/live.",
       "docker-compose.yml : 5 services métier (inventory et payment ×2), healthcheck sur /health/ready, restart: unless-stopped, depends_on avec condition service_healthy (bank → payment → orders → gateway), Prometheus (découverte DNS des réplicas) et Grafana provisionnés.",
       "Une seule commande : docker compose up -d --build. Variable RESILIENCE pour le mode avant / après.",
       "Limite connue (TP 10) : Compose ne retire pas du trafic une instance non prête ; un conteneur tué par docker kill n'est pas relancé (seule une sortie spontanée du processus l'est)."])
doc.add_heading("7.2 Kubernetes (bonus)", 2)
puces(["k8s/gen_k8s.py produit un Deployment et un Service par service : 3 réplicas pour gateway et orders, 2 pour inventory et payment, 3 sondes (startup, liveness, readiness), ressources, rolling update maxUnavailable: 0 / maxSurge: 1, anti-affinité par nœud, terminationGracePeriodSeconds 30 (drain de 5 s).",
       "PodDisruptionBudget minAvailable: 2 sur gateway et orders : un drain de nœud n'évince qu'un pod à la fois (vérifié au TP 10 sur un cluster kind : 0 requête en échec pendant delete pod, rolling update et drain).",
       "Avec ces manifestes, la disponibilité théorique de l'acceptation des commandes passe de 99,0 % à 99,995 % (chapitre 3)."])
doc.add_heading("7.3 Exploitation", 2)
puces(["Santé : /health/ready par instance, /health/deps pour le diagnostic des dépendances, tableau de bord Grafana, alertes Prometheus (page / ticket).",
       "Arrêt propre : SIGTERM → readiness en échec → 5 s de drain → arrêt ; aucun appel coupé lors d'un redéploiement.",
       "Runbook minimal : circuit ouvert vers la banque → vérifier /admin de la banque et orders_pending_payment ; SLO violé → regarder les codes par route et la latence sortante pour trouver la dépendance en cause."])

# ============================================================================= 8. limites
doc.add_heading("8. Limites et perspectives", 1)
puces(["**État en mémoire** : commandes, stock et débits sont perdus au redémarrage et empêchent de répliquer orders en Compose. Perspective : base de données (PostgreSQL) et file de messages pour le rejeu des paiements, ce qui rendrait orders sans état et répliquable partout.",
       "**Rate limiting local à l'instance** : avec 3 réplicas de gateway, la limite réelle d'un client est triplée ; perspective : compteurs partagés (Redis) ou limite au niveau de l'ingress.",
       "**Dépendance externe** : la banque reste un fournisseur unique ; perspective : second prestataire de paiement en fallback avec réconciliation.",
       "**Mesures** : chaque expérience a été jouée une fois par mode ; les ordres de grandeur sont stables mais une campagne répétée (game days réguliers) donnerait des intervalles de confiance. Le générateur de charge tourne sur la même machine que la stack.",
       "**Sécurité et production** : pas de TLS, d'authentification ni de limitation par IP réelle ; pas de persistance Prometheus au-delà de 2 jours ; pas de notification d'alerte (Alertmanager) câblée.",
       "**Chaos continu** : les expériences sont lancées à la main ; perspective : exécution planifiée en préproduction avec arrêt automatique branché sur le SLO réel."])

# ============================================================================= annexes
doc.add_heading("Annexes", 1)
doc.add_heading("A. Commandes", 2)
code("""docker compose up -d --build                 # tout démarrer (gateway :8000, banque :8080, Prometheus :9090, Grafana :3000)
RESILIENCE=off docker compose up -d          # mode « avant » (tous les patterns désactivés)
python chaos/experiences.py                  # campagne complète avant / après (~15 min)
python chaos/graphes.py                      # figures Prometheus -> docs/
python analyse/archi.py                      # disponibilité composite et SPOF
python docs/gen_dossier.py                   # régénère ce dossier
docker compose down                          # arrêt""")
doc.add_heading("B. Structure du dépôt", 2)
code("""services/common/   metrics.py  resilience.py  server.py      socle commun (métriques, patterns, HTTP, santé)
services/<svc>/    app.py                                   gateway, orders, inventory, payment, bank
services/Dockerfile                                         image commune (slim, non root, HEALTHCHECK)
docker-compose.yml                                          stack complète + Prometheus + Grafana
observability/prometheus/  prometheus.yml  alerts.yml       découverte DNS, SLI, alertes
observability/grafana/     provisioning/  dashboards/  gen_dashboard.py
chaos/             experiences.py  graphes.py  resultats/   campagne avant / après, courbes, JSON, comparaison.md
analyse/           archi.py  graphe.py  resultats_dispo.txt
k8s/               gen_k8s.py  *.yaml  kind-config.yaml     Deployments, Services, PDB
docs/              Dossier_architecture_MOUSSAOUI_Tarek.docx, figures""")

doc.core_properties.author = AUTEUR
doc.core_properties.title = "Dossier d'architecture — ShopFlow résilient"
doc.save(OUT)
print("écrit", OUT)
