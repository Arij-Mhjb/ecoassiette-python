from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import DemandeNutritionniste, Invitation, AnalyseProfilIA, ProfilAlimentaire, Utilisateur


class ProfilInline(admin.StackedInline):
    model = ProfilAlimentaire
    can_delete = False
    extra = 0


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    inlines = [ProfilInline]
    list_display = ("username", "email", "email_verifie", "first_name", "last_name", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active", "email_verifie", "is_staff", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)
    list_editable = ("role", "is_active")
    actions = ["desactiver", "activer"]
    fieldsets = UserAdmin.fieldsets + (("EcoAssiette", {"fields": ("role", "telephone", "avatar", "email_verifie")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("EcoAssiette", {"fields": ("email", "role")}),)

    @admin.action(description="Désactiver les comptes sélectionnés")
    def desactiver(self, request, queryset):
        n = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, f"{n} compte(s) désactivé(s).")

    @admin.action(description="Activer les comptes sélectionnés")
    def activer(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} compte(s) activé(s).")


@admin.register(ProfilAlimentaire)
class ProfilAlimentaireAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "regime", "taille_foyer", "objectif_co2_hebdo", "profil_public", "mis_a_jour")
    list_filter = ("regime", "niveau_activite", "profil_public")
    search_fields = ("utilisateur__username", "utilisateur__email", "ville")
    readonly_fields = ("mis_a_jour",)


@admin.register(AnalyseProfilIA)
class AnalyseProfilIAAdmin(admin.ModelAdmin):
    list_display = ("id", "profil", "statut", "source", "duree_ms", "cree_le")
    list_filter = ("statut", "source")
    readonly_fields = ("profil", "statut", "source", "resultat", "erreur", "duree_ms", "cree_le", "termine_le")
    date_hierarchy = "cree_le"

    def has_add_permission(self, request):
        return False


@admin.register(DemandeNutritionniste)
class DemandeNutritionnisteAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "numero_ordre", "etablissement", "statut", "cree_le", "traitee_par", "traitee_le")
    list_filter = ("statut",)
    search_fields = ("utilisateur__username", "utilisateur__email", "numero_ordre", "etablissement")
    readonly_fields = ("cree_le", "traitee_le", "traitee_par")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "statut", "invite_par", "cree_le", "expire_le", "acceptee_le")
    list_filter = ("statut", "role")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ("jeton_hash", "cree_le", "acceptee_le", "utilisateur")

    def has_add_permission(self, request):
        return False   # une invitation se crée depuis /comptes/gestion/invitations/ (envoi de l'e-mail)
