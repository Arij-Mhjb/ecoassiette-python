"""Tableau de bord admin personnalisé (template tags eco_admin)."""
from django.test import TestCase

from users.models import Utilisateur
from users.templatetags import eco_admin


class AdminThemeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.su = Utilisateur.objects.create_superuser("root", "root@test.tn", "x")
        cls.staff = Utilisateur.objects.create_user("staffsans", "s@test.tn", "x", is_staff=True, email_verifie=True)

    def test_dashboard_superuser(self):
        self.client.force_login(self.su)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Vue d'ensemble")
        self.assertContains(r, "eco-stat")
        self.assertContains(r, "Bonjour, root")

    def test_dashboard_sans_permission(self):
        # staff sans aucune permission : pas de cartes, message d'absence de droits
        Utilisateur.objects.filter(pk=self.staff.pk).update(is_staff=True)
        self.client.force_login(self.staff)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'class="eco-stat ')

    def test_page_login_admin(self):
        r = self.client.get("/admin/login/")
        self.assertContains(r, "eco-admin.css")

    def test_icones_et_styles(self):
        self.assertIn("<svg", eco_admin.eco_icon("inconnu"))
        self.assertEqual(eco_admin._style("users.utilisateur"), ("users", "blue"))
        self.assertEqual(eco_admin._style("x.y"), ("box", "slate"))
        self.assertIn("<svg", eco_admin.eco_app_icon("repas"))

    def test_stats_robustes(self):
        class Casse:
            class _default_manager:
                @staticmethod
                def count():
                    raise RuntimeError("table absente")
        app_list = [{"app_label": "x", "name": "X", "models": [
            {"model": None, "name": "Sans modèle", "object_name": "A"},
            {"model": Casse, "name": "Cassé", "object_name": "B"},
            {"model": Utilisateur, "name": "Utilisateurs", "object_name": "Utilisateur", "admin_url": "/a/"},
        ]}]
        cartes = eco_admin.eco_stats(app_list)
        self.assertEqual(len(cartes), 1)
        self.assertEqual(cartes[0]["total"], 2)
        self.assertEqual(eco_admin.eco_stats(None), [])

    def test_resume(self):
        r = eco_admin.eco_resume()
        self.assertEqual(r["actifs"], 2)
