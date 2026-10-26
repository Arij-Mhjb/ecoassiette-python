import io
import json
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from food_rescue.models import AnnonceSurplus, CollecteSurplus, ProfilBeneficiaire, ReservationSurplus
from food_rescue.services import annonces_recommandees, crediter_donateur
from impact.models import TransactionPoints
from users.models import Utilisateur

from .base import FoodRescueTestCase


class RecommandationTest(FoodRescueTestCase):
    def test_recommandation_exclut_donateur_et_aliment_evite(self):
        self.beneficiaire.profil.ville = "Tunis"
        self.beneficiaire.profil.aliments_evites = "fromage"
        self.beneficiaire.profil.save()
        compatible = self.creer_annonce(titre="Pain complet", description="Pain du jour", urgence_ia="ELEVEE")
        self.creer_annonce(titre="Fromage", description="Fromage réfrigéré", urgence_ia="CRITIQUE")
        self.creer_annonce(donateur=self.beneficiaire, titre="Mon propre don")
        resultats = annonces_recommandees(self.beneficiaire)
        self.assertEqual([r["annonce"].pk for r in resultats], [compatible.pk])
        self.assertIn("dans votre ville", " ".join(resultats[0]["raisons"]))


class CreditDonateurTest(FoodRescueTestCase):
    def test_credit_donateur_est_idempotent(self):
        annonce = self.creer_annonce(co2_evite_estime="4.00", statut="COLLECTEE")
        reservation = ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire, statut="COLLECTEE",
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        collecte = CollecteSurplus.objects.create(
            reservation=reservation, confirmee_par_donateur=True, confirmee_par_beneficiaire=True,
        )
        premiere = crediter_donateur(collecte)
        seconde = crediter_donateur(collecte)
        self.assertEqual(premiere, (True, 90))
        self.assertEqual(seconde, (False, 90))
        self.assertEqual(TransactionPoints.objects.filter(utilisateur=self.donateur).count(), 1)


class CommandesTest(TestCase):
    @override_settings(GEMINI_API_KEY="")
    def test_seed_food_rescue_est_idempotent(self):
        sortie = io.StringIO()
        call_command("seed_food_rescue", stdout=sortie)
        call_command("seed_food_rescue", stdout=sortie)
        self.assertEqual(AnnonceSurplus.objects.count(), 4)
        self.assertEqual(ReservationSurplus.objects.count(), 2)
        self.assertEqual(CollecteSurplus.objects.filter(confirmee_le__isnull=False).count(), 1)
        self.assertEqual(ProfilBeneficiaire.objects.filter(statut="VALIDEE").count(), 3)
        self.assertEqual(TransactionPoints.objects.filter(motif__startswith="Don Food Rescue").count(), 1)

    def test_commande_evaluation_produit_metriques(self):
        sortie = io.StringIO()
        call_command("evaluer_food_rescue", stdout=sortie)
        rapport = json.loads(sortie.getvalue())
        self.assertEqual(rapport["nombre_cas"], 20)
        self.assertGreaterEqual(rapport["accuracy"], 0.8)
        self.assertIn("matrice_confusion", rapport)

