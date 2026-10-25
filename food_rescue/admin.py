from django.contrib import admin, messages
from django.utils import timezone

from .models import AnalyseSurplusIA, AnnonceSurplus, CollecteSurplus, ProfilBeneficiaire, ReservationSurplus


@admin.register(AnnonceSurplus)
class AnnonceSurplusAdmin(admin.ModelAdmin):
    list_display = ("titre", "donateur", "ville", "categorie", "statut", "urgence_ia", "disponible_jusquau")
    list_filter = ("statut", "categorie", "conservation", "urgence_ia", "ville")
    search_fields = ("titre", "description", "donateur__username", "ville")
    readonly_fields = ("urgence_ia", "confiance_ia", "co2_evite_estime", "creee_le", "modifiee_le")


@admin.register(ReservationSurplus)
class ReservationSurplusAdmin(admin.ModelAdmin):
    list_display = ("annonce", "beneficiaire", "heure_collecte", "statut", "creee_le")
    list_filter = ("statut", "creee_le")
    search_fields = ("annonce__titre", "beneficiaire__username")
    readonly_fields = ("code_collecte", "creee_le", "traitee_le")


@admin.register(AnalyseSurplusIA)
class AnalyseSurplusIAAdmin(admin.ModelAdmin):
    list_display = ("annonce", "statut", "source", "duree_ms", "creee_le")
    list_filter = ("statut", "source")
    readonly_fields = ("annonce", "statut", "source", "resultat", "erreur", "duree_ms", "creee_le", "terminee_le")


@admin.register(CollecteSurplus)
class CollecteSurplusAdmin(admin.ModelAdmin):
    list_display = ("reservation", "confirmee_par_donateur", "confirmee_par_beneficiaire", "points_attribues", "confirmee_le")
    readonly_fields = ("reservation", "confirmee_par_donateur", "confirmee_par_beneficiaire", "points_attribues", "confirmee_le")


@admin.register(ProfilBeneficiaire)
class ProfilBeneficiaireAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "type_beneficiaire", "organisme", "statut", "soumis_le", "verifie_le")
    list_filter = ("type_beneficiaire", "statut", "soumis_le")
    search_fields = ("utilisateur__username", "utilisateur__email", "organisme", "reference_justificatif")
    readonly_fields = ("utilisateur", "type_beneficiaire", "organisme", "reference_justificatif", "soumis_le", "modifie_le", "verifie_par", "verifie_le")
    fields = readonly_fields + ("statut", "motif_refus")
    actions = ("valider_eligibilite", "refuser_eligibilite")

    @admin.action(description="Valider les profils sélectionnés")
    def valider_eligibilite(self, request, queryset):
        nombre = queryset.update(
            statut=ProfilBeneficiaire.Statut.VALIDEE,
            motif_refus="",
            verifie_par=request.user,
            verifie_le=timezone.now(),
        )
        self.message_user(request, f"{nombre} profil(s) validé(s).", messages.SUCCESS)

    @admin.action(description="Refuser les profils sélectionnés")
    def refuser_eligibilite(self, request, queryset):
        nombre = queryset.update(
            statut=ProfilBeneficiaire.Statut.REFUSEE,
            verifie_par=request.user,
            verifie_le=timezone.now(),
        )
        self.message_user(request, f"{nombre} profil(s) refusé(s).", messages.WARNING)

