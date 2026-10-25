"""python manage.py evaluer_repas_ia [--moteur LOCAL|GEMINI|TOUS] [--limite N] [--json fichier]

Évalue l'IA « texte -> aliments » sur le jeu de test annoté : précision, rappel, F1, matrice de confusion,
temps de réponse. Les résultats sont aussi enregistrés et visibles dans le laboratoire IA (/repas/labo/).
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from repas.models import EvaluationIA
from repas.tasks import executer_evaluation


class Command(BaseCommand):
    help = "Évalue l'IA du module repas (précision / rappel / F1 / matrice de confusion / latence)."

    def add_arguments(self, parser):
        parser.add_argument("--moteur", choices=["LOCAL", "GEMINI", "TOUS"], default="TOUS")
        parser.add_argument("--limite", type=int, default=None, help="nombre de phrases (défaut : toutes)")
        parser.add_argument("--json", dest="fichier_json", help="enregistre le rapport complet dans ce fichier")

    def handle(self, *args, moteur, limite, fichier_json=None, **opts):
        moteurs = ["LOCAL", "GEMINI"] if moteur == "TOUS" else [moteur]
        rapport = {}
        for m in moteurs:
            if m == "GEMINI" and not settings.GEMINI_API_KEY:
                self.stdout.write(self.style.WARNING("GEMINI : clé GEMINI_API_KEY absente, évaluation ignorée."))
                continue
            self.stdout.write(f"Évaluation {m}…")
            ev = EvaluationIA.objects.create(moteur=m)
            executer_evaluation(ev.pk, limite)
            ev.refresh_from_db()
            if ev.statut != EvaluationIA.Statut.TERMINE:
                self.stdout.write(self.style.ERROR(f"  échec : {ev.erreur}"))
                continue
            k = ev.metriques
            rapport[m] = k
            d, c, b, lat = k["detection"], k["categories"], k["bout_en_bout"], k["latence_ms"]
            self.stdout.write(self.style.SUCCESS(
                f"  {k['nb_phrases']} phrases · détection P={d['precision']} R={d['rappel']} F1={d['f1']} · "
                f"catégories exactitude={c['exactitude']} F1 macro={c['f1_macro']} · bout en bout F1={b['f1']} · "
                f"phrases parfaites={k['phrases_parfaites']:.0%} · latence p50={lat['p50']} ms p95={lat['p95']} ms"))
        if fichier_json and rapport:
            with open(fichier_json, "w", encoding="utf-8") as f:
                f.write(json.dumps(rapport, ensure_ascii=False, indent=2))
            self.stdout.write(f"Rapport enregistré : {fichier_json}")
