from .models import DemandeNutritionniste


def notifications_admin(request):
    """Nombre de demandes « nutritionniste » à valider (pastille dans le menu des administrateurs)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.has_perm("users.gerer_utilisateurs"):
        return {}
    return {"nb_demandes_attente": DemandeNutritionniste.objects.filter(statut=DemandeNutritionniste.Statut.EN_ATTENTE).count()}
