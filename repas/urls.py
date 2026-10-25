from django.urls import path

from . import views

app_name = "repas"

urlpatterns = [
    path("", views.RepasListView.as_view(), name="liste"),
    path("ajouter/", views.RepasCreateView.as_view(), name="ajouter"),
    path("<int:pk>/", views.RepasDetailView.as_view(), name="detail"),
    path("<int:pk>/modifier/", views.RepasUpdateView.as_view(), name="modifier"),
    path("<int:pk>/supprimer/", views.RepasDeleteView.as_view(), name="supprimer"),
    path("<int:pk>/remplacer/<int:element_pk>/", views.remplacer, name="remplacer"),
    path("ia/photo/", views.ia_photo, name="ia_photo"),
    path("ia/audio/", views.ia_audio, name="ia_audio"),
    path("ia/texte/", views.ia_texte, name="ia_texte"),
    path("ia/analyse/<int:pk>/", views.ia_etat, name="ia_etat"),
    path("labo/", views.LaboIAView.as_view(), name="labo"),
]