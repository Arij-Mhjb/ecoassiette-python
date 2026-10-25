from unittest.mock import patch

from django.test import override_settings

from food_rescue.ai import analyser_avec_gemini, analyser_localement, analyser_surplus

from .base import FoodRescueTestCase


class IntelligenceFoodRescueTest(FoodRescueTestCase):
    def test_moteur_local_classe_un_plat(self):
        resultat = analyser_localement(self.creer_annonce())
        self.assertEqual(resultat["categorie"], "PLAT_PREPARE")
        self.assertEqual(resultat["source"], "LOCAL")
        self.assertIn(resultat["urgence"], ("FAIBLE", "MOYENNE", "ELEVEE", "CRITIQUE"))
        self.assertGreater(resultat["co2_evite_estime"], 0)

    def test_allergene_gluten_detecte(self):
        resultat = analyser_localement(self.creer_annonce())
        self.assertIn("gluten", resultat["allergenes_possibles"])

    @override_settings(GEMINI_API_KEY="cle-test")
    @patch("food_rescue.ai.generer")
    def test_reponse_gemini_validee(self, generer_mock):
        generer_mock.return_value = {
            "categorie": "PLAT_PREPARE", "allergenes_possibles": ["gluten"],
            "urgence": "ELEVEE", "confiance": 0.91, "co2_evite_estime": 4.5,
            "resume": "À récupérer rapidement.",
        }
        resultat = analyser_avec_gemini(self.creer_annonce())
        self.assertEqual(resultat["source"], "GEMINI")
        self.assertEqual(resultat["confiance"], 0.91)

    @patch("food_rescue.ai.analyser_avec_gemini")
    def test_repli_local_si_gemini_indisponible(self, gemini_mock):
        from users.ai import ErreurIA
        gemini_mock.side_effect = ErreurIA("quota")
        resultat = analyser_surplus(self.creer_annonce())
        self.assertEqual(resultat["source"], "LOCAL")
        self.assertIn("quota", resultat["erreur_gemini"])

