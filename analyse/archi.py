"""archi.py -- analyse de disponibilité du parcours « passer une commande » (TP 2 appliqué au projet).

Hypothèses : chaque instance de nos services est disponible à 99,5 % (mesure type d'une instance Python
sans redondance), la banque externe à 99,9 %. Pannes supposées indépendantes.
Usage : python archi.py  -> resultats_dispo.txt
"""
from math import prod
import os

HEURES_AN = 8760


def serie(*a):
    return prod(a)


def parallele(*a):
    return 1 - prod(1 - x for x in a)


A_INST, A_BANK = 0.995, 0.999

# Docker Compose : gateway et orders uniques, inventory et payment x2
compose = {
    "gateway": [A_INST],
    "orders": [A_INST],
    "inventory": [A_INST, A_INST],
    "payment": [A_INST, A_INST],
    "banque externe": [A_BANK],
}
# Kubernetes : 3 réplicas pour gateway et orders (manifestes k8s/)
k8s = {**compose, "gateway": [A_INST] * 3, "orders": [A_INST] * 3}


def dispo(archi, sans_banque=False):
    etages = {k: v for k, v in archi.items() if not (sans_banque and k == "banque externe")}
    return serie(*(parallele(*v) for v in etages.values()))


def spof(archi):
    a0 = dispo(archi)
    res = []
    for nom, inst in archi.items():
        if len(inst) == 1:
            a1 = a0 / inst[0] * parallele(inst[0], inst[0])
            res.append((nom, inst[0], a1 - a0, (a1 - a0) * HEURES_AN))
    return sorted(res, key=lambda r: -r[2])


def rapport():
    L = []
    for titre, archi in (("Docker Compose (livré)", compose), ("Kubernetes (manifestes k8s/, 3 réplicas gateway et orders)", k8s)):
        a_sync = dispo(archi)
        a_async = dispo(archi, sans_banque=True)
        L.append(f"=== {titre} ===")
        for nom, inst in archi.items():
            L.append(f"  {nom:<16} {len(inst)} instance(s) à {inst[0]:.1%}  -> étage {parallele(*inst):.5%}")
        L.append(f"  Disponibilité du parcours, banque synchrone dans le chemin critique : {a_sync:.4%}  ({(1 - a_sync) * HEURES_AN:.1f} h/an)")
        L.append(f"  Avec fallback « paiement différé » (la banque sort du chemin d'acceptation) : {a_async:.4%}  ({(1 - a_async) * HEURES_AN:.1f} h/an)")
        L.append("  SPOF (gain si doublé) :")
        for nom, a, gain, h in spof(archi):
            L.append(f"    - {nom:<16} {a:.1%}  gain +{gain:.3%}  ({h:.1f} h/an)")
        L.append("")
    L.append("Objectif : 99,9 % sur l'acceptation des commandes. Atteint seulement si (1) gateway et orders sont redondés et")
    L.append("(2) la banque n'est plus synchrone dans le chemin d'acceptation (fallback paiement différé), d'où l'architecture cible.")
    return "\n".join(L)


if __name__ == "__main__":
    txt = rapport()
    print(txt)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultats_dispo.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
