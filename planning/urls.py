from django.urls import path

from . import views

app_name = "planning"

urlpatterns = [
    path("", views.tableau, name="tableau"),
    path("generer/", views.generer, name="generer"),
    path("menu/<int:menu_id>/remplacer/", views.remplacer, name="remplacer"),
    path("<int:plan_id>/courses/", views.courses, name="courses"),
]
