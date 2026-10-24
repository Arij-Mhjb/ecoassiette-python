from django.urls import path

from . import views

app_name = "repas"

urlpatterns = [
    path("", views.RepasListView.as_view(), name="liste"),
    path("ajouter/", views.RepasCreateView.as_view(), name="ajouter"),
    path("<int:pk>/", views.RepasDetailView.as_view(), name="detail"),
    path("<int:pk>/modifier/", views.RepasUpdateView.as_view(), name="modifier"),
    path("<int:pk>/supprimer/", views.RepasDeleteView.as_view(), name="supprimer"),
]