from django.urls import path

from . import views

app_name = "food_rescue"

urlpatterns = [
    path("", views.AnnonceListView.as_view(), name="liste"),
    path("tableau-de-bord/", views.tableau_bord, name="tableau_bord"),
    path("mes-annonces/", views.MesAnnoncesView.as_view(), name="mes_annonces"),
    path("publier/", views.AnnonceCreateView.as_view(), name="creer"),
    path("<int:pk>/", views.AnnonceDetailView.as_view(), name="detail"),
    path("<int:pk>/modifier/", views.AnnonceUpdateView.as_view(), name="modifier"),
    path("<int:pk>/supprimer/", views.AnnonceDeleteView.as_view(), name="supprimer"),
    path("<int:pk>/reserver/", views.reserver, name="reserver"),
    path("<int:pk>/analyse/", views.analyse_etat, name="analyse_etat"),
    path("reservation/<int:pk>/confirmer-collecte/", views.confirmer_collecte, name="confirmer_collecte"),
    path("reservation/<int:pk>/<str:action>/", views.traiter_reservation, name="traiter_reservation"),
]

