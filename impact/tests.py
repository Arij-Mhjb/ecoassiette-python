from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from repas.models import ElementRepas, Repas
from users.models import Utilisateur

from .models import AlternativeAdoptee, AlternativeVegetale, ExtractionRecetteIA, FacteurImpact
from .recipe_ai import extraire_localement
from .services import analyser_repas


class AnalyseImpactTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Utilisateur.objects.create_user(
            username="eco", email="eco@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.repas = Repas.objects.create(utilisateur=cls.user, type_repas="DEJEUNER")
        ElementRepas.objects.create(
            repas=cls.repas, aliment="bœuf", categorie="VIANDE_ROUGE", quantite_g=200
        )

    def test_calcul_co2_eau_terres(self):
        resultat = analyser_repas(self.repas, self.user)
        self.assertEqual(resultat["totaux"]["co2"], Decimal("7.00"))
        self.assertEqual(resultat["totaux"]["eau"], Decimal("2900.00"))
        self.assertEqual(resultat["totaux"]["terres"], Decimal("32.00"))
        self.assertEqual(resultat["risque_deforestation"], "Élevé")

    def test_alternative_et_economies(self):
        resultat = analyser_repas(self.repas, self.user)
        self.assertEqual(resultat["alternatives"][0]["remplacement"], "lentilles")
        self.assertEqual(resultat["economies"]["co2"], Decimal("6.82"))
        self.assertGreater(resultat["economies"]["eau"], 0)

    def test_aliment_evite_n_est_pas_propose(self):
        self.user.profil.aliments_evites = "lentilles"
        self.user.profil.save()
        resultat = analyser_repas(self.repas, self.user)
        self.assertEqual(resultat["alternatives"], [])

    def test_detail_repas_affiche_impact(self):
        self.client.force_login(self.user)
        reponse = self.client.get(reverse("repas:detail", args=[self.repas.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Impact environnemental estimé")
        self.assertContains(reponse, "Alternatives végétales adaptées")

    def test_facteurs_sont_administrables(self):
        self.assertEqual(FacteurImpact.objects.count(), 7)
        self.assertTrue(AlternativeVegetale.objects.filter(remplacement="lentilles").exists())


class AdoptionAlternativeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Utilisateur.objects.create_user(
            username="citoyen", email="citoyen@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.autre = Utilisateur.objects.create_user(
            username="autre", email="autre@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.repas = Repas.objects.create(utilisateur=cls.user, type_repas="DINER")
        ElementRepas.objects.create(
            repas=cls.repas, aliment="agneau", categorie="VIANDE_ROUGE", quantite_g=200
        )
        cls.alternative = AlternativeVegetale.objects.get(aliment_source="agneau")

    def setUp(self):
        self.client.force_login(self.user)

    def test_adopter_enregistre_les_economies(self):
        url = reverse("impact:adopter", args=[self.repas.pk, self.alternative.pk])
        reponse = self.client.post(url)
        self.assertRedirects(reponse, reverse("repas:detail", args=[self.repas.pk]))
        adoption = AlternativeAdoptee.objects.get()
        self.assertEqual(adoption.utilisateur, self.user)
        self.assertEqual(adoption.remplacement, "pois chiches")
        self.assertGreater(adoption.co2_evite, 0)

    def test_adoption_en_double_est_ignoree(self):
        url = reverse("impact:adopter", args=[self.repas.pk, self.alternative.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(AlternativeAdoptee.objects.count(), 1)

    def test_impossible_adopter_pour_le_repas_d_un_autre(self):
        self.client.force_login(self.autre)
        reponse = self.client.post(
            reverse("impact:adopter", args=[self.repas.pk, self.alternative.pk])
        )
        self.assertEqual(reponse.status_code, 404)
        self.assertFalse(AlternativeAdoptee.objects.exists())

    def test_tableau_de_bord_affiche_le_bilan(self):
        self.client.post(reverse("impact:adopter", args=[self.repas.pk, self.alternative.pk]))
        reponse = self.client.get(reverse("impact:tableau_bord"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Impact de mes repas validés")
        self.assertContains(reponse, "CO₂ émis")
        self.assertContains(reponse, "Pois chiches")

    def test_tableau_de_bord_exige_connexion(self):
        self.client.logout()
        reponse = self.client.get(reverse("impact:tableau_bord"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("users:login"), reponse.url)


class AssistantRecetteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Utilisateur.objects.create_user(
            username="chef", email="chef@test.tn", password="MotDePasse!42", email_verifie=True
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_extraction_locale_quantites_et_categories(self):
        ingredients = extraire_localement(
            "Couscous pour 2 personnes : 300 g d'agneau, 200 g de pois chiches, 2 tomates"
        )
        self.assertEqual([i["aliment"] for i in ingredients], ["agneau", "pois chiches", "tomates"])
        self.assertEqual(ingredients[0]["categorie"], "VIANDE_ROUGE")
        self.assertEqual(ingredients[2]["quantite_g"], 240)

    def test_analyse_texte_affiche_brouillon_editable(self):
        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(), "note": "Mon couscous",
            "texte": "300 g d'agneau, 200 g de pois chiches, 2 tomates",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Vérifiez les ingrédients extraits")
        self.assertContains(reponse, "Pois chiches")
        self.assertContains(reponse, "Valider et ajouter à mes repas")

    def test_validation_cree_repas_modifie_et_bilan(self):
        donnees = {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(), "note": "Couscous végétalisé",
            "texte": "300 g d'agneau, 200 g de semoule", "source": "LOCAL",
            "ingredients-TOTAL_FORMS": "2", "ingredients-INITIAL_FORMS": "2",
            "ingredients-MIN_NUM_FORMS": "1", "ingredients-MAX_NUM_FORMS": "1000",
            "ingredients-0-aliment": "agneau", "ingredients-0-categorie": "VIANDE_ROUGE",
            "ingredients-0-quantite_g": "300", "ingredients-0-utiliser_alternative": "on",
            "ingredients-1-aliment": "semoule", "ingredients-1-categorie": "FECULENT",
            "ingredients-1-quantite_g": "200",
        }
        reponse = self.client.post(reverse("impact:valider_recette"), donnees)
        repas = Repas.objects.get(utilisateur=self.user)
        self.assertRedirects(reponse, reverse("repas:detail", args=[repas.pk]))
        self.assertEqual(set(repas.elements.values_list("aliment", flat=True)), {"pois chiches", "semoule"})
        self.assertTrue(ExtractionRecetteIA.objects.filter(repas=repas, source="LOCAL").exists())
        self.assertEqual(AlternativeAdoptee.objects.filter(repas=repas).count(), 1)

    def test_validation_refuse_les_donnees_incompletes(self):
        reponse = self.client.post(reverse("impact:valider_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(), "texte": "recette",
            "ingredients-TOTAL_FORMS": "0", "ingredients-INITIAL_FORMS": "0",
            "ingredients-MIN_NUM_FORMS": "1", "ingredients-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(Repas.objects.filter(utilisateur=self.user).exists())
