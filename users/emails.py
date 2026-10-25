"""
E-mails transactionnels du module :
  - confirmation de l'adresse à l'inscription (lien unique, valable 24 h) ;
  - notification de changement de mot de passe ;
  - (la réinitialisation « mot de passe oublié » utilise les vues Django + nos templates).
"""
import logging

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


class ConfirmationEmailTokenGenerator(PasswordResetTokenGenerator):
    """Jeton signé (SECRET_KEY) qui devient invalide dès que l'e-mail est confirmé (usage unique)."""
    key_salt = "users.ConfirmationEmailTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.email_verifie}{timestamp}"


jeton_confirmation = ConfirmationEmailTokenGenerator()


def envoyer(sujet, gabarit, destinataire, contexte):
    """Envoie un e-mail texte + HTML. Retourne True/False (ne fait jamais planter la vue)."""
    texte = render_to_string(f"users/emails/{gabarit}.txt", contexte)
    html = render_to_string(f"users/emails/{gabarit}.html", contexte)
    msg = EmailMultiAlternatives(sujet, texte, to=[destinataire])
    msg.attach_alternative(html, "text/html")
    try:
        msg.send()
        return True
    except Exception as e:  # SMTP/HTTP indisponible : on journalise, l'utilisateur est prévenu
        logger.error("Envoi de l'e-mail « %s » à %s impossible : %s", sujet, destinataire, e)
        return False


def envoyer_confirmation(request, user):
    lien = request.build_absolute_uri(reverse("users:confirmer_email", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": jeton_confirmation.make_token(user),
    }))
    return envoyer("Confirmez votre adresse e-mail — EcoAssiette", "confirmation", user.email,
                   {"user": user, "lien": lien})


def notifier_changement_mdp(request, user):
    return envoyer("Votre mot de passe a été modifié — EcoAssiette", "mdp_modifie", user.email, {
        "user": user,
        "lien_reset": request.build_absolute_uri(reverse("users:password_reset")),
    })


# ------------------------------------------------------------- rôle nutritionniste
def lien_invitation(request, jeton):
    return request.build_absolute_uri(reverse("users:invitation_accepter", kwargs={"jeton": jeton}))


def envoyer_invitation(request, invitation, jeton):
    return envoyer("Invitation à rejoindre EcoAssiette en tant que nutritionniste", "invitation", invitation.email, {
        "inv": invitation, "lien": lien_invitation(request, jeton), "invite_par": invitation.invite_par,
    })


def notifier_admins_demande(request, demande):
    """Prévient chaque administrateur actif qu'une demande attend une validation."""
    from .models import Utilisateur
    lien = request.build_absolute_uri(reverse("users:admin_demandes"))
    admins = Utilisateur.objects.filter(role=Utilisateur.Role.ADMIN, is_active=True).exclude(email="")
    return sum(envoyer("Nouvelle demande de statut nutritionniste — EcoAssiette", "demande_recue", a.email,
                       {"admin": a, "d": demande, "lien": lien}) for a in admins)


def notifier_demande_traitee(request, demande):
    gabarit = "demande_acceptee" if demande.statut == demande.Statut.ACCEPTEE else "demande_refusee"
    sujet = ("Votre statut de nutritionniste est validé" if gabarit == "demande_acceptee"
             else "Votre demande de statut nutritionniste") + " — EcoAssiette"
    return envoyer(sujet, gabarit, demande.utilisateur.email, {
        "user": demande.utilisateur, "d": demande,
        "lien": request.build_absolute_uri(reverse("users:nutri_profils" if gabarit == "demande_acceptee" else "users:profil")),
    })


def notifier_recommandation(request, reco):
    return envoyer(f"Nouveau conseil de votre nutritionniste : {reco.titre} — EcoAssiette", "recommandation",
                   reco.citoyen.email, {"user": reco.citoyen, "r": reco,
                                        "lien": request.build_absolute_uri(reverse("users:mes_recommandations"))})
