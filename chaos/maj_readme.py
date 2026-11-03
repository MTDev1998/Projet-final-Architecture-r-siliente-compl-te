"""maj_readme.py -- recopie le tableau avant / après de resultats/comparaison.md dans le README (section Résultats)."""
import os, re

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
readme = os.path.join(RACINE, "README.md")
with open(os.path.join(RACINE, "chaos", "resultats", "comparaison.md"), encoding="utf-8") as f:
    md = f.read()
table = md[md.index("| Exp |"):md.index("## Fiches")].strip()
bloc = ("<!-- resultats:debut -->\n## Résultats de la dernière campagne (avant / après patterns)\n\n"
        + table + "\n\nDétail des fiches : `chaos/resultats/comparaison.md` ; figures : `docs/chaos_*.png` ; "
        "analyse complète : `docs/Dossier_architecture_MOUSSAOUI_Tarek.docx`.\n<!-- resultats:fin -->")
with open(readme, encoding="utf-8") as f:
    txt = f.read()
if "<!-- resultats:debut -->" in txt:
    txt = re.sub(r"<!-- resultats:debut -->.*?<!-- resultats:fin -->", lambda m: bloc, txt, flags=re.S)
else:
    txt = txt.replace("## Contenu du dépôt", bloc + "\n\n## Contenu du dépôt")
with open(readme, "w", encoding="utf-8") as f:
    f.write(txt)
print("README mis à jour")
