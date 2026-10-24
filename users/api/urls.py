from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("moi/", views.moi, name="moi"),
    path("moi/profil/", views.mon_profil, name="mon_profil"),
    path("utilisateurs/", views.UtilisateurListAPI.as_view(), name="utilisateurs"),
    path("utilisateurs/<int:pk>/", views.utilisateur_detail, name="utilisateur_detail"),
]
