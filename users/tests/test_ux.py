"""Application installable (PWA) et thème clair / sombre."""
from django.test import TestCase
from django.urls import reverse

from .base import BaseTest


class PwaTest(TestCase):
    def test_service_worker_a_la_racine(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/javascript")
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", r["Cache-Control"])
        self.assertIn("hors-ligne", r.content.decode())

    def test_page_hors_ligne_sans_donnee_personnelle(self):
        r = self.client.get(reverse("hors_ligne"))
        self.assertContains(r, "Vous êtes hors ligne")
        self.assertNotContains(r, "Déconnexion")

    def test_manifeste_et_icones_references(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'rel="manifest"')
        self.assertContains(r, "apple-touch-icon")
        self.assertContains(r, "data-installer")


class ThemeTest(BaseTest):
    def test_bouton_et_script_sans_flash(self):
        self.client.force_login(self.citoyen)
        r = self.client.get(reverse("users:profil"))
        self.assertContains(r, 'class="theme-toggle"')
        html = r.content.decode()
        self.assertLess(html.index('localStorage.getItem("theme")'), html.index("<body"))   # thème posé avant l'affichage
