"""Tests d'intégration de l'API REST (DRF)."""
from django.urls import reverse

from .base import BaseTest


class APITest(BaseTest):
    def test_anonyme_refuse(self):
        self.assertEqual(self.client.get(reverse("api:moi")).status_code, 403)

    def test_moi(self):
        self.client.force_login(self.citoyen)
        r = self.client.get(reverse("api:moi"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "citoyen")
        self.assertIn("profil", r.json())
        self.assertNotIn("password", r.json())

    def test_moi_patch_role_ignore(self):
        self.client.force_login(self.citoyen)
        r = self.client.patch(reverse("api:moi"), {"first_name": "Api", "role": "ADMIN"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.first_name, "Api")
        self.assertEqual(self.citoyen.role, "CITOYEN")

    def test_mon_profil_get_put_patch(self):
        self.client.force_login(self.citoyen)
        self.assertEqual(self.client.get(reverse("api:mon_profil")).json()["regime"], "OMNIVORE")
        r = self.client.patch(reverse("api:mon_profil"), {"regime": "VEGAN"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["emission_estimee_hebdo"], "20.2")

    def test_mon_profil_regle_metier(self):
        self.client.force_login(self.citoyen)
        r = self.client.patch(reverse("api:mon_profil"), {"aliments_aimes": "tofu", "aliments_evites": "tofu"},
                              content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("aliments_evites", r.json())

    def test_liste_reservee_admin(self):
        self.client.force_login(self.citoyen)
        self.assertEqual(self.client.get(reverse("api:utilisateurs")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("api:utilisateurs"), {"role": "CITOYEN"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 2)

    def test_detail_admin(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("api:utilisateur_detail", args=[self.citoyen.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("api:utilisateur_detail", args=[9999])).status_code, 404)
        self.client.force_login(self.nutri)
        self.assertEqual(self.client.get(reverse("api:utilisateur_detail", args=[self.citoyen.pk])).status_code, 403)
