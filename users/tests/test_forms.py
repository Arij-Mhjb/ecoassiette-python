from users.forms import (
    AdminUtilisateurCreationForm, AdminUtilisateurForm, InfosPersonnellesForm, InscriptionForm,
    SuppressionCompteForm,
)
from users.models import Utilisateur

from .base import MDP, BaseTest


def donnees_inscription(**kw):
    d = {"username": "nouveau", "first_name": "Nour", "last_name": "B", "email": "nour@test.tn",
         "regime": "FLEXITARIEN", "password1": MDP, "password2": MDP, "consentement": "on"}
    d.update(kw)
    return d


class InscriptionFormTest(BaseTest):
    def test_valide_et_role_force_citoyen(self):
        f = InscriptionForm(donnees_inscription(role="ADMIN"))
        self.assertTrue(f.is_valid(), f.errors)
        u = f.save()
        self.assertEqual(u.role, Utilisateur.Role.CITOYEN)
        self.assertEqual(u.profil.regime, "FLEXITARIEN")

    def test_email_deja_utilise_insensible_casse(self):
        f = InscriptionForm(donnees_inscription(email="CITOYEN@test.tn"))
        self.assertFalse(f.is_valid())
        self.assertIn("email", f.errors)

    def test_mot_de_passe_faible(self):
        f = InscriptionForm(donnees_inscription(password1="12345678", password2="12345678"))
        self.assertFalse(f.is_valid())
        self.assertIn("password2", f.errors)

    def test_consentement_obligatoire(self):
        d = donnees_inscription()
        d.pop("consentement")
        self.assertIn("consentement", InscriptionForm(d).errors)

    def test_attributs_aria_sur_erreur(self):
        f = InscriptionForm(donnees_inscription(email="pas-un-email"))
        f.is_valid()
        attrs = f.fields["email"].widget.attrs
        self.assertEqual(attrs["aria-invalid"], "true")
        self.assertIn("id_email_erreurs", attrs["aria-describedby"])


class AutresFormsTest(BaseTest):
    def test_infos_email_pris(self):
        f = InfosPersonnellesForm({"first_name": "a", "last_name": "b", "email": "autre@test.tn"}, instance=self.citoyen)
        self.assertIn("email", f.errors)

    def test_infos_meme_email_ok(self):
        f = InfosPersonnellesForm({"first_name": "a", "last_name": "b", "email": "citoyen@test.tn"}, instance=self.citoyen)
        self.assertTrue(f.is_valid(), f.errors)

    def test_suppression_mauvais_mdp(self):
        self.assertFalse(SuppressionCompteForm(self.citoyen, {"password": "faux"}).is_valid())
        self.assertTrue(SuppressionCompteForm(self.citoyen, {"password": MDP}).is_valid())

    def test_admin_creation_mdp_differents(self):
        f = AdminUtilisateurCreationForm({"username": "z", "email": "z@test.tn", "role": "CITOYEN", "is_active": True,
                                          "password1": MDP, "password2": MDP + "x"})
        self.assertIn("password2", f.errors)

    def test_admin_creation_ok_hache(self):
        f = AdminUtilisateurCreationForm({"username": "z", "email": "z@test.tn", "role": "NUTRITIONNISTE",
                                          "is_active": True, "password1": MDP, "password2": MDP})
        self.assertTrue(f.is_valid(), f.errors)
        u = f.save()
        self.assertTrue(u.check_password(MDP))

    def test_admin_ne_peut_pas_se_retrograder(self):
        f = AdminUtilisateurForm({"username": "admin1", "email": "admin1@test.tn", "role": "CITOYEN", "is_active": True},
                                 instance=self.admin, editeur=self.admin)
        self.assertFalse(f.is_valid())
        self.assertTrue(f.non_field_errors())
