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
        r = self.client.get(reverse("users:export_donnees"), {"format": "json"})
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
        self.assertNotIn("secret de autre", self.client.get(reverse("users:export_donnees"), {"format": "json"}).content.decode())

    def test_export_pdf_par_defaut(self):
        Repas.objects.create(utilisateur=self.citoyen, type_repas="DINER", note="note-dans-le-pdf")
        self.client.force_login(self.citoyen)
        r = self.client.get(reverse("users:export_donnees"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn(".pdf", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertTrue(JournalAudit.objects.filter(action=A.EXPORT_DONNEES, details="format PDF").exists())

    def test_anonyme(self):
        self.assertEqual(self.client.get(reverse("users:export_donnees")).status_code, 302)


class JournalAuditTest(BaseTest):
    def test_actions_admin_journalisees(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_basculer", args=[self.autre.pk]))
        self.client.post(reverse("users:admin_supprimer", args=[self.autre.pk]))
        admin_seul = JournalAudit.CATEGORIES["administration"][1]
        actions = list(JournalAudit.objects.filter(action__in=admin_seul).order_by("cree_le")
                       .values_list("action", "acteur_nom", "cible"))
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


class ActiviteUtilisateursTest(BaseTest):
    """L'administrateur voit l'activité de TOUS les comptes, pas seulement les actions d'administration."""

    def _actions(self, **filtre):
        return list(JournalAudit.objects.filter(**filtre).values_list("action", flat=True))

    def test_connexion_echec_deconnexion(self):
        c = Client()
        c.post(reverse("users:login"), {"username": self.citoyen.username, "password": "mauvais"})
        c.post(reverse("users:login"), {"username": self.citoyen.username, "password": MDP})
        c.post(reverse("users:logout"))
        self.assertIn(A.CONNEXION_ECHOUEE, self._actions(cible=self.citoyen.username.lower()))
        self.assertIn(A.CONNEXION, self._actions(acteur=self.citoyen))
        self.assertIn(A.DECONNEXION, self._actions(acteur=self.citoyen))

    def test_activite_citoyen_journalisee(self):
        self.client.force_login(self.citoyen)
        self.client.post(reverse("users:password_change"), {
            "old_password": MDP, "new_password1": "Nouveau#Mdp2026", "new_password2": "Nouveau#Mdp2026"})
        r = Repas.objects.create(utilisateur=self.citoyen, type_repas="DINER")
        self.client.post(reverse("repas:supprimer", args=[r.pk]))
        actions = self._actions(acteur=self.citoyen)
        self.assertIn(A.MDP_MODIFIE, actions)
        self.assertIn(A.REPAS_SUPPRIME, actions)

    def test_filtre_par_utilisateur_et_type(self):
        JournalAudit.objects.create(acteur=self.citoyen, acteur_nom=self.citoyen.username, action=A.REPAS_AJOUTE, cible="repas n° 1")
        JournalAudit.objects.create(acteur=self.nutri, acteur_nom=self.nutri.username, action=A.PROFIL_MODIFIE, cible="zzz-nutri")
        self.client.force_login(self.admin)
        url = reverse("users:admin_journal")
        r = self.client.get(url, {"u": self.citoyen.username})
        self.assertContains(r, "repas n° 1")
        self.assertNotContains(r, "zzz-nutri")
        r = self.client.get(url, {"type": "connexions"})
        self.assertNotContains(r, "repas n° 1")
        r = self.client.get(url, {"role": "NUTRITIONNISTE"})
        self.assertContains(r, "zzz-nutri")
        self.assertNotContains(r, "repas n° 1")
        self.assertContains(self.client.get(url, {"u": "inconnu"}), "Aucun compte")

    def test_activite_sur_la_fiche_du_compte(self):
        JournalAudit.objects.create(acteur=self.citoyen, acteur_nom=self.citoyen.username, action=A.REPAS_AJOUTE, details="dîner test-fiche")
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:admin_detail", args=[self.citoyen.pk]))
        self.assertContains(r, "Activité récente")
        self.assertContains(r, "dîner test-fiche")
