from django.contrib import admin

from .models import Commentaire, Jaime, Mention, Publication


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ("auteur", "resume", "publication_originale", "est_masquee", "creee_le")
    list_filter = ("est_masquee", "creee_le")
    search_fields = ("texte", "auteur__username", "auteur__email")
    readonly_fields = ("creee_le", "modifiee_le")

    @admin.display(description="Contenu")
    def resume(self, obj):
        return (obj.texte or "Repartage")[:70]


admin.site.register(Commentaire)
admin.site.register(Jaime)
admin.site.register(Mention)
