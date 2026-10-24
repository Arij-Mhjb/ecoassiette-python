"""Tests du module Suivi des repas : modèles, formulaires, vues et sécurité."""
import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import Utilisateur

from .forms import ElementRepasForm, RepasForm
from .models import ElementRepas, Repas

MDP = "UnMotDePasse!Solide42"


def creer_user(username):
    return Utilisateur.objects.create_user(
        username=username, email=f"{username}@test.tn", password=MDP, email_verifie=True
    )


def donnees_repas(**extra):
    """Données POST d'un repas avec 1 aliment (format attendu par le formset)."""
    data = {
        "type_repas": "DEJEUNER",
        "date": timezone.localdate().isoformat(),
        "note": "",
        "elements-TOTAL_FORMS": "1",
        "elements-INITIAL_FORMS": "0",
        "elements-MIN_NUM_FORMS": "1",
        "elements-MAX_NUM_FORMS": "1000",
        "elements-0-aliment": "Couscous",
        "elements-0-categorie": "FECULENT",
        "elements-0-quantite_g": "300",
    }
    data.update(extra)
    return data


# =============================================================== TESTS UNITAIRES
class ModelesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")
        cls.repas = Repas.objects.create(utilisateur=cls.amine, type_repas="DINER",
                                         date=datetime.date(2026, 10, 24))

    def test_str(self):
        self.assertEqual(str(self.repas), "Dîner du 24/10/2026")
        e = ElementRepas.objects.create(repas=self.repas, aliment="lentilles",
                                        categorie="LEGUMINEUSE", quantite_g=200)
        self.assertEqual(str(e), "lentilles (200 g)")

    def test_date_par_defaut_aujourdhui(self):
        r = Repas.objects.create(utilisateur=self.amine, type_repas="DINER")
        self.assertEqual(r.date, timezone.localdate())

    def test_quantite_bornee(self):
        for q in (0, 5000):
            with self.subTest(quantite=q):
                e = ElementRepas(repas=self.repas, aliment="x", categorie="FECULENT", quantite_g=q)
                with self.assertRaises(ValidationError):
                    e.full_clean()

    def test_suppression_en_cascade(self):
        ElementRepas.objects.create(repas=self.repas, aliment="pain", categorie="FECULENT", quantite_g=80)
        self.amine.delete()
        self.assertEqual(Repas.objects.count(), 0)
        self.assertEqual(ElementRepas.objects.count(), 0)


class FormulairesTest(TestCase):
    def test_date_future_refusee(self):
        f = RepasForm(data={"type_repas": "DINER", "date": "2099-01-01"})
        self.assertFalse(f.is_valid())
        self.assertIn("date", f.errors)

    def test_type_invalide(self):
        f = RepasForm(data={"type_repas": "BRUNCH", "date": "2026-10-24"})
        self.assertIn("type_repas", f.errors)

    def test_aliment_nettoye(self):
        f = ElementRepasForm(data={"aliment": "  Couscous ", "categorie": "FECULENT", "quantite_g": 100})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["aliment"], "couscous")

    def test_aliment_numerique_refuse(self):
        f = ElementRepasForm(data={"aliment": "123", "categorie": "FECULENT", "quantite_g": 100})
        self.assertIn("aliment", f.errors)


# ========================================================= TESTS D'INTÉGRATION
class VuesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")
        cls.yasmine = creer_user("yasmine")
        cls.repas_amine = Repas.objects.create(utilisateur=cls.amine, type_repas="DINER")
        ElementRepas.objects.create(repas=cls.repas_amine, aliment="ojja", categorie="FRUIT_LEGUME", quantite_g=250)
        cls.repas_yasmine = Repas.objects.create(utilisateur=cls.yasmine, type_repas="DEJEUNER")

    def setUp(self):
        self.client.force_login(self.amine)

    def test_liste_ne_montre_que_mes_repas(self):
        r = self.client.get(reverse("repas:liste"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.context["repas_list"]), [self.repas_amine])
        self.assertContains(r, "ojja")

    def test_filtre_par_type(self):
        r = self.client.get(reverse("repas:liste"), {"type": "PETIT_DEJ"})
        self.assertEqual(len(r.context["repas_list"]), 0)

    def test_detail(self):
        r = self.client.get(reverse("repas:detail", args=[self.repas_amine.pk]))
        self.assertContains(r, "Ojja")

    def test_creer_repas_avec_aliments(self):
        r = self.client.post(reverse("repas:ajouter"), donnees_repas())
        nouveau = Repas.objects.filter(utilisateur=self.amine).latest("cree_le")
        self.assertRedirects(r, reverse("repas:detail", args=[nouveau.pk]))
        self.assertEqual(nouveau.elements.get().aliment, "couscous")

    def test_utilisateur_force_cote_serveur(self):
        # même si le POST contient un autre utilisateur, le repas est à amine
        self.client.post(reverse("repas:ajouter"), donnees_repas(utilisateur=self.yasmine.pk))
        self.assertEqual(Repas.objects.filter(utilisateur=self.yasmine).count(), 1)

    def test_creer_sans_aliment_refuse(self):
        r = self.client.post(reverse("repas:ajouter"), donnees_repas(**{"elements-0-aliment": "",
                                                                          "elements-0-categorie": "",
                                                                          "elements-0-quantite_g": ""}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Repas.objects.filter(utilisateur=self.amine).count(), 1)

    def test_modifier(self):
        e = self.repas_amine.elements.get()
        data = donnees_repas(**{
            "type_repas": "DINER", "note": "modifié",
            "elements-INITIAL_FORMS": "1",
            "elements-0-id": str(e.pk), "elements-0-repas": str(self.repas_amine.pk),
            "elements-0-aliment": "ojja", "elements-0-categorie": "FRUIT_LEGUME", "elements-0-quantite_g": "400",
        })
        r = self.client.post(reverse("repas:modifier", args=[self.repas_amine.pk]), data)
        self.assertRedirects(r, reverse("repas:detail", args=[self.repas_amine.pk]))
        e.refresh_from_db()
        self.assertEqual(e.quantite_g, 400)

    def test_supprimer(self):
        r = self.client.post(reverse("repas:supprimer", args=[self.repas_amine.pk]))
        self.assertRedirects(r, reverse("repas:liste"))
        self.assertFalse(Repas.objects.filter(pk=self.repas_amine.pk).exists())


class SecuriteTest(TestCase):
    """Impossible de contourner l'accès via une URL directe."""

    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")
        cls.yasmine = creer_user("yasmine")
        cls.repas_yasmine = Repas.objects.create(utilisateur=cls.yasmine, type_repas="DEJEUNER")

    def test_anonyme_redirige_vers_connexion(self):
        for nom in ["repas:liste", "repas:ajouter"]:
            with self.subTest(url=nom):
                r = self.client.get(reverse(nom))
                self.assertEqual(r.status_code, 302)
                self.assertIn(reverse("users:login"), r.url)

    def test_repas_d_un_autre_utilisateur_404(self):
        self.client.force_login(self.amine)
        pk = self.repas_yasmine.pk
        for nom in ["repas:detail", "repas:modifier", "repas:supprimer"]:
            with self.subTest(url=nom):
                self.assertEqual(self.client.get(reverse(nom, args=[pk])).status_code, 404)
        # même en POST direct, rien n'est supprimé
        self.assertEqual(self.client.post(reverse("repas:supprimer", args=[pk])).status_code, 404)
        self.assertTrue(Repas.objects.filter(pk=pk).exists())


# ================================================================ EMPREINTE CO2
class Co2Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")
        cls.repas = Repas.objects.create(utilisateur=cls.amine, type_repas="DEJEUNER")
        ElementRepas.objects.create(repas=cls.repas, aliment="agneau", categorie="VIANDE_ROUGE", quantite_g=100)
        ElementRepas.objects.create(repas=cls.repas, aliment="semoule", categorie="FECULENT", quantite_g=250)

    def test_calcul_element_et_repas(self):
        agneau = self.repas.elements.get(aliment="agneau")
        self.assertEqual(agneau.co2_kg, 6.0)            # 0,1 kg × 60
        self.assertEqual(self.repas.co2_kg, 6.4)        # 6,0 + 0,25 × 1,6
        self.assertEqual(self.repas.niveau_co2, "eleve")
        self.assertEqual(self.repas.element_le_plus_emetteur, agneau)

    def test_niveaux(self):
        r = Repas.objects.create(utilisateur=self.amine, type_repas="DINER")
        self.assertEqual(r.co2_kg, 0)
        self.assertIsNone(r.element_le_plus_emetteur)
        ElementRepas.objects.create(repas=r, aliment="lentilles", categorie="LEGUMINEUSE", quantite_g=300)
        self.assertEqual(r.niveau_co2, "faible")
        ElementRepas.objects.create(repas=r, aliment="poulet", categorie="VOLAILLE", quantite_g=100)
        self.assertEqual(r.niveau_co2, "moyen")

    def test_bilan_semaine_avec_objectif(self):
        p = self.amine.profil
        p.objectif_co2_hebdo = 8
        p.save()
        ancien = Repas.objects.create(utilisateur=self.amine, type_repas="DINER",
                                      date=timezone.localdate() - datetime.timedelta(days=10))
        ElementRepas.objects.create(repas=ancien, aliment="boeuf", categorie="VIANDE_ROUGE", quantite_g=500)
        self.client.force_login(self.amine)
        r = self.client.get(reverse("repas:liste"))
        bilan = r.context["bilan"]
        self.assertEqual(bilan["total"], 6.4)            # le repas d'il y a 10 jours est exclu
        self.assertEqual(bilan["pct"], 80)
        self.assertFalse(bilan["depasse"])
        self.assertContains(r, "co2-eleve")

    def test_bilan_sans_objectif_utilise_empreinte_du_regime(self):
        from repas.views import bilan_semaine
        b = bilan_semaine(self.amine)
        self.assertEqual(b["objectif"], float(self.amine.profil.emission_estimee_hebdo))
        self.assertIn("régime", b["source"])

    def test_bilan_depasse(self):
        p = self.amine.profil
        p.objectif_co2_hebdo = 5
        p.save()
        self.client.force_login(self.amine)
        r = self.client.get(reverse("repas:liste"))
        self.assertTrue(r.context["bilan"]["depasse"])
        self.assertEqual(r.context["bilan"]["pct_barre"], 100)
        self.assertContains(r, "Objectif dépassé")

    def test_detail_affiche_astuce(self):
        self.client.force_login(self.amine)
        r = self.client.get(reverse("repas:detail", args=[self.repas.pk]))
        self.assertContains(r, "6,4 kg CO₂e")
        self.assertContains(r, "Astuce")
