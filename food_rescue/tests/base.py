from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from food_rescue.models import AnnonceSurplus, ProfilBeneficiaire
from users.models import Utilisateur


@override_settings(IA_SYNCHRONE=True, GEMINI_API_KEY="")
class FoodRescueTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.donateur = Utilisateur.objects.create_user(
            username="donateur", email="donateur@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.beneficiaire = Utilisateur.objects.create_user(
            username="beneficiaire", email="beneficiaire@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.autre = Utilisateur.objects.create_user(
            username="autre", email="autre@test.tn", password="MotDePasse!42", email_verifie=True
        )
        ProfilBeneficiaire.objects.create(
            utilisateur=cls.beneficiaire,
            type_beneficiaire=ProfilBeneficiaire.Type.ETUDIANT,
            organisme="Université de test",
            reference_justificatif="ETU-TEST-001",
            statut=ProfilBeneficiaire.Statut.VALIDEE,
        )

    def creer_annonce(self, **kwargs):
        donnees = {
            "donateur": self.donateur, "titre": "Couscous aux légumes",
            "description": "Quatre portions de couscous et semoule, préparées ce matin.",
            "categorie": "PLAT_PREPARE", "quantite": 4, "unite": "PORTION",
            "conservation": "REFRIGERE", "ville": "Tunis", "lieu_collecte": "Centre-ville Tunis",
            "disponible_jusquau": timezone.now() + timedelta(hours=12), "statut": "DISPONIBLE",
        }
        donnees.update(kwargs)
        return AnnonceSurplus.objects.create(**donnees)

