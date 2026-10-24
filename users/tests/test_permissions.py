"""Contrôle d'accès par rôle : impossible de contourner via l'URL directe."""
from django.urls import reverse

from users.models import Utilisateur

from .base import BaseTest


class AccesAnonymeTest(BaseTest):
    def test_pages_protegees_redirigent_vers_connexion(self):
        urls = [
            reverse("users:profil"), reverse("users:modifier_profil"), reverse("users:modifier_infos"),
            reverse("users:supprimer_compte"), reverse("users:nutri_profils"),
            reverse("users:admin_liste"), reverse("users:admin_stats"),
            reverse("users:admin_detail", args=[self.citoyen.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r.url.startswith(reverse("users:login")))

    def test_analyse_anonyme(self):
        self.assertEqual(self.client.post(reverse("users:analyse_lancer")).status_code, 302)


class AccesCitoyenTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.citoyen)

    def test_citoyen_interdit_admin_et_nutri(self):
        urls = [
            reverse("users:admin_liste"), reverse("users:admin_creer"), reverse("users:admin_stats"),
            reverse("users:admin_detail", args=[self.autre.pk]),
            reverse("users:admin_modifier", args=[self.autre.pk]),
            reverse("users:admin_supprimer", args=[self.autre.pk]),
            reverse("users:nutri_profils"), reverse("users:nutri_profil_detail", args=[self.autre.profil.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 403)
                self.assertContains(r, "Accès refusé", status_code=403)

    def test_citoyen_ne_peut_pas_supprimer_par_post(self):
        r = self.client.post(reverse("users:admin_supprimer", args=[self.autre.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Utilisateur.objects.filter(pk=self.autre.pk).exists())

    def test_citoyen_ne_peut_pas_basculer(self):
        self.assertEqual(self.client.post(reverse("users:admin_basculer", args=[self.autre.pk])).status_code, 403)

    def test_admin_django_inaccessible(self):
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)  # non staff -> page de login admin


class AccesNutritionnisteTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.nutri)

    def test_voit_profils_publics(self):
        r = self.client.get(reverse("users:nutri_profils"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Citoyen Test")

    def test_filtre_regime(self):
        r = self.client.get(reverse("users:nutri_profils"), {"regime": "VEGAN"})
        self.assertNotContains(r, "Citoyen Test")

    def test_profil_prive_invisible(self):
        p = self.autre.profil
        p.profil_public = False
        p.save()
        self.assertNotContains(self.client.get(reverse("users:nutri_profils")), "Autre Test")
        self.assertEqual(self.client.get(reverse("users:nutri_profil_detail", args=[p.pk])).status_code, 404)

    def test_detail_profil_public(self):
        r = self.client.get(reverse("users:nutri_profil_detail", args=[self.citoyen.profil.pk]))
        self.assertEqual(r.status_code, 200)

    def test_nutri_interdit_gestion(self):
        self.assertEqual(self.client.get(reverse("users:admin_liste")).status_code, 403)


class CrudAdminTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_liste_et_filtres(self):
        r = self.client.get(reverse("users:admin_liste"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "citoyen@test.tn")
        r = self.client.get(reverse("users:admin_liste"), {"q": "nutri", "role": "NUTRITIONNISTE", "actif": "1"})
        self.assertContains(r, "nutri@test.tn")
        self.assertNotContains(r, "citoyen@test.tn")
        r = self.client.get(reverse("users:admin_liste"), {"actif": "0"})
        self.assertContains(r, "Aucun compte")

    def test_creer(self):
        r = self.client.post(reverse("users:admin_creer"), {
            "username": "neo", "first_name": "Neo", "last_name": "N", "email": "neo@test.tn", "telephone": "",
            "role": "NUTRITIONNISTE", "is_active": "on", "password1": "Tres!Solide2026", "password2": "Tres!Solide2026"})
        neo = Utilisateur.objects.get(username="neo")
        self.assertRedirects(r, reverse("users:admin_detail", args=[neo.pk]))
        self.assertTrue(neo.groups.filter(name="Nutritionniste").exists())

    def test_lire(self):
        r = self.client.get(reverse("users:admin_detail", args=[self.citoyen.pk]))
        self.assertContains(r, "citoyen@test.tn")

    def test_modifier(self):
        r = self.client.post(reverse("users:admin_modifier", args=[self.citoyen.pk]), {
            "username": "citoyen", "first_name": "Modif", "last_name": "T", "email": "citoyen@test.tn",
            "telephone": "", "role": "NUTRITIONNISTE", "is_active": "on"})
        self.assertRedirects(r, reverse("users:admin_detail", args=[self.citoyen.pk]))
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.role, "NUTRITIONNISTE")
        self.assertEqual(self.client.get(reverse("users:admin_modifier", args=[self.citoyen.pk])).status_code, 200)

    def test_supprimer(self):
        self.assertEqual(self.client.get(reverse("users:admin_supprimer", args=[self.autre.pk])).status_code, 200)
        r = self.client.post(reverse("users:admin_supprimer", args=[self.autre.pk]))
        self.assertRedirects(r, reverse("users:admin_liste"))
        self.assertFalse(Utilisateur.objects.filter(pk=self.autre.pk).exists())

    def test_ne_peut_pas_se_supprimer(self):
        self.client.post(reverse("users:admin_supprimer", args=[self.admin.pk]))
        self.assertTrue(Utilisateur.objects.filter(pk=self.admin.pk).exists())

    def test_basculer_actif(self):
        self.client.post(reverse("users:admin_basculer", args=[self.autre.pk]))
        self.autre.refresh_from_db()
        self.assertFalse(self.autre.is_active)
        self.client.post(reverse("users:admin_basculer", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_basculer_get_interdit(self):
        self.assertEqual(self.client.get(reverse("users:admin_basculer", args=[self.autre.pk])).status_code, 405)

    def test_statistiques(self):
        self.client.force_login(self.citoyen)
        self.client.post(reverse("users:analyse_lancer"))
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:admin_stats"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total"], 4)
        self.assertEqual(r.context["ia_succes"], 1)
        self.assertIsNotNone(r.context["ia_p95_ms"])

    def test_admin_voit_profils_prives(self):
        p = self.autre.profil
        p.profil_public = False
        p.save()
        self.assertContains(self.client.get(reverse("users:nutri_profils")), "Autre Test")

    def test_dashboard_django_admin(self):
        self.assertEqual(self.client.get("/admin/users/utilisateur/").status_code, 200)
        self.assertEqual(self.client.get("/admin/users/analyseprofilia/").status_code, 200)
