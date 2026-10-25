"""Rôle nutritionniste : invitation par e-mail et demande validée par un administrateur."""
import re
from datetime import timedelta

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from users.models import DemandeNutritionniste, Invitation, Utilisateur

from .base import BaseTest

NOUVEAU_MDP = "Nutri-Secure-2026!"


def lien_du_mail(message):
    return re.search(r"https?://\S+/comptes/invitation/[\w-]+/", message.body).group(0)


class InvitationTest(BaseTest):
    def inviter(self, email="sarra@clinique.tn"):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("users:admin_invitations"),
                             {"email": email, "first_name": "Sarra", "last_name": "Ben Salah"})
        self.assertRedirects(r, reverse("users:admin_invitations"))
        self.client.logout()
        return Invitation.objects.get(email=email, statut=Invitation.Statut.EN_ATTENTE)

    def accepter(self, lien, username="sarra"):
        return self.client.post(lien, {"username": username, "first_name": "Sarra", "last_name": "Ben Salah",
                                       "password1": NOUVEAU_MDP, "password2": NOUVEAU_MDP})

    def test_invitation_envoie_un_lien_et_ne_stocke_que_son_empreinte(self):
        inv = self.inviter()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sarra@clinique.tn"])
        jeton = lien_du_mail(mail.outbox[0]).rstrip("/").rsplit("/", 1)[1]
        self.assertNotIn(jeton, inv.jeton_hash)          # le jeton en clair n'est pas en base
        self.assertEqual(len(inv.jeton_hash), 64)        # SHA-256

    def test_acceptation_cree_un_compte_nutritionniste(self):
        self.inviter()
        r = self.accepter(lien_du_mail(mail.outbox[0]))
        self.assertRedirects(r, reverse("users:nutri_profils"))
        u = Utilisateur.objects.get(username="sarra")
        self.assertEqual(u.role, Utilisateur.Role.NUTRITIONNISTE)
        self.assertEqual(u.email, "sarra@clinique.tn")
        self.assertTrue(u.email_verifie)
        self.assertTrue(u.has_perm("users.view_profilalimentaire"))   # groupe synchronisé
        inv = Invitation.objects.get(email="sarra@clinique.tn")
        self.assertEqual(inv.statut, Invitation.Statut.ACCEPTEE)
        self.assertEqual(inv.utilisateur, u)

    def test_lien_a_usage_unique(self):
        self.inviter()
        lien = lien_du_mail(mail.outbox[0])
        self.accepter(lien)
        self.client.logout()
        r = self.client.get(lien)
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "déjà été utilisée", status_code=400)

    def test_lien_expire(self):
        inv = self.inviter()
        Invitation.objects.filter(pk=inv.pk).update(expire_le=timezone.now() - timedelta(minutes=1))
        r = self.client.get(lien_du_mail(mail.outbox[0]))
        self.assertContains(r, "expiré", status_code=400)

    def test_lien_invente(self):
        r = self.client.get(reverse("users:invitation_accepter", args=["faux-jeton"]))
        self.assertEqual(r.status_code, 400)

    def test_annulation_rend_le_lien_inutilisable(self):
        inv = self.inviter()
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_invitation_annuler", args=[inv.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(lien_du_mail(mail.outbox[0])).status_code, 400)

    def test_renvoyer_invalide_l_ancien_lien(self):
        inv = self.inviter()
        ancien = lien_du_mail(mail.outbox[0])
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_invitation_renvoyer", args=[inv.pk]))
        self.client.logout()
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.client.get(ancien).status_code, 400)
        self.assertEqual(self.client.get(lien_du_mail(mail.outbox[1])).status_code, 200)

    def test_nouvelle_invitation_annule_la_precedente(self):
        self.inviter()
        self.inviter()
        self.assertEqual(Invitation.objects.filter(email="sarra@clinique.tn", statut="EN_ATTENTE").count(), 1)

    def test_email_deja_utilise_refuse(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("users:admin_invitations"), {"email": self.citoyen.email})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "existe déjà")
        self.assertFalse(Invitation.objects.exists())

    def test_utilisateur_connecte_doit_se_deconnecter(self):
        self.inviter()
        self.client.force_login(self.citoyen)
        r = self.client.get(lien_du_mail(mail.outbox[0]))
        self.assertContains(r, "Déconnectez-vous", status_code=400)

    def test_mot_de_passe_faible_refuse(self):
        self.inviter()
        r = self.client.post(lien_du_mail(mail.outbox[0]), {"username": "sarra", "first_name": "S", "last_name": "B",
                                                             "password1": "123", "password2": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Utilisateur.objects.filter(username="sarra").exists())

    def test_seul_l_admin_peut_inviter(self):
        for u in (self.citoyen, self.nutri):
            self.client.force_login(u)
            with self.subTest(role=u.role):
                self.assertEqual(self.client.get(reverse("users:admin_invitations")).status_code, 403)
                self.assertEqual(self.client.post(reverse("users:admin_invitations"), {"email": "x@y.tn"}).status_code, 403)
        self.assertFalse(Invitation.objects.exists())

    def test_lien_affiche_une_seule_fois(self):
        self.inviter()
        self.client.force_login(self.admin)
        lien = lien_du_mail(mail.outbox[0])
        # la page d'après l'envoi a déjà consommé le lien : il n'est plus affiché ensuite
        self.assertNotContains(self.client.get(reverse("users:admin_invitations")), lien)


class DemandeInscriptionTest(BaseTest):
    def donnees(self, **kw):
        d = {"type_compte": "NUTRITIONNISTE", "username": "leila", "first_name": "Leïla", "last_name": "Haddad",
             "email": "leila@test.tn", "password1": NOUVEAU_MDP, "password2": NOUVEAU_MDP, "regime": "FLEXITARIEN",
             "consentement": "on", "numero_ordre": "DN-2019-0457", "etablissement": "Cabinet, Tunis"}
        d.update(kw)
        return d

    def test_inscription_nutritionniste_reste_citoyen_en_attente(self):
        r = self.client.post(reverse("users:inscription"), self.donnees())
        self.assertEqual(r.status_code, 302)
        u = Utilisateur.objects.get(username="leila")
        self.assertEqual(u.role, Utilisateur.Role.CITOYEN)            # pas d'auto-attribution du rôle
        self.assertFalse(u.has_perm("users.view_profilalimentaire"))
        d = u.demandes_nutritionniste.get()
        self.assertEqual(d.statut, DemandeNutritionniste.Statut.EN_ATTENTE)
        sujets = [m.subject for m in mail.outbox]
        self.assertTrue(any("Nouvelle demande" in s for s in sujets))   # l'admin est prévenu
        self.assertIn(self.admin.email, [m.to[0] for m in mail.outbox])

    def test_numero_ordre_obligatoire_pour_un_nutritionniste(self):
        r = self.client.post(reverse("users:inscription"), self.donnees(numero_ordre="", etablissement=""))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Obligatoire pour une demande")
        self.assertFalse(Utilisateur.objects.filter(username="leila").exists())

    def test_inscription_citoyen_sans_demande(self):
        self.client.post(reverse("users:inscription"), self.donnees(type_compte="CITOYEN", numero_ordre=""))
        u = Utilisateur.objects.get(username="leila")
        self.assertFalse(u.demandes_nutritionniste.exists())

    def test_impossible_de_forcer_le_role(self):
        self.client.post(reverse("users:inscription"), self.donnees(type_compte="ADMIN", role="ADMIN"))
        self.assertFalse(Utilisateur.objects.filter(username="leila").exists())   # choix invalide


class ValidationDemandeTest(BaseTest):
    def setUp(self):
        self.demande = DemandeNutritionniste.objects.create(
            utilisateur=self.citoyen, numero_ordre="DN-1234", etablissement="Hôpital Charles-Nicolle")

    def test_admin_valide_la_demande(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("users:admin_demandes"))
        self.assertContains(r, "DN-1234")
        self.assertContains(r, 'class="pastille"')
        self.client.post(reverse("users:admin_demande_accepter", args=[self.demande.pk]))
        self.citoyen.refresh_from_db()
        self.demande.refresh_from_db()
        self.assertEqual(self.citoyen.role, Utilisateur.Role.NUTRITIONNISTE)
        self.assertEqual(self.demande.statut, DemandeNutritionniste.Statut.ACCEPTEE)
        self.assertEqual(self.demande.traitee_par, self.admin)
        self.assertTrue(Utilisateur.objects.get(pk=self.citoyen.pk).has_perm("users.view_profilalimentaire"))
        self.assertEqual(mail.outbox[-1].to, [self.citoyen.email])
        self.assertIn("validé", mail.outbox[-1].subject)

    def test_admin_refuse_avec_motif(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_demande_refuser", args=[self.demande.pk]), {"motif": "Numéro introuvable"})
        self.citoyen.refresh_from_db()
        self.demande.refresh_from_db()
        self.assertEqual(self.citoyen.role, Utilisateur.Role.CITOYEN)
        self.assertEqual(self.demande.statut, DemandeNutritionniste.Statut.REFUSEE)
        self.assertIn("Numéro introuvable", mail.outbox[-1].body)

    def test_refus_sans_motif_impossible(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_demande_refuser", args=[self.demande.pk]), {"motif": ""})
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, DemandeNutritionniste.Statut.EN_ATTENTE)

    def test_demande_deja_traitee(self):
        self.client.force_login(self.admin)
        url = reverse("users:admin_demande_accepter", args=[self.demande.pk])
        self.client.post(url)
        n = len(mail.outbox)
        self.client.post(url)
        self.assertEqual(len(mail.outbox), n)     # pas de second e-mail

    def test_get_interdit_sur_les_actions(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("users:admin_demande_accepter", args=[self.demande.pk])).status_code, 405)

    def test_non_admin_ne_peut_pas_valider(self):
        for u in (self.citoyen, self.nutri):
            self.client.force_login(u)
            with self.subTest(role=u.role):
                self.assertEqual(self.client.post(reverse("users:admin_demande_accepter", args=[self.demande.pk])).status_code, 403)
                self.assertEqual(self.client.get(reverse("users:admin_demandes")).status_code, 403)
        self.citoyen.refresh_from_db()
        self.assertEqual(self.citoyen.role, Utilisateur.Role.CITOYEN)

    def test_bandeau_sur_le_profil(self):
        self.client.force_login(self.citoyen)
        self.assertContains(self.client.get(reverse("users:profil")), "en cours d'examen")


class DemandeDepuisProfilTest(BaseTest):
    def test_citoyen_fait_une_demande(self):
        self.client.force_login(self.autre)
        r = self.client.post(reverse("users:demande_nutritionniste"),
                             {"numero_ordre": "DN-777", "etablissement": "Cabinet Sousse", "message": ""})
        self.assertRedirects(r, reverse("users:profil"))
        self.assertTrue(self.autre.demandes_nutritionniste.filter(statut="EN_ATTENTE").exists())

    def test_une_seule_demande_en_attente(self):
        DemandeNutritionniste.objects.create(utilisateur=self.autre, numero_ordre="DN-1", etablissement="X")
        self.client.force_login(self.autre)
        r = self.client.post(reverse("users:demande_nutritionniste"), {"numero_ordre": "DN-2", "etablissement": "Y"})
        self.assertRedirects(r, reverse("users:profil"))
        self.assertEqual(self.autre.demandes_nutritionniste.count(), 1)

    def test_nutritionniste_ne_redemande_pas(self):
        self.client.force_login(self.nutri)
        self.assertRedirects(self.client.get(reverse("users:demande_nutritionniste")), reverse("users:profil"))

    def test_numero_ordre_invalide(self):
        self.client.force_login(self.autre)
        r = self.client.post(reverse("users:demande_nutritionniste"), {"numero_ordre": "<script>", "etablissement": "Y"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.autre.demandes_nutritionniste.exists())

    def test_anonyme_redirige(self):
        self.assertEqual(self.client.get(reverse("users:demande_nutritionniste")).status_code, 302)
