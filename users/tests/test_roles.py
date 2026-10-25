"""Fonctions citoyennes (repas, profil alimentaire, analyse IA) interdites aux autres rôles."""
from django.urls import reverse

from repas.models import ElementRepas, Repas
from users.models import DemandeNutritionniste

from .base import BaseTest


class FonctionsCitoyennesTest(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.repas = Repas.objects.create(utilisateur=cls.citoyen, type_repas="DINER")
        cls.element = ElementRepas.objects.create(repas=cls.repas, aliment="agneau", categorie="VIANDE_ROUGE", quantite_g=100)

    def urls_get(self):
        return [reverse("repas:liste"), reverse("repas:ajouter"), reverse("repas:detail", args=[self.repas.pk]),
                reverse("repas:modifier", args=[self.repas.pk]), reverse("repas:supprimer", args=[self.repas.pk]),
                reverse("users:modifier_profil")]

    def urls_post(self):
        return [reverse("repas:ia_texte"), reverse("repas:ia_photo"),
                reverse("repas:remplacer", args=[self.repas.pk, self.element.pk]), reverse("users:analyse_lancer")]

    def test_admin_et_nutritionniste_recoivent_403(self):
        for u in (self.admin, self.nutri):
            self.client.force_login(u)
            for url in self.urls_get():
                with self.subTest(role=u.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            for url in self.urls_post():
                with self.subTest(role=u.role, url=url):
                    self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(Repas.objects.count(), 1)

    def test_citoyen_garde_l_acces(self):
        self.client.force_login(self.citoyen)
        for url in self.urls_get():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_anonyme_redirige_vers_connexion(self):
        r = self.client.get(reverse("repas:liste"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith(reverse("users:login")))

    def test_menu_selon_le_role(self):
        self.client.force_login(self.citoyen)
        self.assertContains(self.client.get(reverse("users:profil")), reverse("repas:liste"))
        for u in (self.admin, self.nutri):
            self.client.force_login(u)
            with self.subTest(role=u.role):
                self.assertNotContains(self.client.get(reverse("users:profil")), reverse("repas:liste"))


class ProfilProfessionnelTest(BaseTest):
    def test_profil_nutritionniste(self):
        DemandeNutritionniste.objects.create(utilisateur=self.nutri, numero_ordre="DN-4242", etablissement="Clinique X",
                                             statut="ACCEPTEE", traitee_par=self.admin)
        self.client.force_login(self.nutri)
        r = self.client.get(reverse("users:profil"))
        self.assertContains(r, "Informations professionnelles")
        self.assertContains(r, "DN-4242")
        self.assertNotContains(r, "Mon empreinte alimentaire")
        self.assertNotContains(r, "Analyse IA de mon profil")

    def test_profil_admin(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:profil"))
        self.assertContains(r, "Mon espace administration")
        self.assertNotContains(r, "Mon empreinte alimentaire")

    def test_profil_citoyen_inchange(self):
        self.client.force_login(self.citoyen)
        r = self.client.get(reverse("users:profil"))
        self.assertContains(r, "Mon empreinte alimentaire")
        self.assertNotContains(r, "Informations professionnelles")
