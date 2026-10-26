from django.contrib import admin

from .models import Commentaire, Jaime, Mention, MentionCommentaire, NotificationCommunaute, Publication


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ("auteur", "resume", "publication_originale", "image_generee_ia", "est_masquee", "creee_le")
    list_filter = ("est_masquee", "image_generee_ia", "creee_le")
    search_fields = ("texte", "auteur__username", "auteur__email")
    readonly_fields = ("creee_le", "modifiee_le")

    @admin.display(description="Contenu")
    def resume(self, obj):
        return (obj.texte or "Repartage")[:70]


admin.site.register(Commentaire)
admin.site.register(Jaime)
admin.site.register(Mention)
admin.site.register(MentionCommentaire)


@admin.register(NotificationCommunaute)
class NotificationCommunauteAdmin(admin.ModelAdmin):
    list_display = ("destinataire", "acteur", "type", "lue_le", "creee_le")
    list_filter = ("type", "lue_le", "creee_le")
    search_fields = ("destinataire__username", "acteur__username")
    readonly_fields = ("creee_le",)
