from .models import NotificationCommunaute


def notifications_communaute(request):
    utilisateur = getattr(request, "user", None)
    if not utilisateur or not utilisateur.is_authenticated:
        return {}
    return {
        "nb_notifications_communaute": NotificationCommunaute.objects.filter(
            destinataire=utilisateur, lue_le__isnull=True
        ).count()
    }
