"""Tests unitaires : modèles, contraintes, signaux (groupes/permissions)."""
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from users.models import ProfilAlimentaire, Utilisateur

from .base import BaseTest


class UtilisateurModelTest(BaseTest):
    def test_mot_de_passe_hache(self):
        self.assertNotEqual(self.citoyen.password, "UnMotDePasse!Solide42")
        self.assertTrue(self.citoyen.password.startswith("pbkdf2_sha256$"))

    def test_email_normalise_et_unique(self):
        u = self.creer("Majuscule", Utilisateur.Role.CITOYEN)
        u.email = "  MAJ@Test.TN "
        u.save()
        self.assertEqual(u.email, "maj@test.tn")
        with self.assertRaises(IntegrityError):
            Utilisateur.objects.create_user(username="x", email="maj@test.tn", password="a")

    def test_profil_cree_automatiquement(self):
        self.assertIsInstance(self.citoyen.profil, ProfilAlimentaire)

    def test_groupe_suit_le_role(self):
        self.assertTrue(self.citoyen.groups.filter(name="Citoyen").exists())
        self.citoyen.role = Utilisateur.Role.NUTRITIONNISTE
        self.citoyen.save()
        noms = list(self.citoyen.groups.values_list("name", flat=True))
        self.assertEqual(noms, ["Nutritionniste"])

    def test_admin_est_staff_et_retrogradation(self):
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.has_perm("users.gerer_utilisateurs"))
        self.admin.role = Utilisateur.Role.CITOYEN
        self.admin.save()
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_staff)

    def test_superuser_force_role_admin(self):
        su = Utilisateur.objects.create_superuser("root", "root@test.tn", "x")
        self.assertEqual(su.role, Utilisateur.Role.ADMIN)
        self.assertTrue(su.est_admin)

    def test_permissions_par_role(self):
        self.assertFalse(self.citoyen.has_perm("users.view_profilalimentaire"))
        self.assertTrue(self.nutri.has_perm("users.view_profilalimentaire"))
        self.assertFalse(self.nutri.has_perm("users.gerer_utilisateurs"))
        self.assertTrue(self.nutri.est_nutritionniste)

    def test_groupes_crees_au_migrate(self):
        self.assertEqual(Group.objects.filter(name__in=["Citoyen", "Nutritionniste", "Administrateur"]).count(), 3)

    def test_telephone_invalide(self):
        self.citoyen.telephone = "abc"
        with self.assertRaises(ValidationError):
            self.citoyen.full_clean()

    def test_str(self):
        self.assertEqual(str(self.citoyen), "Citoyen Test")


class ProfilModelTest(BaseTest):
    def test_emission_estimee(self):
        p = self.citoyen.profil
        p.regime = ProfilAlimentaire.Regime.VEGAN
        self.assertEqual(p.emission_estimee_hebdo, Decimal("20.2"))
        p.regime = ProfilAlimentaire.Regime.OMNIVORE_FORT
        self.assertEqual(p.emission_estimee_hebdo, Decimal("50.3"))

    def test_listes_aliments(self):
        p = self.citoyen.profil
        p.aliments_aimes = " Couscous ,  pizza,,"
        self.assertEqual(p.liste_aimes, ["couscous", "pizza"])

    def test_aliment_aime_et_evite_refuse(self):
        p = self.citoyen.profil
        p.aliments_aimes, p.aliments_evites = "tofu, riz", "Tofu"
        with self.assertRaises(ValidationError) as cm:
            p.full_clean()
        self.assertIn("aliments_evites", cm.exception.message_dict)

    def test_objectif_superieur_empreinte_refuse(self):
        p = self.citoyen.profil
        p.regime = ProfilAlimentaire.Regime.VEGAN
        p.objectif_co2_hebdo = Decimal("40")
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_objectif_bornes(self):
        p = self.citoyen.profil
        p.objectif_co2_hebdo = Decimal("2")
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_taille_foyer_bornes(self):
        p = self.citoyen.profil
        p.taille_foyer = 0
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_taux_completion(self):
        p = self.citoyen.profil
        base = p.taux_completion
        p.ville = "Tunis"
        self.assertGreater(p.taux_completion, base)

    def test_str_et_url(self):
        self.assertIn("Citoyen", str(self.citoyen.profil))
        self.assertEqual(self.citoyen.profil.get_absolute_url(), "/comptes/profil/")
