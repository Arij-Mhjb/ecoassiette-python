"""Fonctions citoyennes (repas, profil alimentaire, analyse IA) interdites aux autres rôles."""
from django.urls import reverse

from repas.models import ElementRepas, Repas
from users.models import DemandeNutritionniste, Utilisateur

from .base import MDP, BaseTest


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


class SuperAdministrateurTest(BaseTest):
    """Seul un super-administrateur peut modifier, désactiver ou supprimer un compte administrateur."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin2 = cls.creer("admin2", "ADMIN")
        cls.root = Utilisateur.objects.create_superuser("root", "root@test.tn", MDP)

    def donnees(self, u, **kw):
        d = {"username": u.username, "first_name": "X", "last_name": "Y", "email": u.email, "telephone": "",
             "role": u.role, "is_active": "on"}
        d.update(kw)
        return d

    def test_admin_ne_peut_pas_toucher_un_autre_admin(self):
        self.client.force_login(self.admin)
        for cible in (self.admin2, self.root):
            with self.subTest(cible=cible.username):
                self.assertEqual(self.client.get(reverse("users:admin_modifier", args=[cible.pk])).status_code, 403)
                self.assertEqual(self.client.post(reverse("users:admin_modifier", args=[cible.pk]),
                                                  self.donnees(cible, role="CITOYEN")).status_code, 403)
                self.assertEqual(self.client.post(reverse("users:admin_supprimer", args=[cible.pk])).status_code, 403)
                self.assertEqual(self.client.post(reverse("users:admin_basculer", args=[cible.pk])).status_code, 403)
        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.role, "ADMIN")
        self.assertTrue(self.admin2.is_active)
        self.assertTrue(Utilisateur.objects.filter(pk=self.root.pk).exists())

    def test_admin_gere_toujours_citoyens_et_nutritionnistes(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_basculer", args=[self.nutri.pk]))
        self.nutri.refresh_from_db()
        self.assertFalse(self.nutri.is_active)

    def test_admin_ne_peut_pas_promouvoir_en_admin(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("users:admin_modifier", args=[self.citoyen.pk]), self.donnees(self.citoyen, role="ADMIN"))
        self.assertEqual(r.status_code, 200)            # choix invalide
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.role, "CITOYEN")
        r = self.client.post(reverse("users:admin_creer"), {
            "username": "pirate", "first_name": "P", "last_name": "P", "email": "pirate@test.tn", "telephone": "",
            "role": "ADMIN", "is_active": "on", "password1": "Tres!Solide2026", "password2": "Tres!Solide2026"})
        self.assertFalse(Utilisateur.objects.filter(username="pirate").exists())

    def test_superadmin_peut_tout_faire(self):
        self.client.force_login(self.root)
        r = self.client.post(reverse("users:admin_modifier", args=[self.admin2.pk]), self.donnees(self.admin2, role="NUTRITIONNISTE"))
        self.assertRedirects(r, reverse("users:admin_detail", args=[self.admin2.pk]))
        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.role, "NUTRITIONNISTE")
        self.client.post(reverse("users:admin_modifier", args=[self.citoyen.pk]), self.donnees(self.citoyen, role="ADMIN"))
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.role, "ADMIN")
        self.client.post(reverse("users:admin_supprimer", args=[self.admin.pk]))
        self.assertFalse(Utilisateur.objects.filter(pk=self.admin.pk).exists())

    def test_boutons_masques_pour_un_admin(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:admin_detail", args=[self.admin2.pk]))
        self.assertContains(r, "super-administrateur")
        self.assertNotContains(r, reverse("users:admin_supprimer", args=[self.admin2.pk]))

    def test_site_admin_django_protege(self):
        self.client.force_login(self.admin)
        r = self.client.post(f"/admin/users/utilisateur/{self.admin2.pk}/delete/", {"post": "yes"})
        self.assertIn(r.status_code, (302, 403))
        self.assertTrue(Utilisateur.objects.filter(pk=self.admin2.pk).exists())
        r = self.client.post(f"/admin/users/utilisateur/{self.admin2.pk}/change/", {})
        self.assertEqual(r.status_code, 403)
