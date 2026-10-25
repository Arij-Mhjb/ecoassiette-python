import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from food_rescue.ai import analyser_localement
from food_rescue.models import AnnonceSurplus


class ObjetTest:
    unite = "KG"
    quantite = 1
    conservation = "AMBIANTE"
    disponible_jusquau = timezone.now() + timedelta(days=3)


class Command(BaseCommand):
    help = "Évalue gratuitement le classifieur local Food Rescue (accuracy, precision, recall et F1 macro)."

    def add_arguments(self, parser):
        parser.add_argument("--json", dest="sortie")

    def handle(self, *args, **options):
        chemin = Path(__file__).resolve().parents[2] / "evaluation" / "jeu_de_test.json"
        cas = json.loads(chemin.read_text(encoding="utf-8"))
        matrice = defaultdict(lambda: defaultdict(int))
        bons = 0
        for cas_test in cas:
            objet = ObjetTest()
            objet.titre, objet.description = cas_test["titre"], cas_test["description"]
            objet.categorie = AnnonceSurplus.Categorie.AUTRE
            predit = analyser_localement(objet)["categorie"]
            attendu = cas_test["categorie"]
            matrice[attendu][predit] += 1
            bons += int(predit == attendu)
        classes = AnnonceSurplus.Categorie.values
        scores = []
        for classe in classes:
            vp = matrice[classe][classe]
            fp = sum(matrice[a][classe] for a in classes if a != classe)
            fn = sum(matrice[classe][p] for p in classes if p != classe)
            precision = vp / (vp + fp) if vp + fp else 0
            rappel = vp / (vp + fn) if vp + fn else 0
            f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0
            scores.append({"classe": classe, "precision": round(precision, 3), "rappel": round(rappel, 3), "f1": round(f1, 3)})
        rapport = {
            "moteur": "LOCAL", "nombre_cas": len(cas), "accuracy": round(bons / len(cas), 3),
            "f1_macro": round(sum(s["f1"] for s in scores) / len(scores), 3), "par_classe": scores,
            "matrice_confusion": {a: dict(ligne) for a, ligne in matrice.items()},
        }
        self.stdout.write(json.dumps(rapport, ensure_ascii=False, indent=2))
        if options["sortie"]:
            Path(options["sortie"]).write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")

