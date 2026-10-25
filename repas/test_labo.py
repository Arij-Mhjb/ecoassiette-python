"""Laboratoire IA : calcul des métriques, jeu de test, page d'administration, commande."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import Utilisateur

from .evaluation import metriques as M
from .models import FACTEURS_CO2, EvaluationIA

MDP = "UnMotDePasse!Solide42"


def A(nom, cat):
    return {"aliment": nom, "categorie": cat}


class CalculMetriquesTest(TestCase):
    def test_equivalences_tounsi(self):
        self.assertTrue(M.cles("3dham") & M.cles("œufs"))
        self.assertTrue(M.cles("ma9rouna") & M.cles("pâtes"))
        self.assertFalse(M.cles("poulet") & M.cles("poisson"))

    def test_appariement(self):
        paires, fp, fn = M.apparier([A("agneau", "VIANDE_ROUGE"), A("salade", "FRUIT_LEGUME")],
                                    [A("l3allouch", "VIANDE_ROUGE"), A("pain", "FECULENT")])
        self.assertEqual(len(paires), 1)
        self.assertEqual([p["aliment"] for p in fp], ["pain"])
        self.assertEqual([a["aliment"] for a in fn], ["salade"])

    def test_precision_rappel_f1_et_confusion(self):
        m = M.calculer([
            {"texte": "1", "attendu": [A("agneau", "VIANDE_ROUGE"), A("riz", "FECULENT")],
             "predit": [A("agneau", "VIANDE_ROUGE"), A("riz", "LEGUMINEUSE"), A("pain", "FECULENT")], "duree_ms": 10},
            {"texte": "2", "attendu": [A("lait", "LAITIER")], "predit": [], "duree_ms": 30, "erreur": "HTTP 429"},
        ])
        d = m["detection"]
        self.assertEqual((d["vrais_positifs"], d["faux_positifs"], d["faux_negatifs"]), (2, 1, 1))
        self.assertEqual((d["precision"], d["rappel"], d["f1"]), (0.667, 0.667, 0.667))
        self.assertEqual(m["categories"]["exactitude"], 0.5)                       # riz mal classé
        self.assertEqual(m["categories"]["confusion"]["FECULENT"]["LEGUMINEUSE"], 1)
        self.assertEqual(m["bout_en_bout"]["f1"], 0.333)
        self.assertEqual(m["phrases_parfaites"], 0.0)
        self.assertEqual(m["erreurs_api"], 1)
        self.assertEqual((m["latence_ms"]["p50"], m["latence_ms"]["p95"]), (10, 30))

    def test_centile(self):
        self.assertEqual(M.centile(list(range(1, 101)), 95), 95)
        self.assertIsNone(M.centile([], 50))

    def test_jeu_de_test_valide(self):
        jeu = M.charger_jeu()
        self.assertGreaterEqual(len(jeu), 40)
        for ph in jeu:
            self.assertTrue(ph["attendu"], ph["texte"])
            for a in ph["attendu"]:
                self.assertIn(a["categorie"], FACTEURS_CO2, ph["texte"])

    def test_moteur_local_sur_le_jeu_complet(self):
        m = M.evaluer("LOCAL")
        self.assertGreaterEqual(m["detection"]["f1"], 0.85)          # garde-fou : pas de régression du moteur local
        self.assertEqual(m["nb_phrases"], len(M.charger_jeu()))


@override_settings(IA_SYNCHRONE=True, GEMINI_PAUSE_S=0)
class PageLaboTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("adm", "adm@test.tn", MDP, role="ADMIN", email_verifie=True)
        cls.citoyen = Utilisateur.objects.create_user("cit", "cit@test.tn", MDP, email_verifie=True)
        cls.nutri = Utilisateur.objects.create_user("nut", "nut@test.tn", MDP, role="NUTRITIONNISTE", email_verifie=True)

    def test_acces_reserve_admin(self):
        for u in (self.citoyen, self.nutri):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("repas:labo")).status_code, 403)
            self.assertEqual(self.client.post(reverse("repas:labo"), {"moteur": "LOCAL"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("repas:labo")).status_code, 302)

    def test_evaluation_locale_et_affichage(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("repas:labo")), "Aucune évaluation")
        r = self.client.post(reverse("repas:labo"), {"moteur": "LOCAL"}, follow=True)
        ev = EvaluationIA.objects.get()
        self.assertEqual(ev.statut, "TERMINE")
        self.assertContains(r, "Matrice de confusion")
        self.assertContains(r, "Comparatif des moteurs")

    @override_settings(GEMINI_API_KEY="")
    def test_gemini_sans_cle(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("repas:labo"), {"moteur": "GEMINI"})
        self.assertFalse(EvaluationIA.objects.exists())

    @override_settings(GEMINI_API_KEY="cle-test", LABO_LIMITE_GEMINI=3)
    @mock.patch("repas.ia._appeler_gemini", return_value={"aliments": [{"aliment": "couscous", "categorie": "FECULENT"}]})
    def test_gemini_et_verdict(self, appel):
        self.client.force_login(self.admin)
        self.client.post(reverse("repas:labo"), {"moteur": "LOCAL"})
        self.client.post(reverse("repas:labo"), {"moteur": "GEMINI"})
        ev = EvaluationIA.objects.get(moteur="GEMINI")
        self.assertEqual((ev.statut, ev.nb_phrases, appel.call_count), ("TERMINE", 3, 3))
        self.assertContains(self.client.get(reverse("repas:labo")), "Verdict")

    def test_une_seule_evaluation_a_la_fois(self):
        EvaluationIA.objects.create(moteur="GEMINI")
        self.client.force_login(self.admin)
        self.client.post(reverse("repas:labo"), {"moteur": "LOCAL"})
        self.assertEqual(EvaluationIA.objects.count(), 1)

    def test_commande(self):
        sortie = StringIO()
        call_command("evaluer_repas_ia", "--moteur", "LOCAL", stdout=sortie)
        self.assertIn("F1=", sortie.getvalue())
        self.assertEqual(EvaluationIA.objects.filter(moteur="LOCAL", statut="TERMINE").count(), 1)
