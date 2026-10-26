from django.urls import path

from . import views

app_name = "impact"

urlpatterns = [
    path("", views.tableau_bord, name="tableau_bord"),
    path("assistant-recette/", views.assistant_recette, name="assistant_recette"),
    path("assistant-recette/brouillon/<int:brouillon_id>/", views.reprendre_brouillon, name="reprendre_brouillon"),
    path("assistant-recette/brouillon/<int:brouillon_id>/supprimer/", views.supprimer_brouillon, name="supprimer_brouillon"),
    path("assistant-recette/valider/", views.valider_recette, name="valider_recette"),
    path("portefeuille/", views.portefeuille, name="portefeuille"),
    path("portefeuille/preuve/", views.soumettre_preuve, name="soumettre_preuve"),
    path("portefeuille/acheter/<int:produit_id>/", views.acheter_produit, name="acheter_produit"),
    path("portefeuille/bon/<int:commande_id>/pdf/", views.telecharger_bon, name="telecharger_bon"),
    path("bons/<str:code>/", views.verifier_bon, name="verifier_bon"),
    path("repas/<int:repas_id>/adopter/<int:alternative_id>/", views.adopter_alternative, name="adopter"),
]
