"""
Sécurité du module utilisateurs :
  - journal d'audit (journaliser) ;
  - anti brute-force : 5 échecs en 15 minutes sur un même identifiant -> connexion bloquée 15 minutes ;
  - historique des connexions (IP masquée, navigateur) et déconnexion de tous les appareils.
"""
import re
from datetime import timedelta

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.sessions.models import Session
from django.dispatch import receiver
from django.utils import timezone

from .models import HistoriqueConnexion, JournalAudit, Utilisateur

MAX_ECHECS = 5
FENETRE = timedelta(minutes=15)


# ----------------------------------------------------------------------------- utilitaires
def ip_client(request):
    if request is None:
        return ""
    ip = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    return ip[:45]


def masquer_ip(ip):
    """Minimisation RGPD : 197.15.42.8 -> 197.15.x.x ; IPv6 -> 4 premiers blocs."""
    if not ip:
        return ""
    if "." in ip:
        a = ip.split(".")
        return ".".join(a[:2] + ["x", "x"]) if len(a) == 4 else "x"
    return ":".join(ip.split(":")[:4]) + ":…"


def resume_navigateur(ua):
    ua = ua or ""
    nav = next((n for motif, n in [(r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"),
                                   (r"Chrome/", "Chrome"), (r"Safari/", "Safari")] if re.search(motif, ua)), "Navigateur")
    os_ = next((n for motif, n in [(r"Android", "Android"), (r"iPhone|iPad", "iOS"), (r"Windows", "Windows"),
                                   (r"Mac OS X", "macOS"), (r"Linux", "Linux")] if re.search(motif, ua)), "")
    return f"{nav} · {os_}" if os_ else nav


def normaliser_identifiant(identifiant):
    return (identifiant or "").strip().lower()[:254]


def journaliser(request, action, cible="", details="", acteur=None):
    acteur = acteur if acteur is not None else (request.user if request and request.user.is_authenticated else None)
    return JournalAudit.objects.create(
        acteur=acteur, acteur_nom=(acteur.username if acteur else ""), action=action,
        cible=str(cible)[:200], details=str(details)[:300], ip=masquer_ip(ip_client(request)),
    )


# ------------------------------------------------------------------------------ brute-force
def minutes_de_blocage(identifiant):
    """Renvoie le nombre de minutes restantes si l'identifiant est bloqué, sinon 0."""
    ident = normaliser_identifiant(identifiant)
    if not ident:
        return 0
    depuis = timezone.now() - FENETRE
    echecs = list(HistoriqueConnexion.objects.filter(identifiant=ident, succes=False, cree_le__gte=depuis)
                  .order_by("-cree_le").values_list("cree_le", flat=True)[:MAX_ECHECS])
    if len(echecs) < MAX_ECHECS:
        return 0
    # une connexion réussie après ces échecs remet le compteur à zéro
    if HistoriqueConnexion.objects.filter(identifiant=ident, succes=True, cree_le__gt=echecs[-1]).exists():
        return 0
    reste = echecs[0] + FENETRE - timezone.now()
    return max(1, int(reste.total_seconds() // 60) + 1)


def _utilisateur_pour(identifiant):
    champ = "email__iexact" if "@" in identifiant else "username__iexact"
    return Utilisateur.objects.filter(**{champ: identifiant}).first()


@receiver(user_login_failed)
def enregistrer_echec(sender, credentials, request=None, **kwargs):
    ident = normaliser_identifiant(credentials.get("username"))
    if not ident:
        return
    HistoriqueConnexion.objects.create(
        utilisateur=_utilisateur_pour(ident), identifiant=ident, succes=False,
        ip=masquer_ip(ip_client(request)),
        navigateur=resume_navigateur(request.META.get("HTTP_USER_AGENT") if request else ""),
    )
    journaliser(request, JournalAudit.Action.CONNEXION_ECHOUEE, cible=ident,
                details="identifiant ou mot de passe incorrect", acteur=None)
    if minutes_de_blocage(ident) and not JournalAudit.objects.filter(
            action=JournalAudit.Action.CONNEXION_BLOQUEE, cible=ident, cree_le__gte=timezone.now() - FENETRE).exists():
        journaliser(request, JournalAudit.Action.CONNEXION_BLOQUEE, cible=ident,
                    details=f"{MAX_ECHECS} échecs en {int(FENETRE.total_seconds() // 60)} min", acteur=None)


@receiver(user_logged_in)
def enregistrer_succes(sender, request, user, **kwargs):
    if request is None:
        return
    HistoriqueConnexion.objects.create(
        utilisateur=user, identifiant=normaliser_identifiant(request.POST.get("username") or user.username),
        succes=True, ip=masquer_ip(ip_client(request)),
        navigateur=resume_navigateur(request.META.get("HTTP_USER_AGENT")),
        session_key=getattr(request.session, "session_key", "") or "",
    )
    journaliser(request, JournalAudit.Action.CONNEXION, cible=user.username,
                details=resume_navigateur(request.META.get("HTTP_USER_AGENT")), acteur=user)


@receiver(user_logged_out)
def enregistrer_deconnexion(sender, request, user, **kwargs):
    if request is not None and user is not None and user.pk and Utilisateur.objects.filter(pk=user.pk).exists():
        journaliser(request, JournalAudit.Action.DECONNEXION, cible=user.username, acteur=user)


def deconnecter_autres_appareils(request):
    """Supprime toutes les sessions de l'utilisateur sauf celle en cours. Renvoie le nombre de sessions fermées."""
    actuelle = request.session.session_key
    cles = set(request.user.connexions.filter(succes=True).exclude(session_key="").values_list("session_key", flat=True))
    cles.discard(actuelle)
    n, _ = Session.objects.filter(session_key__in=cles).delete()
    return n
