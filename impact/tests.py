from decimal import Decimal
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from repas.models import ElementRepas, Repas
from users.ai import ErreurIA
from users.models import Utilisateur

from .admin import approuver_preuves
from .forms import PreuveRepasForm
from .models import (
    AlternativeAdoptee, AlternativeVegetale, CommandeRecompense, ExtractionRecetteIA,
    FacteurImpact, PreuveRepas, ProduitRecompense, Sponsor, TransactionPoints,
)
from .recipe_ai import extraire_localement
from .services import crediter_preuve, solde_points
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

    @mock.patch("impact.recipe_ai.appeler_gemini", side_effect=Exception("ne doit pas sortir"))
    def test_garde_manger_propose_des_recettes(self, gemini):
        # ErreurIA est normalement levée par le fournisseur ; ce test du repli
        # utilise une vraie absence de clé plutôt que le mock générique.
        gemini.side_effect = ErreurIA("pas de clé")
        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "mode": "garde_manger", "ingredients_maison": "tomates, courgette, cajou et tofu et oignions",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Poêlée végétale du garde-manger")
        self.assertContains(reponse, "150 g de tofu")
        self.assertContains(reponse, "60 g d&#x27;oignions", html=False)
        self.assertContains(reponse, "Analyser et personnaliser ce repas")

    @mock.patch("impact.recipe_ai.appeler_gemini", side_effect=ErreurIA("pas de clé"))
    def test_recette_garde_manger_est_reanalysable(self, gemini):
        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DEJEUNER", "date": timezone.localdate().isoformat(),
            "note": "Poêlée", "texte": "120 g de tomates, 180 g de courgette, 25 g de cajou, 150 g de tofu, 60 g de oignons",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Vérifiez les ingrédients extraits")
        self.assertContains(reponse, 'value="150"')


class RecompensesTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_tmp = tempfile.mkdtemp()
        cls.override_media = override_settings(MEDIA_ROOT=cls.media_tmp)
        cls.override_media.enable()

    @classmethod
    def tearDownClass(cls):
        cls.override_media.disable()
        shutil.rmtree(cls.media_tmp, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = Utilisateur.objects.create_user(
            username="recompense", email="reward@test.tn", password="MotDePasse!42", email_verifie=True
        )
        cls.repas = Repas.objects.create(utilisateur=cls.user, type_repas="DINER")
        ElementRepas.objects.create(
            repas=cls.repas, aliment="pois chiches", categorie="LEGUMINEUSE", quantite_g=200
        )
        cls.alternative = AlternativeVegetale.objects.get(aliment_source="agneau")
        AlternativeAdoptee.objects.create(
            utilisateur=cls.user, repas=cls.repas, alternative=cls.alternative,
            aliment_original="agneau", remplacement="pois chiches", co2_evite="6.82",
            eau_economisee="2650", terres_preservees="31.3",
        )
        cls.sponsor = Sponsor.objects.create(nom="Sponsor végétal", site_web="https://example.com")
        cls.produit = ProduitRecompense.objects.create(
            sponsor=cls.sponsor, nom="Panier végétal", description="Produits végétaux",
            prix_public="20", remise_pourcent=60, cout_points=200, stock=2,
            url_source="https://example.com/produit", statut="PUBLIE",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _preuve(self):
        return PreuveRepas.objects.create(
            utilisateur=self.user, repas=self.repas, type_media="IMAGE",
            media=SimpleUploadedFile("repas.jpg", b"image-test", content_type="image/jpeg"),
        )

    def test_soumission_preuve_pour_repas_vegetalise(self):
        fichier = SimpleUploadedFile("preuve.jpg", b"image-test", content_type="image/jpeg")
        reponse = self.client.post(reverse("impact:soumettre_preuve"), {
            "repas": self.repas.pk, "media": fichier,
        })
        self.assertRedirects(reponse, reverse("impact:portefeuille"))
        self.assertEqual(PreuveRepas.objects.get().statut, "EN_ATTENTE")

    def test_selecteur_affiche_nom_type_date_et_tous_repas_sans_preuve(self):
        repas_simple = Repas.objects.create(
            utilisateur=self.user, type_repas="DEJEUNER", note="Salade maison",
            date=timezone.localdate(),
        )
        ElementRepas.objects.create(
            repas=repas_simple, aliment="tomates", categorie="FRUIT_LEGUME", quantite_g=120
        )
        form = PreuveRepasForm(utilisateur=self.user)
        ids = set(form.fields["repas"].queryset.values_list("pk", flat=True))
        self.assertEqual(ids, {self.repas.pk, repas_simple.pk})
        self.assertIn("Salade maison — Déjeuner", form.fields["repas"].label_from_instance(repas_simple))

        PreuveRepas.objects.create(
            utilisateur=self.user, repas=repas_simple, type_media="IMAGE", media="preuves/test.jpg"
        )
        form = PreuveRepasForm(utilisateur=self.user)
        self.assertNotIn(repas_simple.pk, form.fields["repas"].queryset.values_list("pk", flat=True))

    def test_validation_admin_credite_une_seule_transaction(self):
        preuve = self._preuve()

        class AdminMuet:
            def message_user(self, *args, **kwargs):
                pass

        approuver_preuves(AdminMuet(), None, PreuveRepas.objects.filter(pk=preuve.pk))
        preuve.refresh_from_db()
        self.assertEqual(preuve.statut, "APPROUVEE")
        self.assertGreater(preuve.points_attribues, 50)
        self.assertEqual(TransactionPoints.objects.filter(preuve=preuve).count(), 1)
        approuver_preuves(AdminMuet(), None, PreuveRepas.objects.filter(pk=preuve.pk))
        self.assertEqual(TransactionPoints.objects.filter(preuve=preuve).count(), 1)

    def test_approbation_manuelle_credite_le_portefeuille(self):
        preuve = self._preuve()
        preuve.statut = PreuveRepas.Statut.APPROUVEE
        preuve.save(update_fields=["statut"])
        creee, points = crediter_preuve(preuve)
        self.assertTrue(creee)
        self.assertEqual(solde_points(self.user), points)
        creee_encore, _ = crediter_preuve(preuve)
        self.assertFalse(creee_encore)

    def test_achat_debite_points_et_stock(self):
        TransactionPoints.objects.create(utilisateur=self.user, montant=500, motif="Test")
        reponse = self.client.post(reverse("impact:acheter_produit", args=[self.produit.pk]))
        self.assertRedirects(reponse, reverse("impact:portefeuille"))
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.stock, 1)
        self.assertEqual(solde_points(self.user), 300)
        self.assertTrue(CommandeRecompense.objects.filter(utilisateur=self.user, produit=self.produit).exists())

    def test_achat_refuse_si_solde_insuffisant(self):
        self.client.post(reverse("impact:acheter_produit", args=[self.produit.pk]))
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.stock, 2)
        self.assertFalse(CommandeRecompense.objects.exists())
