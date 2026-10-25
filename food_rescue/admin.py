from django.contrib import admin

from .models import AnalyseSurplusIA, AnnonceSurplus, CollecteSurplus, ReservationSurplus


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
    list_display = ("reservation", "confirmee_par_donateur", "confirmee_par_beneficiaire", "confirmee_le")
    readonly_fields = ("reservation", "confirmee_par_donateur", "confirmee_par_beneficiaire", "confirmee_le")

