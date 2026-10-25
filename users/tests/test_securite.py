"""Recommandations, sécurité de connexion (anti brute-force, historique, sessions), export RGPD, journal d'audit."""
import json

from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client
from django.urls import reverse

from repas.models import ElementRepas, Repas
from users.models import HistoriqueConnexion, JournalAudit, Recommandation, Utilisateur

from .base import MDP, BaseTest

A = JournalAudit.Action


class RecommandationTest(BaseTest):
    def url(self):
        return reverse("users:nutri_profil_detail", args=[self.citoyen.profil.pk])

    def ecrire(self, **kw):
        d = {"theme": "ALIMENTATION", "titre": "Moins de viande rouge", "contenu": "Essayez le lablabi le mardi."}
        d.update(kw)
        return self.client.post(self.url(), d)

    def test_nutritionniste_envoie_un_conseil(self):
        self.client.force_login(self.nutri)
        self.assertContains(self.client.get(self.url()), "Envoyer la recommandation")
        r = self.ecrire()
        self.assertRedirects(r, self.url())
        reco = Recommandation.objects.get()
        self.assertEqual((reco.auteur, reco.citoyen), (self.nutri, self.citoyen))
        self.assertEqual(mail.outbox[-1].to, [self.citoyen.email])
        self.assertIn("Moins de viande rouge", mail.outbox[-1].subject)
        self.assertTrue(JournalAudit.objects.filter(action=A.RECOMMANDATION, acteur=self.nutri).exists())

    def test_champs_obligatoires(self):
        self.client.force_login(self.nutri)
        r = self.ecrire(titre="", contenu="")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Recommandation.objects.exists())

    def test_profil_non_partage_inaccessible(self):
        self.citoyen.profil.profil_public = False
        self.citoyen.profil.save()
        self.client.force_login(self.nutri)
        self.assertEqual(self.ecrire().status_code, 404)

    def test_seul_le_nutritionniste_ecrit(self):
        self.client.force_login(self.admin)               # l'admin voit la fiche mais n'écrit pas
        self.assertNotContains(self.client.get(self.url()), "Envoyer la recommandation")
        self.assertEqual(self.ecrire().status_code, 403)
        self.client.force_login(self.autre)
        self.assertEqual(self.ecrire().status_code, 403)
        self.assertFalse(Recommandation.objects.exists())

    def test_citoyen_lit_et_donne_son_avis(self):
        reco = Recommandation.objects.create(auteur=self.nutri, citoyen=self.citoyen, titre="T", contenu="C")
        self.client.force_login(self.citoyen)
        self.assertContains(self.client.get(reverse("users:profil")), "nouveau conseil")
        r = self.client.get(reverse("users:mes_recommandations"))
        self.assertContains(r, "Nouveau")
        reco.refresh_from_db()
        self.assertIsNotNone(reco.lue_le)
        self.client.post(reverse("users:avis_recommandation", args=[reco.pk]), {"avis": "UTILE"})
        reco.refresh_from_db()
        self.assertEqual(reco.avis, "UTILE")

    def test_avis_sur_le_conseil_d_un_autre_impossible(self):
        reco = Recommandation.objects.create(auteur=self.nutri, citoyen=self.autre, titre="T", contenu="C")
        self.client.force_login(self.citoyen)
        r = self.client.post(reverse("users:avis_recommandation", args=[reco.pk]), {"avis": "UTILE"})
        self.assertEqual(r.status_code, 404)

    def test_pastille_non_lus_dans_le_menu(self):
        Recommandation.objects.create(auteur=self.nutri, citoyen=self.citoyen, titre="T", contenu="C")
        self.client.force_login(self.citoyen)
        self.assertEqual(self.client.get(reverse("users:profil")).context["nb_recos_non_lues"], 1)


class BruteForceTest(BaseTest):
    def tenter(self, mdp="mauvais", identifiant="citoyen"):
        return self.client.post(reverse("users:login"), {"username": identifiant, "password": mdp})

    def test_blocage_apres_5_echecs_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(5):
            self.assertContains(self.tenter(), "Identifiants incorrects")
        r = self.tenter(MDP)
        self.assertContains(r, "Trop de tentatives")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(JournalAudit.objects.filter(action=A.CONNEXION_BLOQUEE, cible="citoyen").exists())

    def test_blocage_par_email_aussi(self):
        for _ in range(5):
            self.tenter(identifiant="CITOYEN@test.tn")
        self.assertContains(self.tenter(MDP, identifiant="citoyen@test.tn"), "Trop de tentatives")

    def test_4_echecs_puis_succes_remet_a_zero(self):
        for _ in range(4):
            self.tenter()
        self.assertEqual(self.tenter(MDP).status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.tenter()
        self.assertEqual(self.tenter(MDP).status_code, 302)     # 4 nouveaux échecs seulement

    def test_les_autres_comptes_ne_sont_pas_bloques(self):
        for _ in range(5):
            self.tenter()
        self.assertEqual(self.tenter(MDP, identifiant="autre").status_code, 302)

    def test_historique_enregistre(self):
        self.tenter()
        self.tenter(MDP)
        h = list(HistoriqueConnexion.objects.filter(utilisateur=self.citoyen).order_by("cree_le"))
        self.assertEqual([c.succes for c in h], [False, True])
        self.assertTrue(all(c.ip.endswith("x.x") for c in h))       # IP masquée


class SessionsTest(BaseTest):
    def test_deconnecter_les_autres_appareils(self):
        pc, tel = Client(), Client()
        for c in (pc, tel):
            c.post(reverse("users:login"), {"username": "citoyen", "password": MDP})
        self.assertEqual(Session.objects.count(), 2)
        r = pc.post(reverse("users:deconnexion_globale"))
        self.assertRedirects(r, reverse("users:securite"))
        self.assertEqual(pc.get(reverse("users:profil")).status_code, 200)     # cet appareil reste connecté
        self.assertEqual(tel.get(reverse("users:profil")).status_code, 302)    # l'autre est déconnecté
        self.assertTrue(JournalAudit.objects.filter(action=A.DECONNEXION_GLOBALE).exists())

    def test_page_securite(self):
        self.client.post(reverse("users:login"), {"username": "citoyen", "password": "faux"})
        self.client.post(reverse("users:login"), {"username": "citoyen", "password": MDP})
        r = self.client.get(reverse("users:securite"))
        self.assertContains(r, "Échouée")
        self.assertContains(r, "cet appareil")

    def test_get_interdit(self):
        self.client.force_login(self.citoyen)
        self.assertEqual(self.client.get(reverse("users:deconnexion_globale")).status_code, 405)


class ExportRGPDTest(BaseTest):
    def test_export_complet(self):
        repas = Repas.objects.create(utilisateur=self.citoyen, type_repas="DINER")
        ElementRepas.objects.create(repas=repas, aliment="couscous", categorie="FECULENT", quantite_g=300)
        Recommandation.objects.create(auteur=self.nutri, citoyen=self.citoyen, titre="T", contenu="C")
        self.client.force_login(self.citoyen)
        r = self.client.get(reverse("users:export_donnees"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        d = json.loads(r.content)
        self.assertEqual(d["compte"]["email"], self.citoyen.email)
        self.assertEqual(d["repas"][0]["aliments"][0]["aliment"], "couscous")
        self.assertEqual(len(d["recommandations_recues"]), 1)
        self.assertNotIn("password", r.content.decode())          # jamais le hash du mot de passe
        self.assertTrue(JournalAudit.objects.filter(action=A.EXPORT_DONNEES, acteur=self.citoyen).exists())

    def test_seulement_mes_donnees(self):
        Repas.objects.create(utilisateur=self.autre, type_repas="DINER", note="secret de autre")
        self.client.force_login(self.citoyen)
        self.assertNotIn("secret de autre", self.client.get(reverse("users:export_donnees")).content.decode())

    def test_anonyme(self):
        self.assertEqual(self.client.get(reverse("users:export_donnees")).status_code, 302)


class JournalAuditTest(BaseTest):
    def test_actions_admin_journalisees(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_basculer", args=[self.autre.pk]))
        self.client.post(reverse("users:admin_supprimer", args=[self.autre.pk]))
        actions = list(JournalAudit.objects.order_by("cree_le").values_list("action", "acteur_nom", "cible"))
        self.assertEqual(actions, [(A.COMPTE_DESACTIVE, "admin1", "autre"), (A.COMPTE_SUPPRIME, "admin1", "autre")])

    def test_suppression_par_le_titulaire(self):
        self.client.force_login(self.autre)
        self.client.post(reverse("users:supprimer_compte"), {"password": MDP})
        e = JournalAudit.objects.get(action=A.SUPPRESSION_PAR_UTILISATEUR)
        self.assertEqual(e.acteur_nom, "autre")          # le nom reste même si le compte n'existe plus
        self.assertIsNone(e.acteur)

    def test_page_reservee_admin(self):
        JournalAudit.objects.create(acteur_nom="x", action=A.COMPTE_CREE, cible="zorro")
        for u in (self.citoyen, self.nutri):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("users:admin_journal")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:admin_journal"), {"action": "COMPTE_CREE", "q": "zorro"})
        self.assertContains(r, "zorro")

    def test_journal_inalterable_dans_admin_django(self):
        e = JournalAudit.objects.create(acteur_nom="x", action=A.COMPTE_CREE)
        root = Utilisateur.objects.create_superuser("root", "root@test.tn", MDP)
        self.client.force_login(root)
        self.assertEqual(self.client.post(f"/admin/users/journalaudit/{e.pk}/delete/", {"post": "yes"}).status_code, 403)
        self.assertTrue(JournalAudit.objects.filter(pk=e.pk).exists())
