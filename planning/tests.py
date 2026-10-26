from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from repas.models import ElementRepas, Repas
from impact.models import ProduitRecompense, Sponsor
from users.ai import ErreurIA
from users.models import Utilisateur

from .forms import lundi_de
from .models import MenuPlanifie, PlanMenu
from .services import liste_courses


class PlanificateurTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Utilisateur.objects.create_user(
            username="planificateur", email="planning@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )
        cls.autre = Utilisateur.objects.create_user(
            username="autre_planning", email="autre-planning@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )
        cls.lundi = lundi_de(timezone.localdate())

    def setUp(self):
        self.client.force_login(self.user)

    @mock.patch("planning.services.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_generation_cree_quatorze_menus_vegetaux(self, gemini):
        reponse = self.client.post(reverse("planning:generer"), {
            "semaine_du": self.lundi.isoformat(), "objectif_co2": "20",
        })
        plan = PlanMenu.objects.get(utilisateur=self.user, semaine_du=self.lundi)
        self.assertRedirects(reponse, f"/planning/?semaine={self.lundi:%Y-%m-%d}")
        self.assertEqual(plan.menus.count(), 14)
        self.assertEqual(plan.source, "LOCAL")
        self.assertTrue(all(m.co2_estime >= 0 for m in plan.menus.all()))
        page = self.client.get(reverse("planning:tableau"), {"semaine": self.lundi.isoformat()})
        self.assertContains(page, "Objectif hebdomadaire")
        self.assertContains(page, "Liste de courses")

    @mock.patch("planning.services.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_regeneration_propose_un_nouveau_groupe_de_menus(self, gemini):
        donnees = {"semaine_du": self.lundi.isoformat(), "objectif_co2": "20"}
        self.client.post(reverse("planning:generer"), donnees)
        plan = PlanMenu.objects.get(utilisateur=self.user, semaine_du=self.lundi)
        premiers = set(plan.menus.values_list("nom", flat=True))
        self.assertEqual(len(premiers), 14)

        self.client.post(reverse("planning:generer"), donnees)
        plan.refresh_from_db()
        nouveaux = set(plan.menus.values_list("nom", flat=True))
        self.assertEqual(plan.numero_generation, 2)
        self.assertEqual(len(nouveaux), 14)
        self.assertNotEqual(premiers, nouveaux)
        self.assertGreaterEqual(len(nouveaux - premiers), 5)

    @mock.patch("planning.services.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_repas_polluant_affiche_economie_et_remplacement(self, gemini):
        repas = Repas.objects.create(
            utilisateur=self.user, type_repas="DEJEUNER", date=self.lundi,
            note="Steak très émetteur",
        )
        ElementRepas.objects.create(
            repas=repas, aliment="bœuf", categorie="VIANDE_ROUGE", quantite_g=300,
        )
        self.client.post(reverse("planning:generer"), {
            "semaine_du": self.lundi.isoformat(), "objectif_co2": "10",
        })
        menu = MenuPlanifie.objects.get(plan__utilisateur=self.user, date=self.lundi, type_repas="DEJEUNER")
        self.assertEqual(menu.repas_source, repas)
        self.assertGreater(menu.economie_co2, 0)
        page = self.client.get(reverse("planning:tableau"), {"semaine": self.lundi.isoformat()})
        self.assertContains(page, "trop émetteur")
        self.assertContains(page, "par rapport au repas enregistré")

    def test_liste_courses_regroupe_les_quantites(self):
        plan = PlanMenu.objects.create(
            utilisateur=self.user, semaine_du=self.lundi,
            objectif_co2=20, source="LOCAL",
        )
        for jour, quantite in enumerate((100, 150)):
            MenuPlanifie.objects.create(
                plan=plan, date=self.lundi + timedelta(days=jour), type_repas="DEJEUNER",
                nom=f"Lentilles {jour}", ingredients=[{"nom": "Lentilles", "quantite_g": quantite}],
                instructions=[], co2_estime=Decimal("0.10"),
            )
        self.assertEqual(liste_courses(plan), [{"nom": "lentilles", "quantite_g": 250}])
        page = self.client.get(reverse("planning:courses", args=[plan.pk]))
        self.assertContains(page, "250 g")

    def test_un_utilisateur_ne_voit_pas_le_plan_d_un_autre(self):
        plan = PlanMenu.objects.create(
            utilisateur=self.autre, semaine_du=self.lundi,
            objectif_co2=20, source="LOCAL",
        )
        reponse = self.client.get(reverse("planning:courses", args=[plan.pk]))
        self.assertEqual(reponse.status_code, 404)

    @mock.patch("planning.services.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_menus_utilisent_produits_vegetaux_et_affichent_tutoriels(self, gemini):
        sponsor = Sponsor.objects.create(nom="Partenaire veggie", site_web="https://example.com")
        produit = ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Steak burger végétal", description="Alternative au bœuf",
            prix_public="6", remise_pourcent=20, cout_points=80, stock=5,
            mots_cles_recommandation="hamburger, steak, viande hachée",
            url_source="https://example.com/steak-veggie",
            statut=ProduitRecompense.Statut.PUBLIE,
        )
        produit_hache = ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Viande hachée végétale", description="Haché végétal",
            prix_public="5", remise_pourcent=15, cout_points=70, stock=4,
            mots_cles_recommandation="viande hachée, bœuf, burger",
            url_source="https://example.com/hache-veggie",
            statut=ProduitRecompense.Statut.PUBLIE,
        )
        self.client.post(reverse("planning:generer"), {
            "semaine_du": self.lundi.isoformat(), "objectif_co2": "20",
        })
        plan = PlanMenu.objects.get(utilisateur=self.user, semaine_du=self.lundi)
        menu = plan.menus.filter(produit_vegetal=produit).first()
        menu_hache = plan.menus.filter(produit_vegetal=produit_hache).first()
        self.assertIsNotNone(menu)
        self.assertIsNotNone(menu_hache)
        self.assertIn("Hamburger veggie", menu.nom)
        self.assertIn("Bolognaise veggie", menu_hache.nom)
        self.assertEqual(plan.menus.filter(produit_vegetal=produit).count(), 2)
        self.assertEqual(plan.menus.filter(produit_vegetal=produit_hache).count(), 2)
        self.assertTrue(any(i["nom"] == produit.nom for i in menu.ingredients))
        self.assertEqual(plan.menus.values("nom").distinct().count(), 14)
        page = self.client.get(reverse("planning:tableau"), {"semaine": self.lundi.isoformat()})
        self.assertContains(page, "Produit végétal partenaire")
        self.assertContains(page, "Voir le produit")
        self.assertContains(page, "Voir un tutoriel vidéo", count=14)
        self.assertContains(page, "youtube.com/results")
        self.assertContains(page, "protéines", count=14)
        self.assertContains(page, "fibres", count=14)
        self.assertGreater(menu.nutrition["proteines"], 0)
