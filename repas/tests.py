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


# ======================================================= CATÉGORIE AUTOMATIQUE
class CategorieAutoTest(TestCase):
    def test_deviner(self):
        from .categories import deviner_categorie
        cas = {
            "Agneau": "VIANDE_ROUGE", "lentilles": "LEGUMINEUSE", "Pâtes": "FECULENT", "œufs": "LAITIER",
            "pommes de terre": "FECULENT", "pomme": "FRUIT_LEGUME", "couscous au poulet": "VOLAILLE",
            "couscous à l'agneau": "VIANDE_ROUGE", "Lablabi": "LEGUMINEUSE", "table": None, "xyz": None,
        }
        for nom, attendu in cas.items():
            with self.subTest(nom=nom):
                self.assertEqual(deviner_categorie(nom), attendu)

    def test_formulaire_complete_la_categorie(self):
        f = ElementRepasForm(data={"aliment": "Merguez", "categorie": "", "quantite_g": 100})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["categorie"], "VIANDE_ROUGE")

    def test_choix_manuel_conserve(self):
        f = ElementRepasForm(data={"aliment": "merguez végétale", "categorie": "LEGUMINEUSE", "quantite_g": 100})
        self.assertTrue(f.is_valid())
        self.assertEqual(f.cleaned_data["categorie"], "LEGUMINEUSE")

    def test_categorie_introuvable(self):
        f = ElementRepasForm(data={"aliment": "plat mystère", "categorie": "", "quantite_g": 100})
        self.assertIn("categorie", f.errors)

    def test_creation_sans_categorie_via_la_vue(self):
        amine = creer_user("amine")
        self.client.force_login(amine)
        r = self.client.post(reverse("repas:ajouter"), donnees_repas(**{
            "elements-0-aliment": "Couscous", "elements-0-categorie": ""}))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ElementRepas.objects.get(repas__utilisateur=amine).categorie, "FECULENT")
        r = self.client.get(reverse("repas:ajouter"))
        self.assertContains(r, 'id="aide-categories"')


# ==================================================== IA : photo, texte, tounsi
import json as _json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from users.ai import ErreurIA

from . import ia
from .bilan import badges, bilan_semaine, foret, serie_verte
from .categories import remplacement_pour, trouver_aliments
from .models import Remplacement


def reponse_gemini(payload, status=200):
    m = mock.Mock(status_code=status)
    m.json.return_value = {"candidates": [{"content": {"parts": [{"text": _json.dumps(payload)}]}}]}
    m.raise_for_status.side_effect = None
    return m


class TounsiTest(TestCase):
    def test_extraction_darija_latin_et_arabe(self):
        self.assertEqual(trouver_aliments("klit kosksi b l3allouch w slata"),
                         [("couscous", "FECULENT"), ("agneau", "VIANDE_ROUGE"), ("salade", "FRUIT_LEGUME")])
        self.assertEqual(trouver_aliments("كسكسي بالعلوش"), [("couscous", "FECULENT"), ("agneau", "VIANDE_ROUGE")])
        self.assertEqual(trouver_aliments("pommes de terre"), [("pomme de terre", "FECULENT")])
        self.assertEqual(trouver_aliments("ton repas"), [])

    def test_analyse_locale(self):
        r = ia.valider(ia.analyse_locale_texte("3cha : 2 oeufs, 100g fromage w khobz"))
        noms = {a["aliment"]: a["quantite_g"] for a in r["aliments"]}
        self.assertEqual(noms, {"oeuf": 110, "fromage": 100, "pain": 250})
        self.assertEqual(r["type_repas"], "DINER")
        self.assertEqual(ia.analyse_locale_texte("0,2 kg lablabi")["aliments"][0]["quantite_g"], 200)

    def test_remplacements(self):
        self.assertEqual(remplacement_pour("couscous à l'agneau", "VIANDE_ROUGE")[0], "pois chiches")
        self.assertEqual(remplacement_pour("osbane", "VIANDE_ROUGE")[0], "lentilles")
        self.assertIsNone(remplacement_pour("salade", "FRUIT_LEGUME"))


@override_settings(GEMINI_API_KEY="cle-test")
class IaRepasTest(TestCase):
    def test_valider_filtre_et_borne(self):
        r = ia.valider({"type_repas": "BRUNCH", "aliments": [
            {"aliment": "Agneau", "categorie": "INCONNUE", "quantite_g": 99999},
            {"aliment": "123", "categorie": "FECULENT"},
            {"aliment": "truc", "categorie": "PAS_UNE_CATEGORIE"},
            {"aliment": "lentilles", "categorie": "LEGUMINEUSE", "quantite_g": "abc"},
            "pas un dict",
        ]})
        self.assertEqual([(a["aliment"], a["categorie"], a["quantite_g"]) for a in r["aliments"]],
                         [("agneau", "VIANDE_ROUGE", 3000), ("lentilles", "LEGUMINEUSE", 200)])
        self.assertIn(r["type_repas"], Repas.TypeRepas.values)
        self.assertEqual(r["co2_total_kg"], 180.2)
        with self.assertRaises(ErreurIA):
            ia.valider({"aliments": []})
        with self.assertRaises(ErreurIA):
            ia.valider(["liste"])

    def test_type_selon_heure(self):
        import datetime as dt
        tz = timezone.get_current_timezone()
        self.assertEqual(ia.type_selon_heure(dt.datetime(2026, 1, 1, 8, tzinfo=tz)), "PETIT_DEJ")
        self.assertEqual(ia.type_selon_heure(dt.datetime(2026, 1, 1, 13, tzinfo=tz)), "DEJEUNER")
        self.assertEqual(ia.type_selon_heure(dt.datetime(2026, 1, 1, 17, tzinfo=tz)), "COLLATION")
        self.assertEqual(ia.type_selon_heure(dt.datetime(2026, 1, 1, 21, tzinfo=tz)), "DINER")

    @mock.patch("repas.ia.requests.post")
    def test_photo_envoie_image_en_base64(self, post):
        post.return_value = reponse_gemini({"type_repas": "DEJEUNER", "aliments": [
            {"aliment": "couscous", "categorie": "FECULENT", "quantite_g": 300}]})
        r = ia.depuis_photo(b"\xff\xd8image", "image/jpeg")
        self.assertEqual(r["source"], "GEMINI")
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["inlineData"]["mimeType"], "image/jpeg")
        self.assertEqual(parts[0]["inlineData"]["data"], "/9hpbWFnZQ==")

    @mock.patch("repas.ia.requests.post")
    def test_texte_repli_local_si_api_en_panne(self, post):
        import requests as rq
        for effet in (rq.Timeout(), rq.ConnectionError(), mock.Mock(**{"raise_for_status.side_effect": rq.HTTPError(response=mock.Mock(status_code=429))})):
            with self.subTest(effet=effet):
                if isinstance(effet, mock.Mock):
                    post.side_effect, post.return_value = None, effet
                else:
                    post.side_effect = effet
                r = ia.depuis_texte("kosksi b djej")
                self.assertEqual(r["source"], "LOCAL")
                self.assertTrue(r["erreur"])
                self.assertEqual({a["aliment"] for a in r["aliments"]}, {"couscous", "poulet"})

    @mock.patch("repas.ia.requests.post")
    def test_texte_reponse_illisible(self, post):
        m = mock.Mock(); m.raise_for_status.return_value = None; m.json.return_value = {}
        post.return_value = m
        self.assertEqual(ia.depuis_texte("lablabi")["source"], "LOCAL")

    @override_settings(GEMINI_API_KEY="")
    def test_sans_cle(self):
        with self.assertRaises(ErreurIA):
            ia.depuis_photo(b"x", "image/png")
        self.assertEqual(ia.depuis_texte("lablabi")["source"], "LOCAL")


@override_settings(GEMINI_API_KEY="")
class VuesIaTest(TestCase):
    def setUp(self):
        self.amine = creer_user("amine")
        self.client.force_login(self.amine)

    def test_anonyme_et_get_refuses(self):
        self.assertEqual(self.client.get(reverse("repas:ia_texte")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("repas:ia_texte")).status_code, 302)

    def test_texte(self):
        url = reverse("repas:ia_texte")
        r = self.client.post(url, _json.dumps({"texte": "kosksi b l3allouch"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["aliments"]), 2)
        self.assertEqual(self.client.post(url, "{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, "pas du json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, _json.dumps({"texte": "x" * 501}), content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, _json.dumps({"texte": "rien de connu"}), content_type="application/json").status_code, 422)

    def test_photo_validations(self):
        url = reverse("repas:ia_photo")
        self.assertEqual(self.client.post(url).status_code, 400)
        pdf = SimpleUploadedFile("a.pdf", b"%PDF", content_type="application/pdf")
        self.assertEqual(self.client.post(url, {"photo": pdf}).status_code, 400)
        with mock.patch("repas.views.TAILLE_MAX_PHOTO", 2):
            gros = SimpleUploadedFile("a.jpg", b"123", content_type="image/jpeg")
            self.assertEqual(self.client.post(url, {"photo": gros}).status_code, 400)
        img = SimpleUploadedFile("a.jpg", b"jpeg", content_type="image/jpeg")
        r = self.client.post(url, {"photo": img})          # pas de clé -> 503 avec message clair
        self.assertEqual(r.status_code, 503)
        self.assertIn("indisponible", r.json()["erreur"])

    @mock.patch("repas.views.ia.depuis_photo")
    def test_photo_ok(self, depuis_photo):
        depuis_photo.return_value = {"aliments": [], "source": "GEMINI"}
        img = SimpleUploadedFile("a.jpg", b"jpeg", content_type="image/jpeg")
        self.assertEqual(self.client.post(reverse("repas:ia_photo"), {"photo": img}).status_code, 200)

    def test_formulaire_contient_le_panneau_ia(self):
        r = self.client.get(reverse("repas:ajouter"))
        self.assertContains(r, "Remplir avec l'IA")
        self.assertContains(r, reverse("repas:ia_photo"))


# ============================================= simulateur « Et si… » et badges
class SimulateurTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")
        cls.yasmine = creer_user("yasmine")
        cls.repas = Repas.objects.create(utilisateur=cls.amine, type_repas="DEJEUNER")
        cls.agneau = ElementRepas.objects.create(repas=cls.repas, aliment="agneau", categorie="VIANDE_ROUGE", quantite_g=150)
        cls.salade = ElementRepas.objects.create(repas=cls.repas, aliment="salade", categorie="FRUIT_LEGUME", quantite_g=100)

    def setUp(self):
        self.client.force_login(self.amine)

    def test_detail_propose_le_remplacement(self):
        r = self.client.get(reverse("repas:detail", args=[self.repas.pk]))
        self.assertContains(r, "Et si")
        self.assertContains(r, "Pois chiches")          # SUBSTITUTIONS : agneau -> pois chiches
        self.assertContains(r, "−8,85 kg CO₂e")         # 9,0 − 0,15 × 1,0

    def test_appliquer(self):
        r = self.client.post(reverse("repas:remplacer", args=[self.repas.pk, self.agneau.pk]), follow=True)
        self.agneau.refresh_from_db()
        self.assertEqual((self.agneau.aliment, self.agneau.categorie), ("pois chiches", "LEGUMINEUSE"))
        rem = Remplacement.objects.get()
        self.assertEqual(rem.gain_kg, 8.85)
        self.assertIn("agneau", str(rem))
        self.assertContains(r, "Premier pas")

    def test_aliment_deja_sobre(self):
        r = self.client.post(reverse("repas:remplacer", args=[self.repas.pk, self.salade.pk]), follow=True)
        self.assertContains(r, "déjà peu émetteur")
        self.assertEqual(Remplacement.objects.count(), 0)

    def test_securite(self):
        self.client.force_login(self.yasmine)
        self.assertEqual(self.client.post(reverse("repas:remplacer", args=[self.repas.pk, self.agneau.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("repas:remplacer", args=[self.repas.pk, self.agneau.pk])).status_code, 405)

    def test_cinquieme_remplacement_badge(self):
        for _ in range(4):
            Remplacement.objects.create(utilisateur=self.amine, ancien_aliment="x", nouvel_aliment="y", gain_kg=1)
        r = self.client.post(reverse("repas:remplacer", args=[self.repas.pk, self.agneau.pk]), follow=True)
        self.assertContains(r, "Éco-cuisinier")


class BilanTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amine = creer_user("amine")

    def ajouter(self, jours, kg_viande):
        r = Repas.objects.create(utilisateur=self.amine, type_repas="DINER",
                                 date=timezone.localdate() - datetime.timedelta(days=jours))
        ElementRepas.objects.create(repas=r, aliment="boeuf", categorie="VIANDE_ROUGE", quantite_g=int(kg_viande * 1000 / 60))
        return r

    def test_foret(self):
        self.assertEqual(foret(0.3, True)["sains"], 14)
        f = foret(1.15, True)
        self.assertEqual((f["sains"], f["fatigues"], f["morts"]), (3, 4, 7))
        self.assertEqual(foret(2, True)["morts"], 14)
        self.assertIn("Ajoutez", foret(0, False)["message"])
        vide = foret(0, False)          # aucun repas : de jeunes pousses, pas une forêt « parfaite »
        self.assertTrue(vide["vide"])
        self.assertEqual({a["etat"] for a in vide["arbres"]}, {"pousse"})
        self.assertEqual(vide["sains"], 0)
        self.assertEqual(len({a["etat"] for a in foret(1.15, True)["arbres"]}), 3)
        for ratio, mot in [(0.5, "luxuriante"), (0.9, "tient bon"), (1.2, "souffre"), (2, "Alerte")]:
            self.assertIn(mot, foret(ratio, True)["message"])

    def test_serie_et_badges(self):
        p = self.amine.profil
        p.objectif_co2_hebdo = 14       # 2 kg / jour
        p.save()
        for j in (0, 1, 2):
            self.ajouter(j, 1)
        self.ajouter(3, 5)              # jour au-dessus de l'objectif : la série s'arrête
        self.assertEqual(serie_verte(self.amine, 14), 3)
        self.assertEqual(serie_verte(self.amine, None), 0)
        b = {x["nom"]: x["obtenu"] for x in badges(7, 0, 0, 3)}
        self.assertTrue(b["Assidu"] and b["Série verte"])
        self.assertFalse(b["Premier pas"])

    def test_serie_commence_hier_si_rien_aujourdhui(self):
        self.ajouter(1, 1)
        self.assertEqual(serie_verte(self.amine, 14), 1)

    def test_bilan_complet_et_page(self):
        self.ajouter(0, 6)
        self.ajouter(10, 50)            # hors des 7 jours
        b = bilan_semaine(self.amine)
        self.assertEqual(b["km_voiture"], 30)
        self.assertEqual(b["arbres_semaine"], 13)
        self.assertEqual(len(b["jours"]), 7)
        self.assertTrue(b["jours"][-1]["aujourd_hui"])
        self.client.force_login(self.amine)
        r = self.client.get(reverse("repas:liste"))
        self.assertContains(r, 'class="foret')
        self.assertContains(r, "km</strong> en voiture")
        self.assertContains(r, "graphe-barre")
