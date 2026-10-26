from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("", views.fil, name="fil"),
    path("publier/", views.publier, name="publier"),
    path("api/utilisateurs/", views.rechercher_utilisateurs, name="rechercher_utilisateurs"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/tout-lire/", views.tout_lire, name="tout_lire"),
    path("notifications/<int:pk>/lire/", views.lire_notification, name="lire_notification"),
    path("administration/", views.administration, name="administration"),
    path("administration/<int:pk>/moderer/", views.moderer_publication, name="moderer_publication"),
    path("membre/<str:username>/", views.profil_membre, name="profil_membre"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/modifier/", views.modifier, name="modifier"),
    path("<int:pk>/supprimer/", views.supprimer, name="supprimer"),
    path("<int:pk>/aimer/", views.aimer, name="aimer"),
    path("<int:pk>/commenter/", views.commenter, name="commenter"),
    path("<int:pk>/partager/", views.partager, name="partager"),
    path("commentaire/<int:pk>/supprimer/", views.supprimer_commentaire, name="supprimer_commentaire"),
]
