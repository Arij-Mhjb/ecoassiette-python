from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from food_rescue.models import AnalyseSurplusIA, CollecteSurplus, ProfilBeneficiaire, ReservationSurplus
from impact.models import TransactionPoints
from impact.services import solde_points

from .base import FoodRescueTestCase


@override_settings(DEBUG=True, IA_SYNCHRONE=True, GEMINI_API_KEY="")
class VuesFoodRescueTest(FoodRescueTestCase):
    def setUp(self):
        self.client.force_login(self.donateur)

    def test_liste_exige_connexion(self):
        self.client.logout()
        reponse = self.client.get(reverse("food_rescue:liste"))
        self.assertEqual(reponse.status_code, 302)

    def test_liste_filtre_par_categorie(self):
        self.creer_annonce(titre="Pain", categorie="BOULANGERIE")
        self.creer_annonce(titre="Pommes", categorie="FRUITS_LEGUMES")
        reponse = self.client.get(reverse("food_rescue:liste"), {"categorie": "BOULANGERIE"})
        self.assertContains(reponse, "Pain")
        self.assertNotContains(reponse, "Pommes")

    def test_tableau_de_bord(self):
        self.creer_annonce(statut="COLLECTEE", co2_evite_estime="3.50")
        reponse = self.client.get(reverse("food_rescue:tableau_bord"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "3,50 kg")

    def test_suppression_par_proprietaire(self):
        annonce = self.creer_annonce()
        reponse = self.client.post(reverse("food_rescue:supprimer", args=[annonce.pk]))
        self.assertRedirects(reponse, reverse("food_rescue:mes_annonces"))
        self.assertFalse(type(annonce).objects.filter(pk=annonce.pk).exists())

    def test_creation_et_analyse_locale(self):
        reponse = self.client.post(reverse("food_rescue:creer"), {
            "titre": "Pain complet", "description": "Cinq pains de la journée",
            "categorie": "AUTRE", "quantite": "5", "unite": "UNITE",
            "conservation": "AMBIANTE", "ville": "Tunis", "lieu_collecte": "Lafayette",
            "disponible_jusquau": (timezone.now() + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(reponse.status_code, 302)
        analyse = AnalyseSurplusIA.objects.get()
        self.assertEqual(analyse.statut, "TERMINEE")
        self.assertEqual(analyse.source, "LOCAL")
        self.assertEqual(analyse.annonce.categorie, "BOULANGERIE")

    def test_un_autre_utilisateur_ne_modifie_pas_annonce(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.autre)
        self.assertEqual(self.client.get(reverse("food_rescue:modifier", args=[annonce.pk])).status_code, 404)

    def test_adresse_masquee_avant_acceptation(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.beneficiaire)
        reponse = self.client.get(reverse("food_rescue:detail", args=[annonce.pk]))
        self.assertNotContains(reponse, "Centre-ville Tunis")
        self.assertContains(reponse, "Adresse précise communiquée")

    def test_reservation_et_acceptation(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.beneficiaire)
        reponse = self.client.post(reverse("food_rescue:reserver", args=[annonce.pk]), {
            "heure_collecte": (timezone.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "message": "Je viens avec un sac isotherme.",
        })
        self.assertEqual(reponse.status_code, 302)
        reservation = ReservationSurplus.objects.get()
        self.client.force_login(self.donateur)
        reponse = self.client.post(reverse("food_rescue:traiter_reservation", args=[reservation.pk, "accepter"]))
        self.assertEqual(reponse.status_code, 302)
        reservation.refresh_from_db()
        annonce.refresh_from_db()
        self.assertEqual(reservation.statut, "ACCEPTEE")
        self.assertEqual(annonce.statut, "RESERVEE")
        self.assertTrue(CollecteSurplus.objects.filter(reservation=reservation).exists())

    def test_reservation_interdite_sans_eligibilite_validee(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.autre)
        reponse = self.client.post(reverse("food_rescue:reserver", args=[annonce.pk]), {
            "heure_collecte": (timezone.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "message": "Demande non autorisée",
        })
        self.assertRedirects(reponse, reverse("food_rescue:eligibilite"))
        self.assertFalse(ReservationSurplus.objects.filter(beneficiaire=self.autre).exists())

    def test_demande_eligibilite_creee_en_attente(self):
        self.client.force_login(self.autre)
        reponse = self.client.post(reverse("food_rescue:eligibilite"), {
            "type_beneficiaire": "ASSOCIATION",
            "organisme": "Association Test",
            "reference_justificatif": "ASSO-001",
            "attestation": "on",
        })
        self.assertRedirects(reponse, reverse("food_rescue:eligibilite"))
        profil = ProfilBeneficiaire.objects.get(utilisateur=self.autre)
        self.assertEqual(profil.statut, ProfilBeneficiaire.Statut.EN_ATTENTE)

    def test_autre_utilisateur_ne_traite_pas_reservation(self):
        annonce = self.creer_annonce()
        reservation = ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire,
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        self.client.force_login(self.autre)
        reponse = self.client.post(reverse("food_rescue:traiter_reservation", args=[reservation.pk, "accepter"]))
        self.assertEqual(reponse.status_code, 404)

    def test_double_confirmation_termine_collecte(self):
        annonce = self.creer_annonce(statut="RESERVEE")
        reservation = ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire, statut="ACCEPTEE",
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        self.client.post(reverse("food_rescue:confirmer_collecte", args=[reservation.pk]))
        self.client.force_login(self.beneficiaire)
        self.client.post(reverse("food_rescue:confirmer_collecte", args=[reservation.pk]), {"code": reservation.code_collecte})
        reservation.refresh_from_db()
        annonce.refresh_from_db()
        self.assertEqual(reservation.statut, "COLLECTEE")
        self.assertEqual(annonce.statut, "COLLECTEE")
        collecte = reservation.collecte
        collecte.refresh_from_db()
        self.assertGreater(collecte.points_attribues, 0)
        self.assertEqual(solde_points(self.donateur), collecte.points_attribues)
        self.assertEqual(TransactionPoints.objects.filter(utilisateur=self.donateur).count(), 1)

    def test_mauvais_code_ne_confirme_pas_collecte(self):
        annonce = self.creer_annonce(statut="RESERVEE")
        reservation = ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire, statut="ACCEPTEE",
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        self.client.force_login(self.beneficiaire)
        self.client.post(reverse("food_rescue:confirmer_collecte", args=[reservation.pk]), {"code": "FAUXCODE"})
        self.assertFalse(CollecteSurplus.objects.filter(reservation=reservation, confirmee_par_beneficiaire=True).exists())

    def test_endpoint_analyse_reserve_au_donateur(self):
        annonce = self.creer_annonce()
        AnalyseSurplusIA.objects.create(annonce=annonce)
        self.client.force_login(self.beneficiaire)
        self.assertEqual(self.client.get(reverse("food_rescue:analyse_etat", args=[annonce.pk])).status_code, 404)

