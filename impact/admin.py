from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from urllib.parse import urlsplit
from django.utils import timezone

from users.ai import ErreurIA, appeler_gemini

from .models import (
    AlternativeAdoptee, AlternativeVegetale, CommandeRecompense, ExtractionRecetteIA,
    FacteurImpact, PreuveRepas, ProduitRecompense, Sponsor, TransactionPoints,
)
from .product_ai import ErreurImportProduit, analyser_url_produit
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
        "produit_utilise", "co2_evite", "eau_economisee", "terres_preservees", "adoptee_le",
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


class ImportProduitIAForm(forms.Form):
    url = forms.URLField(
        label="URL officielle du produit",
        help_text="Collez la page exacte du produit chez le fabricant ou le sponsor.",
    )
    remise_pourcent = forms.IntegerField(
        label="Remise proposée (%)", min_value=1, max_value=100, initial=50
    )
    cout_points = forms.IntegerField(label="Points nécessaires", min_value=1, initial=200)


@admin.register(ProduitRecompense)
class ProduitRecompenseAdmin(admin.ModelAdmin):
    form = ProduitRecompenseForm
    change_list_template = "admin/impact/produitrecompense/change_list.html"
    list_display = ("nom", "sponsor", "statut", "remise_pourcent", "cout_points", "stock", "propose_par_ia")
    list_filter = ("statut", "produit_vegetal", "propose_par_ia", "sponsor")
    search_fields = ("nom", "description", "mots_cles_recommandation", "sponsor__nom")

    def get_urls(self):
        urls = super().get_urls()
        personnalisees = [
            path(
                "importer-avec-ia/",
                self.admin_site.admin_view(self.importer_avec_ia),
                name="impact_produitrecompense_importer_ia",
            ),
        ]
        return personnalisees + urls

    def importer_avec_ia(self, request):
        if not self.has_add_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = ImportProduitIAForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                donnees = analyser_url_produit(form.cleaned_data["url"])
            except ErreurImportProduit as exc:
                form.add_error("url", str(exc))
            else:
                if not donnees["produit_vegetal"]:
                    form.add_error(
                        "url", "L'IA n'a pas identifié ce produit comme végétal. Vérifiez l'URL."
                    )
                else:
                    domaine = urlsplit(donnees["url_source"]).hostname or ""
                    sponsor, _ = Sponsor.objects.get_or_create(
                        nom=donnees["sponsor_nom"],
                        defaults={"site_web": f"https://{domaine}" if domaine else ""},
                    )
                    produit = ProduitRecompense.objects.create(
                        sponsor=sponsor,
                        nom=donnees["nom"],
                        description=donnees["description"],
                        prix_public=donnees["prix_public"],
                        remise_pourcent=form.cleaned_data["remise_pourcent"],
                        cout_points=form.cleaned_data["cout_points"],
                        stock=0,
                        produit_vegetal=True,
                        mots_cles_recommandation=donnees["mots_cles_recommandation"],
                        url_source=donnees["url_source"],
                        propose_par_ia=True,
                        statut=ProduitRecompense.Statut.BROUILLON,
                    )
                    self.message_user(
                        request,
                        "Produit importé par l'IA. Vérifiez le prix, ajoutez l'image et le stock, puis publiez-le.",
                        messages.SUCCESS,
                    )
                    return redirect(reverse("admin:impact_produitrecompense_change", args=[produit.pk]))
        contexte = {
            **self.admin_site.each_context(request),
            "title": "Importer un produit avec l’IA",
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/impact/produitrecompense/importer_ia.html", contexte
        )


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
    list_display = ("utilisateur", "montant", "motif", "origine", "creee_le")
    list_filter = ("creee_le",)
    search_fields = ("utilisateur__username", "utilisateur__email", "motif")
    autocomplete_fields = ("utilisateur",)
    fields = ("utilisateur", "montant", "motif", "preuve", "creee_le")

    @admin.display(description="Origine")
    def origine(self, obj):
        return "Preuve validée" if obj.preuve_id else "Ajustement manuel"

    def get_readonly_fields(self, request, obj=None):
        # Une transaction issue d'une preuve est une trace d'audit : elle ne doit
        # jamais être altérée. Les ajustements manuels restent modifiables.
        if obj and obj.preuve_id:
            return ("utilisateur", "montant", "motif", "preuve", "creee_le")
        return ("preuve", "creee_le")


@admin.register(CommandeRecompense)
class CommandeRecompenseAdmin(admin.ModelAdmin):
    list_display = ("id", "utilisateur", "produit", "points_utilises", "prix_remise", "statut", "creee_le")
    list_filter = ("statut", "creee_le")
    readonly_fields = ("utilisateur", "produit", "points_utilises", "prix_remise", "creee_le")
