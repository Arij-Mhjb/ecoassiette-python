from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from food_rescue.models import ProfilBeneficiaire, ReservationSurplus

from .base import FoodRescueTestCase


class ModelesFoodRescueTest(FoodRescueTestCase):
    def test_profil_beneficiaire_valide(self):
        profil = self.beneficiaire.profil_beneficiaire_food_rescue
        self.assertTrue(profil.est_valide)
        self.assertEqual(profil.type_beneficiaire, ProfilBeneficiaire.Type.ETUDIANT)

    def test_annonce_future_est_reservable(self):
        annonce = self.creer_annonce()
        self.assertTrue(annonce.est_reservable)
        self.assertGreater(annonce.disponible_jusquau, timezone.now())

    def test_annonce_passee_refusee_par_validation(self):
        annonce = self.creer_annonce(disponible_jusquau=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(ValidationError):
            annonce.full_clean()

    def test_reservation_propre_annonce_interdite(self):
        annonce = self.creer_annonce()
        reservation = ReservationSurplus(
            annonce=annonce, beneficiaire=self.donateur,
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        with self.assertRaises(ValidationError):
            reservation.full_clean()

    def test_collecte_apres_expiration_interdite(self):
        annonce = self.creer_annonce()
        reservation = ReservationSurplus(
            annonce=annonce, beneficiaire=self.beneficiaire,
            heure_collecte=annonce.disponible_jusquau + timedelta(hours=1),
        )
        with self.assertRaises(ValidationError):
            reservation.full_clean()

    def test_code_collecte_unique_genere(self):
        annonce = self.creer_annonce()
        reservation = ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire,
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        self.assertEqual(len(reservation.code_collecte), 8)

    def test_une_demande_par_beneficiaire(self):
        annonce = self.creer_annonce()
        ReservationSurplus.objects.create(
            annonce=annonce, beneficiaire=self.beneficiaire,
            heure_collecte=timezone.now() + timedelta(hours=2),
        )
        with self.assertRaises(IntegrityError):
            ReservationSurplus.objects.create(
                annonce=annonce, beneficiaire=self.beneficiaire,
                heure_collecte=timezone.now() + timedelta(hours=3),
            )

