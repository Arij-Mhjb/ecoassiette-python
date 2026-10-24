"""Tests d'intégration des vues (Client Django) : statuts HTTP, redirections, données."""
from django.core import mail
from django.urls import reverse

from users.models import AnalyseProfilIA, Utilisateur

from .base import MDP, BaseTest
from .test_forms import donnees_inscription


class AuthViewsTest(BaseTest):
    def test_pages_publiques(self):
        for nom in ["home", "users:login", "users:inscription", "users:password_reset"]:
            with self.subTest(nom=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)

    def test_inscription_si_deja_connecte(self):
        self.client.force_login(self.citoyen)
        self.assertRedirects(self.client.get(reverse("users:inscription")), reverse("users:profil"))

    def test_connexion_par_email(self):
        r = self.client.post(reverse("users:login"), {"username": "CITOYEN@test.tn", "password": MDP})
        self.assertRedirects(r, reverse("users:profil"))

    def test_connexion_par_username(self):
        r = self.client.post(reverse("users:login"), {"username": "citoyen", "password": MDP})
        self.assertEqual(r.status_code, 302)

    def test_connexion_echouee(self):
        r = self.client.post(reverse("users:login"), {"username": "citoyen", "password": "faux"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Identifiants incorrects")
        r = self.client.post(reverse("users:login"), {"username": "inconnu@x.tn", "password": "faux"})
        self.assertContains(r, "Identifiants incorrects")

    def test_compte_desactive_ne_peut_pas_se_connecter(self):
        self.autre.is_active = False
        self.autre.save()
        r = self.client.post(reverse("users:login"), {"username": "autre", "password": MDP})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deconnexion_post(self):
        self.client.force_login(self.citoyen)
        self.assertRedirects(self.client.post(reverse("users:logout")), reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_reinitialisation_mot_de_passe_envoie_email(self):
        r = self.client.post(reverse("users:password_reset"), {"email": "citoyen@test.tn"})
        self.assertRedirects(r, reverse("users:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/reinitialiser/", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")

    def test_changement_mot_de_passe(self):
        self.client.force_login(self.citoyen)
        r = self.client.post(reverse("users:password_change"), {
            "old_password": MDP, "new_password1": "Nouveau!Mdp2026", "new_password2": "Nouveau!Mdp2026"})
        self.assertRedirects(r, reverse("users:profil"))
        self.citoyen.refresh_from_db()
        self.assertTrue(self.citoyen.check_password("Nouveau!Mdp2026"))


class EspaceCitoyenTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.citoyen)

    def test_profil_affiche(self):
        r = self.client.get(reverse("users:profil"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Mon empreinte alimentaire")
        self.assertContains(r, "<main", html=False)

    def test_modifier_profil_valide(self):
        r = self.client.post(reverse("users:modifier_profil"), {
            "regime": "VEGETARIEN", "aliments_aimes": "pâtes", "aliments_evites": "", "taille_foyer": 2,
            "niveau_activite": "MODERE", "temps_cuisine": "RAPIDE", "ville": "Tunis", "objectif_co2_hebdo": "20",
            "profil_public": "on"})
        self.assertRedirects(r, reverse("users:profil"))
        self.citoyen.profil.refresh_from_db()
        self.assertEqual(self.citoyen.profil.regime, "VEGETARIEN")

    def test_modifier_profil_invalide(self):
        r = self.client.post(reverse("users:modifier_profil"), {
            "regime": "VEGAN", "taille_foyer": 99, "niveau_activite": "MODERE", "temps_cuisine": "RAPIDE"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'aria-invalid="true"')

    def test_modifier_infos(self):
        r = self.client.post(reverse("users:modifier_infos"), {
            "first_name": "Ali", "last_name": "B", "email": "ali@test.tn", "telephone": "+216 22 333 444"})
        self.assertRedirects(r, reverse("users:profil"))
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.first_name, "Ali")

    def test_modifier_infos_invalide(self):
        r = self.client.post(reverse("users:modifier_infos"), {"first_name": "Ali", "email": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Le formulaire contient des erreurs")

    def test_supprimer_compte(self):
        r = self.client.post(reverse("users:supprimer_compte"), {"password": MDP})
        self.assertRedirects(r, reverse("home"))
        self.assertFalse(Utilisateur.objects.filter(pk=self.citoyen.pk).exists())

    def test_supprimer_compte_mauvais_mdp(self):
        r = self.client.post(reverse("users:supprimer_compte"), {"password": "faux"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Utilisateur.objects.filter(pk=self.citoyen.pk).exists())


class AnalyseIAViewsTest(BaseTest):
    def setUp(self):
        self.client.force_login(self.citoyen)

    def test_lancer_analyse_retourne_202_et_resultat(self):
        r = self.client.post(reverse("users:analyse_lancer"))
        self.assertEqual(r.status_code, 202)
        data = r.json()
        self.assertTrue(data["termine"])
        self.assertEqual(data["source"], "LOCAL")  # pas de clé en test -> repli
        self.assertIn("objectif_recommande_kg", data["resultat"])

    def test_lancer_analyse_get_interdit(self):
        self.assertEqual(self.client.get(reverse("users:analyse_lancer")).status_code, 405)

    def test_etat_analyse_proprietaire_uniquement(self):
        a = AnalyseProfilIA.objects.create(profil=self.autre.profil)
        self.assertEqual(self.client.get(reverse("users:analyse_etat", args=[a.pk])).status_code, 404)

    def test_etat_analyse(self):
        a = AnalyseProfilIA.objects.create(profil=self.citoyen.profil)
        r = self.client.get(reverse("users:analyse_etat", args=[a.pk]))
        self.assertEqual(r.json()["statut"], "EN_ATTENTE")
        self.assertFalse(r.json()["termine"])

    def test_analyse_en_cours_reutilisee(self):
        a = AnalyseProfilIA.objects.create(profil=self.citoyen.profil, statut="EN_COURS")
        r = self.client.post(reverse("users:analyse_lancer"))
        self.assertEqual(r.json()["id"], a.pk)

    def test_echec_message(self):
        a = AnalyseProfilIA.objects.create(profil=self.citoyen.profil, statut="ECHEC")
        self.assertIn("échoué", self.client.get(reverse("users:analyse_etat", args=[a.pk])).json()["erreur"])

    def test_appliquer_objectif(self):
        self.client.post(reverse("users:analyse_lancer"))
        a = AnalyseProfilIA.objects.get(profil=self.citoyen.profil)
        r = self.client.post(reverse("users:appliquer_objectif", args=[a.pk]))
        self.assertRedirects(r, reverse("users:profil"))
        self.citoyen.profil.refresh_from_db()
        self.assertEqual(float(self.citoyen.profil.objectif_co2_hebdo), a.resultat["objectif_recommande_kg"])

    def test_appliquer_objectif_incoherent(self):
        a = AnalyseProfilIA.objects.create(profil=self.citoyen.profil, statut="TERMINE",
                                           resultat={"objectif_recommande_kg": 999})
        r = self.client.post(reverse("users:appliquer_objectif", args=[a.pk]), follow=True)
        self.assertContains(r, "Impossible d&#x27;appliquer")

    def test_profil_affiche_derniere_analyse(self):
        self.client.post(reverse("users:analyse_lancer"))
        r = self.client.get(reverse("users:profil"))
        self.assertContains(r, "Alternatives végétales pour vous")
        self.assertContains(r, "Relancer l'analyse")


class PagesErreurTest(BaseTest):
    def test_404_personnalisee(self):
        r = self.client.get("/page-qui-n-existe-pas/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page introuvable", status_code=404)

    def test_handlers_directs(self):
        from django.test import RequestFactory

        from users import views
        req = RequestFactory().get("/")
        from django.contrib.auth.models import AnonymousUser
        req.user = AnonymousUser()
        self.assertEqual(views.erreur_500(req).status_code, 500)
        self.assertEqual(views.erreur_403(req).status_code, 403)
