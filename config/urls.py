from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

admin.site.site_header = "EcoAssiette — Administration"
admin.site.site_title = "EcoAssiette"
admin.site.index_title = "Tableau de bord"

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("admin/", admin.site.urls),
    path("comptes/", include("users.urls")),
    path("api/", include("users.api.urls")),
    path("repas/", include("repas.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "users.views.erreur_403"
handler404 = "users.views.erreur_404"
handler500 = "users.views.erreur_500"
