from django.contrib import admin

from .models import AlternativeAdoptee, AlternativeVegetale, ExtractionRecetteIA, FacteurImpact


@admin.register(FacteurImpact)
class FacteurImpactAdmin(admin.ModelAdmin):
    list_display = (
        "categorie", "co2_kg_par_kg", "eau_litres_par_kg",
        "terres_m2_par_kg", "risque_deforestation",
    )
    list_filter = ("risque_deforestation",)
    search_fields = ("categorie", "source")


@admin.register(AlternativeVegetale)
class AlternativeVegetaleAdmin(admin.ModelAdmin):
    list_display = ("aliment_source", "categorie_source", "remplacement", "actif")
    list_filter = ("categorie_source", "actif")
    search_fields = ("aliment_source", "remplacement")


@admin.register(AlternativeAdoptee)
class AlternativeAdopteeAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "aliment_original", "remplacement", "co2_evite", "adoptee_le")
    list_filter = ("adoptee_le",)
    search_fields = ("utilisateur__username", "aliment_original", "remplacement")
    readonly_fields = (
        "utilisateur", "repas", "alternative", "aliment_original", "remplacement",
        "co2_evite", "eau_economisee", "terres_preservees", "adoptee_le",
    )


@admin.register(ExtractionRecetteIA)
class ExtractionRecetteIAAdmin(admin.ModelAdmin):
    list_display = ("repas", "utilisateur", "source", "creee_le")
    list_filter = ("source", "creee_le")
    search_fields = ("utilisateur__username", "texte_original")
    readonly_fields = ("utilisateur", "repas", "texte_original", "source", "creee_le")
