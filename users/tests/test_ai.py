"""Tests de la logique IA : moteur local, validation des réponses Gemini, gestion d'erreurs (API simulée)."""
import json
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import override_settings

from users import ai, tasks
from users.models import AnalyseProfilIA

from .base import BaseTest


def reponse_gemini(payload, status=200):
    m = mock.Mock(status_code=status)
    m.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    m.raise_for_status.side_effect = None if status < 400 else requests.HTTPError("err")
    return m


BONNE = {
    "resume": "Bon profil. Peut mieux faire.",
    "objectif_recommande_kg": 30,
    "conseils": ["Mangez des lentilles.", "Achetez local.", "Cuisinez en grande quantité."],
    "alternatives": [
        {"aliment": "burger", "remplacement": "burger de haricots", "idee": "avec betterave"},
        {"aliment": "poulet", "remplacement": "poulet", "idee": "rejeté car animal"},
        {"aliment": "lait", "remplacement": "lait d'avoine", "idee": "ok car végétal"},
        {"aliment": "x", "remplacement": "aubergines rôties", "idee": "rejeté car évité"},
    ],
}


class MoteurLocalTest(BaseTest):
    def setUp(self):
        p = self.citoyen.profil
        p.regime, p.aliments_aimes, p.aliments_evites = "OMNIVORE_FORT", "couscous à l'agneau, burger", "lentilles"
        p.taille_foyer, p.temps_cuisine = 4, "RAPIDE"
        self.d = ai.donnees_profil(p)

    def test_alternatives_partent_des_gouts_et_respectent_evites(self):
        r = ai.analyse_locale(self.d)
        self.assertEqual(r["alternatives"][0]["aliment"], "couscous à l'agneau")
        self.assertEqual(r["alternatives"][0]["remplacement"], "pois chiches")
        for a in r["alternatives"]:
            self.assertNotIn("lentilles", a["remplacement"] + a["idee"].lower())
        self.assertGreater(r["alternatives"][0]["economie_kg_par_kg"], 30)

    def test_objectif_et_score(self):
        r = ai.analyse_locale(self.d)
        self.assertLess(r["objectif_recommande_kg"], r["empreinte_estimee_kg"])
        self.assertEqual(r["score_durabilite"], 0)
        self.assertEqual(ai.score_durabilite("VEGAN"), 100)
        self.assertGreaterEqual(ai.objectif_recommande("VEGAN"), 5)
        self.assertTrue(any("foyer de 4" in c for c in r["conseils"]))

    def test_vegan_sans_alternative(self):
        self.d.update(regime="VEGAN", aliments_aimes=[], temps_cuisine="20 à 45 min")
        self.assertEqual(ai.analyse_locale(self.d)["alternatives"], [])


class GeminiTest(BaseTest):
    def setUp(self):
        p = self.citoyen.profil
        p.regime, p.aliments_aimes, p.aliments_evites = "OMNIVORE", "burger, poulet", "aubergines"
        self.p = p
        self.d = ai.donnees_profil(p)

    def test_prompt_contient_contraintes(self):
        prompt = ai.construire_prompt(self.d)
        self.assertIn("aliments_evites", prompt)
        self.assertIn("UNIQUEMENT en JSON", prompt)

    def test_sans_cle(self):
        with self.assertRaises(ai.ErreurIA):
            ai.appeler_gemini("x")

    @override_settings(GEMINI_API_KEY="cle-test")
    @mock.patch("users.ai.requests.post")
    def test_succes_et_filtrage(self, post):
        post.return_value = reponse_gemini(BONNE)
        r, source, erreur, duree = ai.analyser(self.p)
        self.assertEqual(source, "GEMINI")
        self.assertEqual(erreur, "")
        rempl = [a["remplacement"] for a in r["alternatives"]]
        self.assertEqual(rempl, ["burger de haricots", "lait d'avoine"])
        self.assertEqual(r["objectif_recommande_kg"], 30.0)
        # la clé passe par un en-tête, jamais dans l'URL
        self.assertNotIn("cle-test", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "cle-test")

    @override_settings(GEMINI_API_KEY="cle-test")
    @mock.patch("users.ai.requests.post")
    def test_objectif_borne(self, post):
        post.return_value = reponse_gemini({**BONNE, "objectif_recommande_kg": 500})
        r, *_ = ai.analyser(self.p)
        self.assertEqual(r["objectif_recommande_kg"], self.d["empreinte_estimee_kg"])

    @override_settings(GEMINI_API_KEY="cle-test")
    @mock.patch("users.ai.requests.post")
    def test_repli_sur_erreurs(self, post):
        cas = {
            "timeout": requests.Timeout(),
            "reseau": requests.ConnectionError(),
            "http": None,
            "illisible": None,
            "incomplet": None,
            "non_dict": None,
            "sans_alt": None,
        }
        for nom, exc in cas.items():
            with self.subTest(cas=nom):
                post.reset_mock(side_effect=True, return_value=True)
                if exc:
                    post.side_effect = exc
                elif nom == "http":
                    post.return_value = reponse_gemini({}, status=429)
                elif nom == "illisible":
                    m = mock.Mock()
                    m.raise_for_status.return_value = None
                    m.json.return_value = {"candidates": []}
                    post.return_value = m
                elif nom == "incomplet":
                    post.return_value = reponse_gemini({"resume": "x"})
                elif nom == "non_dict":
                    post.return_value = reponse_gemini(["liste"])
                else:
                    post.return_value = reponse_gemini({**BONNE, "alternatives": [{"remplacement": "boeuf"}]})
                r, source, erreur, _ = ai.analyser(self.p)
                self.assertEqual(source, "LOCAL")
                self.assertTrue(erreur)
                self.assertIn("conseils", r)

    def test_valider_resume_vide(self):
        with self.assertRaises(ai.ErreurIA):
            ai.valider_resultat({**BONNE, "resume": " "}, self.d)


class TacheAsynchroneTest(BaseTest):
    def test_execution_terminee(self):
        a = tasks.lancer_analyse(self.citoyen.profil)
        self.assertEqual(a.statut, AnalyseProfilIA.Statut.TERMINE)
        self.assertEqual(a.source, "LOCAL")
        self.assertIsNotNone(a.duree_ms)
        self.assertTrue(a.est_terminee)
        self.assertIn("Analyse", str(a))

    @mock.patch("users.tasks.ai.analyser", side_effect=RuntimeError("boom"))
    def test_exception_marque_echec(self, _):
        a = tasks.lancer_analyse(self.citoyen.profil)
        self.assertEqual(a.statut, AnalyseProfilIA.Statut.ECHEC)
        self.assertIn("RuntimeError", a.erreur)

    def test_analyse_introuvable(self):
        tasks.executer_analyse(999999)  # ne lève pas

    def test_tache_celery_appelable(self):
        a = AnalyseProfilIA.objects.create(profil=self.citoyen.profil)
        tasks.analyser_profil_task(a.pk)  # exécution directe (sans worker)
        a.refresh_from_db()
        self.assertEqual(a.statut, "TERMINE")


class CommandesTest(BaseTest):
    def test_evaluer_ia_local(self):
        out = StringIO()
        call_command("evaluer_ia", "--local", stdout=out)
        txt = out.getvalue()
        self.assertIn("respect_aliments_evites", txt)
        self.assertIn("1.0", txt)

    def test_evaluer_ia_json(self):
        import os
        import tempfile
        chemin = os.path.join(tempfile.mkdtemp(), "r.json")
        call_command("evaluer_ia", "--json", chemin, stdout=StringIO())  # sans clé -> repli local
        with open(chemin, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["respect_aliments_evites"], 1.0)
        self.assertEqual(r["alternatives_100pct_vegetales"], 1.0)

    def test_seed_demo_idempotent(self):
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())
        from users.models import Utilisateur
        self.assertTrue(Utilisateur.objects.filter(username="admin_eco", role="ADMIN").exists())
