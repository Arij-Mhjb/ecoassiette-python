from .models import DemandeNutritionniste, Recommandation


def notifications_admin(request):
    """Nombre de demandes « nutritionniste » à valider (pastille dans le menu des administrateurs)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.has_perm("users.gerer_utilisateurs"):
        return {}
    return {"nb_demandes_attente": DemandeNutritionniste.objects.filter(statut=DemandeNutritionniste.Statut.EN_ATTENTE).count()}


def notifications_citoyen(request):
    """Nombre de recommandations non lues (pastille dans le menu du citoyen)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.role != user.Role.CITOYEN:
        return {}
    return {"nb_recos_non_lues": Recommandation.objects.filter(citoyen=user, lue_le__isnull=True).count()}
