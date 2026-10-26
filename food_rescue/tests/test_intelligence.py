from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from food_rescue.intelligence import doublons_probables, risque_non_collecte, score_matching
from food_rescue.models import ProfilBeneficiaire, ReservationSurplus
from users.models import Utilisateur

from .base import FoodRescueTestCase


@override_settings(GEMINI_API_KEY="")
class IntelligenceAvanceeTest(FoodRescueTestCase):
    def test_matching_explicable_et_equitable(self):
        self.beneficiaire.profil.ville = "Tunis"
        self.beneficiaire.profil.aliments_aimes = "couscous, légumes"
        self.beneficiaire.profil.save()
        resultat = score_matching(self.beneficiaire, self.creer_annonce())
        self.assertGreaterEqual(resultat["score"], 70)
        self.assertIn("dans votre ville (Tunis)", resultat["raisons"])

    def test_doublon_probable(self):
        self.creer_annonce(titre="Panier légumes frais", description="Tomates carottes courgettes")
        seconde = self.creer_annonce(titre="Panier de légumes frais", description="Tomates, carottes et courgettes")
        self.assertTrue(doublons_probables(seconde, seuil=50))

    def test_risque_collecte_en_retard(self):
        annonce = self.creer_annonce(statut="RESERVEE")
        ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire, statut="ACCEPTEE",
            heure_collecte=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(risque_non_collecte(self.beneficiaire)["niveau"], "ELEVE")

    def test_assistant_repond_sur_eligibilite(self):
        self.client.force_login(self.beneficiaire)
        reponse = self.client.post(reverse("food_rescue:assistant"), {"question": "Mon éligibilité ?"})
        self.assertContains(reponse, "Validé")

    def test_recettes_reservees_aux_participants(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.autre)
        self.assertEqual(self.client.get(reverse("food_rescue:recettes", args=[annonce.pk])).status_code, 403)
        self.client.force_login(self.donateur)
        self.assertContains(self.client.get(reverse("food_rescue:recettes", args=[annonce.pk])), "Recettes anti-gaspillage")

    def test_dashboard_ia_admin(self):
        admin = Utilisateur.objects.create_user(
            "adminia", "adminia@test.tn", "MotDePasse!42", role="ADMIN", email_verifie=True
        )
        self.client.force_login(self.beneficiaire)
        self.assertEqual(self.client.get(reverse("food_rescue:intelligence_dashboard")).status_code, 403)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("food_rescue:intelligence_dashboard")).status_code, 200)

    def test_administration_unifiee_valide_eligibilite(self):
        admin = Utilisateur.objects.create_user(
            "adminrescue", "adminrescue@test.tn", "MotDePasse!42", role="ADMIN", email_verifie=True
        )
        profil = ProfilBeneficiaire.objects.create(
            utilisateur=self.autre, type_beneficiaire="ASSOCIATION",
            organisme="Association test", reference_justificatif="ASSO-42",
        )
        self.client.force_login(self.beneficiaire)
        self.assertEqual(self.client.get(reverse("food_rescue:administration")).status_code, 403)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("food_rescue:administration")), "Association test")
        reponse = self.client.post(reverse("food_rescue:traiter_eligibilite", args=[profil.pk, "valider"]))
        self.assertRedirects(reponse, reverse("food_rescue:administration"))
        profil.refresh_from_db()
        self.assertEqual(profil.statut, ProfilBeneficiaire.Statut.VALIDEE)
        self.assertEqual(profil.verifie_par, admin)

    def test_refus_eligibilite_exige_un_motif(self):
        admin = Utilisateur.objects.create_user(
            "adminrefus", "adminrefus@test.tn", "MotDePasse!42", role="ADMIN", email_verifie=True
        )
        profil = ProfilBeneficiaire.objects.create(
            utilisateur=self.autre, type_beneficiaire="ETUDIANT",
            organisme="Université test", reference_justificatif="ETU-42",
        )
        self.client.force_login(admin)
        self.client.post(reverse("food_rescue:traiter_eligibilite", args=[profil.pk, "refuser"]), {"motif": ""})
        profil.refresh_from_db()
        self.assertEqual(profil.statut, ProfilBeneficiaire.Statut.EN_ATTENTE)
