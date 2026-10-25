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
    AlternativeAdoptee, AlternativeVegetale, BrouillonRecette, CommandeRecompense, ExtractionRecetteIA,
    FacteurImpact, PreuveRepas, ProduitRecompense, Sponsor, TransactionPoints,
)
from .recipe_ai import categoriser, extraire_localement
from .services import crediter_preuve, proposer_recette_alternative, recommander_produits, solde_points
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

    def test_categorie_distingue_pain_burger_et_hamburger(self):
        self.assertEqual(categoriser("pain burger complet"), "FECULENT")
        self.assertEqual(categoriser("hamburger"), "VIANDE_ROUGE")
        self.assertEqual(categoriser("cheeseburger"), "VIANDE_ROUGE")

    def test_analyse_texte_affiche_brouillon_editable(self):
        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(), "note": "Mon couscous",
            "texte": "300 g d'agneau, 200 g de pois chiches, 2 tomates",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Vérifiez les ingrédients extraits")
        self.assertContains(reponse, "Pois chiches")
        self.assertContains(reponse, "Valider et ajouter à mes repas")

    def test_recommande_un_produit_vegan_lie_a_l_ingredient(self):
        sponsor = Sponsor.objects.create(nom="Partenaire vegan", site_web="https://example.com")
        produit = ProduitRecompense.objects.create(
            sponsor=sponsor,
            nom="Haché végétal",
            description="Alternative végétale riche en protéines",
            prix_public="6.50",
            remise_pourcent=40,
            cout_points=120,
            stock=5,
            mots_cles_recommandation="viande hachée, steak, bœuf",
            url_source="https://example.com/hache-vegan",
            statut=ProduitRecompense.Statut.PUBLIE,
        )
        recommandations = recommander_produits("viande hachée")
        self.assertEqual(recommandations[0]["produit"], produit)

        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Steak maison", "texte": "200 g de bœuf",
        })
        self.assertContains(reponse, "Recommandation IA")
        self.assertContains(reponse, "Haché végétal")
        self.assertContains(reponse, "https://example.com/hache-vegan")

    def test_propose_aussi_un_burger_maison_avec_quantites_et_video(self):
        alternative = AlternativeVegetale.objects.get(aliment_source="bœuf")
        recette = proposer_recette_alternative("steak hamburger", alternative, 200)
        self.assertIn("Burger végan maison", recette["nom"])
        self.assertEqual(recette["ingredients"][0]["quantite_g"], 200)
        self.assertIn("youtube.com/results", recette["video_url"])

        reponse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Burger maison", "texte": "200 g de bœuf",
        })
        self.assertContains(reponse, "Recette proposée par l’IA")
        self.assertContains(reponse, "Burger végan maison")
        self.assertContains(reponse, "Ingrédients pour cette portion")
        self.assertContains(reponse, "Voir des tutoriels vidéo")

    @mock.patch("impact.recipe_ai.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_contexte_pain_burger_ne_recommande_pas_de_viande_mais_hamburger_oui(self, gemini):
        sponsor = Sponsor.objects.create(nom="Burger végétal", site_web="https://example.com")
        ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Steak burger végan", description="Steak végétal",
            prix_public="6", remise_pourcent=10, cout_points=80, stock=5,
            mots_cles_recommandation="hamburger, burger, steak",
            url_source="https://example.com/burger-vegan",
            statut=ProduitRecompense.Statut.PUBLIE,
        )
        pain = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Pain maison", "texte": "120 g de pain burger",
        })
        self.assertNotContains(pain, "Alternative prête à acheter")
        self.assertNotContains(pain, "Recette proposée par l’IA")

        hamburger = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Hamburger", "texte": "200 g de hamburger",
        })
        self.assertContains(hamburger, "Steak burger végan")
        self.assertContains(hamburger, "Burger végan maison")
        self.assertContains(hamburger, "Voir des tutoriels vidéo")

    def test_ne_recommande_pas_un_produit_non_publie(self):
        sponsor = Sponsor.objects.create(nom="Sponsor brouillon", site_web="https://example.com")
        ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Steak végétal brouillon", description="Test",
            prix_public="5", remise_pourcent=30, cout_points=100, stock=5,
            mots_cles_recommandation="steak, viande hachée",
            statut=ProduitRecompense.Statut.BROUILLON,
        )
        self.assertEqual(recommander_produits("steak"), [])

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

    @mock.patch("impact.recipe_ai.appeler_gemini", side_effect=ErreurIA("repli local"))
    def test_cycle_brouillon_analyse_sauvegarde_reprise_et_validation(self, gemini):
        analyse = self.client.post(reverse("impact:assistant_recette"), {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Burger à terminer", "texte": "200 g de bœuf",
        })
        self.assertEqual(analyse.status_code, 200)
        brouillon = BrouillonRecette.objects.get(utilisateur=self.user)
        self.assertFalse(Repas.objects.filter(utilisateur=self.user, note="Burger à terminer").exists())
        self.assertContains(analyse, "Enregistrer le brouillon")

        donnees = {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Burger modifié", "texte": "200 g de bœuf", "source": "LOCAL",
            "brouillon_id": str(brouillon.pk), "action": "enregistrer_brouillon",
            "ingredients-TOTAL_FORMS": "1", "ingredients-INITIAL_FORMS": "1",
            "ingredients-MIN_NUM_FORMS": "1", "ingredients-MAX_NUM_FORMS": "1000",
            "ingredients-0-aliment": "bœuf", "ingredients-0-categorie": "VIANDE_ROUGE",
            "ingredients-0-quantite_g": "180", "ingredients-0-utiliser_alternative": "on",
        }
        sauvegarde = self.client.post(reverse("impact:valider_recette"), donnees)
        self.assertRedirects(
            sauvegarde, reverse("impact:reprendre_brouillon", args=[brouillon.pk])
        )
        brouillon.refresh_from_db()
        self.assertEqual(brouillon.note, "Burger modifié")
        self.assertEqual(brouillon.ingredients[0]["quantite_g"], 180)
        reprise = self.client.get(reverse("impact:reprendre_brouillon", args=[brouillon.pk]))
        self.assertContains(reprise, 'value="180"')

        donnees.pop("action")
        validation = self.client.post(reverse("impact:valider_recette"), donnees)
        repas = Repas.objects.get(utilisateur=self.user, note="Burger modifié")
        self.assertRedirects(validation, reverse("repas:detail", args=[repas.pk]))
        self.assertFalse(BrouillonRecette.objects.filter(pk=brouillon.pk).exists())

    def test_brouillon_d_un_autre_utilisateur_est_inaccessible(self):
        autre = Utilisateur.objects.create_user(
            username="autre_brouillon", email="autre-brouillon@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )
        brouillon = BrouillonRecette.objects.create(
            utilisateur=autre, type_repas="DINER", date=timezone.localdate(),
            note="Privé", texte_original="100 g de tofu", source="LOCAL",
            ingredients=[{"aliment": "tofu", "categorie": "LEGUMINEUSE", "quantite_g": 100}],
        )
        reponse = self.client.get(reverse("impact:reprendre_brouillon", args=[brouillon.pk]))
        self.assertEqual(reponse.status_code, 404)

    def test_produit_vegan_choisi_devient_l_alternative_du_repas(self):
        sponsor = Sponsor.objects.create(nom="Marque végétale", site_web="https://example.com")
        produit = ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Steak végétal premium", description="Alternative à la viande",
            prix_public="6", remise_pourcent=20, cout_points=80, stock=4,
            mots_cles_recommandation="agneau, steak, viande",
            url_source="https://example.com/steak", statut=ProduitRecompense.Statut.PUBLIE,
        )
        donnees = {
            "type_repas": "DINER", "date": timezone.localdate().isoformat(),
            "note": "Repas avec produit vegan", "texte": "200 g d'agneau", "source": "LOCAL",
            "ingredients-TOTAL_FORMS": "1", "ingredients-INITIAL_FORMS": "1",
            "ingredients-MIN_NUM_FORMS": "1", "ingredients-MAX_NUM_FORMS": "1000",
            "ingredients-0-aliment": "agneau", "ingredients-0-categorie": "VIANDE_ROUGE",
            "ingredients-0-quantite_g": "200", "ingredients-0-produit_alternatif_id": str(produit.pk),
        }
        reponse = self.client.post(reverse("impact:valider_recette"), donnees)
        repas = Repas.objects.get(note="Repas avec produit vegan")
        self.assertRedirects(reponse, reverse("repas:detail", args=[repas.pk]))
        element = repas.elements.get()
        self.assertEqual(element.aliment, "Steak végétal premium")
        self.assertEqual(element.categorie, "LEGUMINEUSE")
        adoption = AlternativeAdoptee.objects.get(repas=repas)
        self.assertEqual(adoption.produit_utilise, produit)
        self.assertEqual(adoption.remplacement, "Steak végétal premium")
        self.assertGreater(adoption.co2_evite, 0)

    def test_nom_generique_devient_nom_du_produit_burger_et_s_affiche_dans_titre(self):
        sponsor = Sponsor.objects.create(nom="Marque burger", site_web="https://example.com")
        produit = ProduitRecompense.objects.create(
            sponsor=sponsor, nom="Beyond Burger", description="Burger végétal",
            prix_public="6", remise_pourcent=10, cout_points=80, stock=5,
            mots_cles_recommandation="hamburger, burger, steak",
            url_source="https://example.com/burger", statut=ProduitRecompense.Statut.PUBLIE,
        )
        donnees = {
            "type_repas": "DEJEUNER", "date": timezone.localdate().isoformat(),
            "note": "Poêlée végétale du garde-manger", "texte": "120 g de hamburger",
            "source": "LOCAL", "ingredients-TOTAL_FORMS": "1", "ingredients-INITIAL_FORMS": "1",
            "ingredients-MIN_NUM_FORMS": "1", "ingredients-MAX_NUM_FORMS": "1000",
            "ingredients-0-aliment": "hamburger", "ingredients-0-categorie": "VIANDE_ROUGE",
            "ingredients-0-quantite_g": "120", "ingredients-0-produit_alternatif_id": str(produit.pk),
        }
        reponse = self.client.post(reverse("impact:valider_recette"), donnees)
        repas = Repas.objects.get(utilisateur=self.user, elements__aliment="Beyond Burger")
        self.assertRedirects(reponse, reverse("repas:detail", args=[repas.pk]))
        self.assertEqual(repas.note, "Hamburger veggie")
        self.assertIn("Hamburger veggie", str(repas))

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

    def test_produit_publie_sans_stock_reste_visible(self):
        ProduitRecompense.objects.create(
            sponsor=self.sponsor, nom="Produit bientôt disponible", description="Végétal",
            prix_public="5", remise_pourcent=20, cout_points=50, stock=0,
            url_source="https://example.com/bientot", statut=ProduitRecompense.Statut.PUBLIE,
        )
        reponse = self.client.get(reverse("impact:portefeuille"))
        self.assertContains(reponse, "Produit bientôt disponible")
        self.assertContains(reponse, "Rupture de stock")
        self.assertContains(reponse, "Produit temporairement indisponible")


class AdministrationPointsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user(
            username="admin_points", email="admin-points@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )
        cls.admin.is_staff = True
        cls.admin.is_superuser = True
        cls.admin.save(update_fields=["is_staff", "is_superuser"])
        cls.client_user = Utilisateur.objects.create_user(
            username="client_points", email="client-points@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_peut_ajouter_et_modifier_un_ajustement_manuel(self):
        ajout = self.client.post(reverse("admin:impact_transactionpoints_add"), {
            "utilisateur": self.client_user.pk,
            "montant": 75,
            "motif": "Bonus écologique manuel",
            "_save": "Enregistrer",
        })
        transaction = TransactionPoints.objects.get(utilisateur=self.client_user)
        self.assertRedirects(ajout, reverse("admin:impact_transactionpoints_changelist"))
        self.assertEqual(transaction.montant, 75)

        modification = self.client.post(
            reverse("admin:impact_transactionpoints_change", args=[transaction.pk]),
            {
                "utilisateur": self.client_user.pk,
                "montant": 100,
                "motif": "Bonus écologique corrigé",
                "_save": "Enregistrer",
            },
        )
        self.assertRedirects(modification, reverse("admin:impact_transactionpoints_changelist"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.montant, 100)
        self.assertEqual(solde_points(self.client_user), 100)


class ImportProduitIATest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user(
            username="admin_import", email="admin-import@test.tn",
            password="MotDePasse!42", email_verifie=True,
        )
        cls.admin.is_staff = True
        cls.admin.is_superuser = True
        cls.admin.save(update_fields=["is_staff", "is_superuser"])

    def setUp(self):
        self.client.force_login(self.admin)

    def test_bouton_import_est_accessible(self):
        reponse = self.client.get(reverse("admin:impact_produitrecompense_changelist"))
        self.assertContains(reponse, "Importer depuis une URL avec l’IA")
        reponse = self.client.get(reverse("admin:impact_produitrecompense_importer_ia"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "URL officielle du produit")

    @mock.patch("impact.admin.analyser_url_produit")
    def test_import_cree_un_brouillon_a_verifier(self, analyser):
        analyser.return_value = {
            "nom": "Haché végétal IA",
            "description": "Alternative végétale aux protéines de pois.",
            "sponsor_nom": "Beyond Test",
            "prix_public": 6.5,
            "produit_vegetal": True,
            "mots_cles_recommandation": "viande hachée, steak, burger",
            "url_source": "https://example.com/hache",
            "source": "GEMINI",
        }
        reponse = self.client.post(
            reverse("admin:impact_produitrecompense_importer_ia"),
            {"url": "https://example.com/hache", "remise_pourcent": 40, "cout_points": 80},
        )
        produit = ProduitRecompense.objects.get(nom="Haché végétal IA")
        self.assertRedirects(
            reponse, reverse("admin:impact_produitrecompense_change", args=[produit.pk])
        )
        self.assertEqual(produit.statut, ProduitRecompense.Statut.BROUILLON)
        self.assertEqual(produit.remise_pourcent, 40)
        self.assertEqual(produit.cout_points, 80)
        self.assertEqual(produit.stock, 0)
        self.assertTrue(produit.propose_par_ia)
        self.assertEqual(produit.sponsor.nom, "Beyond Test")
