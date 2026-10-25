from django import forms
from django.contrib import admin, messages
from django.utils import timezone

from users.ai import ErreurIA, appeler_gemini

from .models import (
    AlternativeAdoptee, AlternativeVegetale, CommandeRecompense, ExtractionRecetteIA,
    FacteurImpact, PreuveRepas, ProduitRecompense, Sponsor, TransactionPoints,
)
from .services import crediter_preuve


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


@admin.action(description="Proposer des produits végétaux avec l'IA (brouillons)")
def proposer_produits_ia(modeladmin, request, queryset):
    crees = 0
    for sponsor in queryset.filter(actif=True):
        prompt = (
            "Propose 3 produits végétaux plausibles pour le catalogue de ce sponsor. "
            "Ne prétends pas avoir vérifié leur existence. Réponds uniquement en JSON : "
            '{"produits":[{"nom":"...","description":"...","prix_public":10,"remise_pourcent":50,"cout_points":200}]}. '
            f"Sponsor : {sponsor.nom}; site officiel : {sponsor.site_web or 'non renseigné'}."
        )
        try:
            brut = appeler_gemini(prompt)
        except ErreurIA as exc:
            modeladmin.message_user(request, f"IA indisponible pour {sponsor}: {exc}", messages.ERROR)
            continue
        for produit in brut.get("produits", [])[:3] if isinstance(brut, dict) else []:
            try:
                ProduitRecompense.objects.create(
                    sponsor=sponsor, nom=str(produit["nom"])[:160],
                    description=str(produit.get("description", ""))[:800],
                    prix_public=max(0, float(produit.get("prix_public", 0))),
                    remise_pourcent=min(100, max(1, int(produit.get("remise_pourcent", 50)))),
                    cout_points=max(1, int(produit.get("cout_points", 200))),
                    produit_vegetal=True, propose_par_ia=True,
                    statut=ProduitRecompense.Statut.BROUILLON, stock=0,
                )
                crees += 1
            except (KeyError, TypeError, ValueError):
                continue
    modeladmin.message_user(
        request, f"{crees} brouillon(s) créé(s). Vérifiez l'existence, l'URL, le prix et le stock avant publication."
    )


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    list_display = ("nom", "site_web", "actif")
    list_filter = ("actif",)
    actions = (proposer_produits_ia,)


class ProduitRecompenseForm(forms.ModelForm):
    class Meta:
        model = ProduitRecompense
        fields = "__all__"

    def clean(self):
        donnees = super().clean()
        if donnees.get("statut") == ProduitRecompense.Statut.PUBLIE:
            if not donnees.get("url_source"):
                self.add_error("url_source", "Une page officielle vérifiée est obligatoire avant publication.")
            if not donnees.get("produit_vegetal"):
                self.add_error("produit_vegetal", "Seuls les produits végétaux peuvent être publiés.")
        return donnees


@admin.register(ProduitRecompense)
class ProduitRecompenseAdmin(admin.ModelAdmin):
    form = ProduitRecompenseForm
    list_display = ("nom", "sponsor", "statut", "remise_pourcent", "cout_points", "stock", "propose_par_ia")
    list_filter = ("statut", "produit_vegetal", "propose_par_ia", "sponsor")
    search_fields = ("nom", "sponsor__nom")


@admin.action(description="Approuver les preuves et créditer les points")
def approuver_preuves(modeladmin, request, queryset):
    nombre = 0
    for preuve in queryset.filter(statut=PreuveRepas.Statut.EN_ATTENTE):
        creee, _ = crediter_preuve(preuve)
        nombre += int(creee)
    modeladmin.message_user(request, f"{nombre} preuve(s) approuvée(s) et créditée(s).")


@admin.action(description="Refuser les preuves sélectionnées")
def refuser_preuves(modeladmin, request, queryset):
    nombre = queryset.filter(statut=PreuveRepas.Statut.EN_ATTENTE).update(
        statut=PreuveRepas.Statut.REFUSEE, traitee_le=timezone.now()
    )
    modeladmin.message_user(request, f"{nombre} preuve(s) refusée(s).")


@admin.register(PreuveRepas)
class PreuveRepasAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "repas", "type_media", "statut", "points_attribues", "soumise_le")
    list_filter = ("statut", "type_media", "soumise_le")
    readonly_fields = ("utilisateur", "repas", "media", "type_media", "points_attribues", "soumise_le", "traitee_le")
    actions = (approuver_preuves, refuser_preuves)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.statut == PreuveRepas.Statut.APPROUVEE:
            creee, points = crediter_preuve(obj)
            if creee:
                self.message_user(request, f"Preuve approuvée : {points} points crédités au client.")


@admin.register(TransactionPoints)
class TransactionPointsAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "montant", "motif", "creee_le")
    readonly_fields = ("utilisateur", "montant", "motif", "preuve", "creee_le")


@admin.register(CommandeRecompense)
class CommandeRecompenseAdmin(admin.ModelAdmin):
    list_display = ("id", "utilisateur", "produit", "points_utilises", "prix_remise", "statut", "creee_le")
    list_filter = ("statut", "creee_le")
    readonly_fields = ("utilisateur", "produit", "points_utilises", "prix_remise", "creee_le")
