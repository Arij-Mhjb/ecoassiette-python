from django.urls import path

from . import views

app_name = "impact"

urlpatterns = [
    path("", views.tableau_bord, name="tableau_bord"),
    path("assistant-recette/", views.assistant_recette, name="assistant_recette"),
    path("assistant-recette/valider/", views.valider_recette, name="valider_recette"),
    path("repas/<int:repas_id>/adopter/<int:alternative_id>/", views.adopter_alternative, name="adopter"),
]
