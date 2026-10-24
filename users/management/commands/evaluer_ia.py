"""
python manage.py evaluer_ia [--local] [--json rapport.json]

Évaluation de l'IA générative (critère 5.2 de la grille) sur un jeu de profils
de référence. Pour un modèle génératif il n'y a pas de « vérité terrain »
unique : on mesure donc des critères vérifiables automatiquement.

  - Taux de réponses exploitables  : JSON valide et conforme au schéma
  - Respect des aliments évités    : aucune alternative ne contient un aliment évité
  - Alternatives 100 % végétales   : aucun produit animal proposé en remplacement
  - Pertinence goûts               : % d'alternatives qui partent d'un aliment aimé
  - Cohérence de l'objectif        : 5 kg <= objectif <= empreinte estimée
  - Temps de réponse               : moyenne, médiane, p95 (ms)
"""
import json
import statistics
import time
from types import SimpleNamespace

from django.core.management.base import BaseCommand

from users import ai

JEU = [
    ("OMNIVORE_FORT", "couscous à l'agneau, burger, pizza", "aubergines", 4, "Moins de 20 min"),
    ("OMNIVORE", "poulet, steak, lait", "tofu", 2, "20 à 45 min"),
    ("OMNIVORE", "ojja merguez, thon, brick", "pois chiches", 3, "Moins de 20 min"),
    ("FLEXITARIEN", "poulet, fromage, pâtes", "champignons", 1, "20 à 45 min"),
    ("PESCETARIEN", "poisson, crevettes, riz", "lentilles", 2, "J'aime cuisiner longtemps"),
    ("VEGETARIEN", "fromage, oeufs, lablabi", "seitan", 1, "Moins de 20 min"),
    ("VEGAN", "lentilles, houmous", "", 1, "20 à 45 min"),
    ("OMNIVORE_FORT", "kafteji, mloukhia au boeuf, poulet rôti", "haricots", 5, "J'aime cuisiner longtemps"),
    ("OMNIVORE", "burger, fromage, lait", "noix de cajou", 2, "Moins de 20 min"),
    ("FLEXITARIEN", "pizza, couscous, oeuf", "aubergines, tofu", 3, "20 à 45 min"),
]


def profil_factice(regime, aimes, evites, foyer, cuisine):
    from users.models import ProfilAlimentaire
    p = ProfilAlimentaire(regime=regime, aliments_aimes=aimes, aliments_evites=evites, taille_foyer=foyer)
    d = ai.donnees_profil(p)
    d["temps_cuisine"] = cuisine
    return d


class Command(BaseCommand):
    help = "Évalue la qualité et la latence de l'analyse IA du profil."

    def add_arguments(self, parser):
        parser.add_argument("--local", action="store_true", help="N'évaluer que le moteur local")
        parser.add_argument("--json", help="Écrire le rapport dans un fichier JSON")

    def handle(self, *args, **o):
        lignes, durees = [], []
        exploitables = evites_ok = vegetal_ok = gout_ok = objectif_ok = total_alts = 0
        sources = {"GEMINI": 0, "LOCAL": 0}
        for regime, aimes, evites, foyer, cuisine in JEU:
            d = profil_factice(regime, aimes, evites, foyer, cuisine)
            t0 = time.perf_counter()
            source = "LOCAL"
            try:
                if o["local"]:
                    raise ai.ErreurIA("mode local")
                r = ai.valider_resultat(ai.appeler_gemini(ai.construire_prompt(d)), d)
                source = "GEMINI"
            except ai.ErreurIA:
                r = ai.analyse_locale(d)
            durees.append((time.perf_counter() - t0) * 1000)
            sources[source] += 1
            exploitables += 1
            alts = r["alternatives"]
            total_alts += len(alts)
            evites_ok += all(not ai._contient(a["remplacement"] + " " + a.get("idee", ""), d["aliments_evites"]) for a in alts)
            vegetal_ok += all(not (ai._contient(a["remplacement"], ai.PRODUITS_ANIMAUX)
                                   and not ai._contient(a["remplacement"], ai.MARQUEURS_VEGETAUX)) for a in alts)
            gout_ok += sum(1 for a in alts if any(x in a["aliment"].lower() or a["aliment"].lower() in x
                                                  for x in d["aliments_aimes"]))
            objectif_ok += 5 <= r["objectif_recommande_kg"] <= d["empreinte_estimee_kg"]
            lignes.append(SimpleNamespace(regime=regime, source=source, n=len(alts), obj=r["objectif_recommande_kg"],
                                          emp=d["empreinte_estimee_kg"], ms=durees[-1]))

        n = len(JEU)
        rapport = {
            "profils_evalues": n,
            "sources": sources,
            "taux_reponses_exploitables": round(exploitables / n, 3),
            "respect_aliments_evites": round(evites_ok / n, 3),
            "alternatives_100pct_vegetales": round(vegetal_ok / n, 3),
            "pertinence_gouts": round(gout_ok / max(total_alts, 1), 3),
            "coherence_objectif": round(objectif_ok / n, 3),
            "latence_moyenne_ms": round(statistics.mean(durees), 1),
            "latence_mediane_ms": round(statistics.median(durees), 1),
            "latence_p95_ms": round(sorted(durees)[min(n - 1, int(0.95 * n))], 1),
        }
        self.stdout.write(f"{'Régime':<15}{'Source':<8}{'Alt.':>5}{'Objectif':>10}{'Empreinte':>11}{'ms':>9}")
        for l in lignes:
            self.stdout.write(f"{l.regime:<15}{l.source:<8}{l.n:>5}{l.obj:>10}{l.emp:>11}{l.ms:>9.1f}")
        self.stdout.write("")
        for k, v in rapport.items():
            self.stdout.write(f"{k:<32} {v}")
        if o["json"]:
            with open(o["json"], "w", encoding="utf-8") as f:
                json.dump(rapport, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Rapport écrit dans {o['json']}"))
