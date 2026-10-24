"""E-mails : confirmation d'adresse, notification de changement de mot de passe, réinitialisation."""
import re
from unittest import mock

import requests
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from users.email_backends import BrevoBackend
from users.emails import jeton_confirmation
from users.models import Utilisateur

from .base import MDP, BaseTest
from .test_forms import donnees_inscription


def lien(message):
    return re.search(r"https?://testserver(/\S+)", message.body).group(1)


class ConfirmationEmailTest(BaseTest):
    def inscrire(self):
        return self.client.post(reverse("users:inscription"), donnees_inscription())

    def test_inscription_envoie_email_et_ne_connecte_pas(self):
        r = self.inscrire()
        self.assertRedirects(r, reverse("users:verification_envoyee"))
        self.assertNotIn("_auth_user_id", self.client.session)
        u = Utilisateur.objects.get(username="nouveau")
        self.assertFalse(u.email_verifie)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["nour@test.tn"])
        self.assertIn("Confirmez", mail.outbox[0].subject)
        self.assertIn("/comptes/confirmer/", mail.outbox[0].body)
        self.assertContains(self.client.get(r.url), "nour@test.tn")

    def test_connexion_bloquee_avant_confirmation(self):
        self.inscrire()
        r = self.client.post(reverse("users:login"), {"username": "nouveau", "password": MDP})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pas encore confirmée")
        self.assertContains(r, reverse("users:renvoyer_confirmation"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lien_confirme_connecte_et_usage_unique(self):
        self.inscrire()
        url = lien(mail.outbox[0])
        r = self.client.get(url)
        self.assertRedirects(r, reverse("users:modifier_profil"))
        self.assertTrue(Utilisateur.objects.get(username="nouveau").email_verifie)
        self.assertIn("_auth_user_id", self.client.session)
        # 2e clic : le jeton n'est plus valide, mais le compte est déjà confirmé
        self.client.logout()
        self.assertRedirects(self.client.get(url), reverse("users:login"))
        # connexion désormais possible
        r = self.client.post(reverse("users:login"), {"username": "nouveau", "password": MDP})
        self.assertEqual(r.status_code, 302)

    def test_lien_invalide(self):
        self.inscrire()
        u = Utilisateur.objects.get(username="nouveau")
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(u.pk))
        r = self.client.get(reverse("users:confirmer_email", args=[uid, "faux-jeton"]))
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Lien invalide", status_code=400)
        r = self.client.get(reverse("users:confirmer_email", args=["xx", "faux"]))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Utilisateur.objects.get(pk=u.pk).email_verifie)

    def test_jeton_lie_a_l_email(self):
        u = self.creer("z", Utilisateur.Role.CITOYEN)
        u.email_verifie = False
        u.save()
        t = jeton_confirmation.make_token(u)
        u.email = "change@test.tn"
        u.save()
        self.assertFalse(jeton_confirmation.check_token(u, t))

    def test_renvoyer_lien(self):
        self.inscrire()
        mail.outbox.clear()
        self.assertEqual(self.client.get(reverse("users:renvoyer_confirmation")).status_code, 200)
        r = self.client.post(reverse("users:renvoyer_confirmation"), {"email": "NOUR@test.tn"})
        self.assertRedirects(r, reverse("users:verification_envoyee"))
        self.assertEqual(len(mail.outbox), 1)

    def test_renvoyer_compte_inconnu_ou_deja_confirme(self):
        for email in ["inconnu@test.tn", "citoyen@test.tn"]:
            r = self.client.post(reverse("users:renvoyer_confirmation"), {"email": email}, follow=True)
            self.assertContains(r, "Si un compte non confirmé")
        self.assertEqual(len(mail.outbox), 0)

    @mock.patch("users.emails.EmailMultiAlternatives.send", side_effect=OSError("SMTP down"))
    def test_echec_envoi_ne_plante_pas(self, _):
        r = self.inscrire()
        self.assertRedirects(r, reverse("users:verification_envoyee"), fetch_redirect_response=False)
        r = self.client.get(r.url)
        self.assertContains(r, "n&#x27;a pas pu être envoyé")
        self.assertTrue(Utilisateur.objects.filter(username="nouveau").exists())

    def test_compte_cree_par_admin_deja_verifie(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:admin_creer"), {
            "username": "neo", "first_name": "N", "last_name": "N", "email": "neo@test.tn", "telephone": "",
            "role": "CITOYEN", "is_active": "on", "password1": "Tres!Solide2026", "password2": "Tres!Solide2026"})
        self.assertTrue(Utilisateur.objects.get(username="neo").email_verifie)

    def test_superuser_verifie(self):
        self.assertTrue(Utilisateur.objects.create_superuser("root", "root@test.tn", "x").email_verifie)


class NotificationMotDePasseTest(BaseTest):
    def test_changement_envoie_notification(self):
        self.client.force_login(self.citoyen)
        self.client.post(reverse("users:password_change"), {
            "old_password": MDP, "new_password1": "Nouveau!Mdp2026", "new_password2": "Nouveau!Mdp2026"})
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["citoyen@test.tn"])
        self.assertIn("mot de passe a été modifié", m.subject)
        self.assertIn("/comptes/mot-de-passe/oubli/", m.body)

    def test_reinitialisation_complete_avec_notification(self):
        self.client.post(reverse("users:password_reset"), {"email": "citoyen@test.tn"})
        url = lien(mail.outbox[0])
        r = self.client.get(url, follow=True)  # Django redirige vers .../set-password/
        self.assertEqual(r.status_code, 200)
        r = self.client.post(r.redirect_chain[-1][0],
                             {"new_password1": "Encore!Neuf2026", "new_password2": "Encore!Neuf2026"})
        self.assertRedirects(r, reverse("users:password_reset_complete"))
        self.citoyen.refresh_from_db()
        self.assertTrue(self.citoyen.check_password("Encore!Neuf2026"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("modifié", mail.outbox[1].subject)

    def test_reinitialisation_confirme_aussi_l_email(self):
        u = self.creer("pasconf", Utilisateur.Role.CITOYEN)
        Utilisateur.objects.filter(pk=u.pk).update(email_verifie=False)
        self.client.post(reverse("users:password_reset"), {"email": "pasconf@test.tn"})
        r = self.client.get(lien(mail.outbox[0]), follow=True)
        self.client.post(r.redirect_chain[-1][0], {"new_password1": "Encore!Neuf2026", "new_password2": "Encore!Neuf2026"})
        self.assertTrue(Utilisateur.objects.get(pk=u.pk).email_verifie)

    def test_email_inconnu_meme_reponse(self):
        r = self.client.post(reverse("users:password_reset"), {"email": "personne@test.tn"})
        self.assertRedirects(r, reverse("users:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


@override_settings(BREVO_API_KEY="cle-brevo", DEFAULT_FROM_EMAIL="EcoAssiette <eco@test.tn>",
                   EMAIL_BACKEND="users.email_backends.BrevoBackend")
class BrevoBackendTest(BaseTest):
    @mock.patch("users.email_backends.requests.post")
    def test_envoi_html(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("users:password_reset"), {"email": "citoyen@test.tn"})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["sender"], {"email": "eco@test.tn", "name": "EcoAssiette"})
        self.assertEqual(payload["to"], [{"email": "citoyen@test.tn"}])
        self.assertIn("htmlContent", payload)
        self.assertEqual(post.call_args.kwargs["headers"]["api-key"], "cle-brevo")

    @mock.patch("users.email_backends.requests.post", side_effect=requests.ConnectionError())
    def test_erreur(self, _):
        from django.core.mail import EmailMessage
        with self.assertRaises(requests.ConnectionError):
            BrevoBackend().send_messages([EmailMessage("s", "b", to=["a@b.tn"])])
        self.assertEqual(BrevoBackend(fail_silently=True).send_messages([EmailMessage("s", "b", to=["a@b.tn"])]), 0)


@override_settings(CONFIRMATION_EMAIL=False)
class SansConfirmationEmailTest(BaseTest):
    def test_inscription_active_directement(self):
        r = self.client.post(reverse("users:inscription"), donnees_inscription())
        self.assertRedirects(r, reverse("users:modifier_profil"))
        self.assertTrue(Utilisateur.objects.get(username="nouveau").email_verifie)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 0)
