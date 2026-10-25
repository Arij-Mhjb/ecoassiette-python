from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from repas.models import ElementRepas, Repas

from users.ai import ErreurIA

from .forms import GardeMangerForm, IngredientExtraitFormSet, PreuveRepasForm, RecetteAssistantForm
from .models import (
    AlternativeAdoptee, CommandeRecompense, ExtractionRecetteIA, PreuveRepas,
    ProduitRecompense, TransactionPoints,
)
from .recipe_ai import extraire_recette, proposer_recettes_garde_manger
from .services import analyser_ingredients, analyser_repas, proposer_alternative, solde_points


@login_required
def tableau_bord(request):
    adoptions = AlternativeAdoptee.objects.filter(utilisateur=request.user).select_related("repas")
    sommes = adoptions.aggregate(
        co2=Sum("co2_evite"), eau=Sum("eau_economisee"), terres=Sum("terres_preservees")
    )
    totaux = {cle: valeur or Decimal("0") for cle, valeur in sommes.items()}
    repas_recents = []
    impact_reel = {"co2": Decimal("0"), "eau": Decimal("0"), "terres": Decimal("0")}
    repas_qs = Repas.objects.filter(utilisateur=request.user).prefetch_related("elements")
    for repas in repas_qs:
        analyse = analyser_repas(repas, request.user)
        for cle in impact_reel:
            impact_reel[cle] += analyse["totaux"][cle]
        if len(repas_recents) < 10:
            repas_recents.append({"repas": repas, "impact": analyse["totaux"]})
    return render(request, "impact/tableau_bord.html", {
        "adoptions": adoptions[:20], "totaux": totaux, "nombre_adoptions": adoptions.count(),
        "impact_reel": impact_reel, "repas_recents": repas_recents, "nombre_repas": repas_qs.count(),
    })


def _lignes_apercu(formset, utilisateur):
    lignes = []
    for formulaire in formset.forms:
        donnees = formulaire.cleaned_data if formulaire.is_bound and formulaire.is_valid() else formulaire.initial
        alternative = None
        if donnees and not donnees.get("DELETE"):
            alternative = proposer_alternative(
                donnees.get("aliment", ""), donnees.get("categorie", ""), utilisateur
            )
        lignes.append({"form": formulaire, "alternative": alternative})
    return lignes


@login_required
def assistant_recette(request):
    apercu = None
    recettes_garde_manger = None
    garde_form = GardeMangerForm()
    if request.method == "POST":
        if request.POST.get("mode") == "garde_manger":
            garde_form = GardeMangerForm(request.POST)
            form = RecetteAssistantForm()
            if garde_form.is_valid():
                recettes_garde_manger, source_garde = proposer_recettes_garde_manger(
                    garde_form.cleaned_data["ingredients_maison"], getattr(request.user, "profil", None)
                )
            else:
                source_garde = None
            return render(request, "impact/assistant_recette.html", {
                "form": form, "apercu": None, "garde_form": garde_form,
                "recettes_garde_manger": recettes_garde_manger, "source_garde": source_garde,
            })
        form = RecetteAssistantForm(request.POST)
        if form.is_valid():
            try:
                ingredients, source, erreur = extraire_recette(form.cleaned_data["texte"])
            except ErreurIA as exc:
                form.add_error("texte", str(exc))
            else:
                formset = IngredientExtraitFormSet(initial=ingredients, prefix="ingredients")
                analyse = analyser_ingredients(ingredients, request.user)
                apercu = {
                    "formset": formset,
                    "lignes": _lignes_apercu(formset, request.user),
                    "analyse": analyse,
                    "source": source,
                    "erreur_ia": erreur,
                }
    else:
        form = RecetteAssistantForm()
    return render(request, "impact/assistant_recette.html", {
        "form": form, "apercu": apercu, "garde_form": garde_form,
        "recettes_garde_manger": recettes_garde_manger,
    })


@login_required
def portefeuille(request):
    produits = ProduitRecompense.objects.filter(
        statut=ProduitRecompense.Statut.PUBLIE, stock__gt=0, sponsor__actif=True
    ).select_related("sponsor")
    return render(request, "impact/portefeuille.html", {
        "solde": solde_points(request.user), "produits": produits,
        "preuves": PreuveRepas.objects.filter(utilisateur=request.user)[:10],
        "transactions": TransactionPoints.objects.filter(utilisateur=request.user)[:15],
        "commandes": CommandeRecompense.objects.filter(utilisateur=request.user).select_related("produit")[:10],
    })


@login_required
def soumettre_preuve(request):
    if request.method == "POST":
        form = PreuveRepasForm(request.POST, request.FILES, utilisateur=request.user)
        if form.is_valid():
            preuve = form.save(commit=False)
            preuve.utilisateur = request.user
            preuve.type_media = form.type_media
            preuve.save()
            messages.success(request, "Preuve envoyée. Les points seront crédités après validation administrative.")
            return redirect("impact:portefeuille")
    else:
        form = PreuveRepasForm(utilisateur=request.user)
    return render(request, "impact/soumettre_preuve.html", {"form": form})


@login_required
@require_POST
def acheter_produit(request, produit_id):
    with transaction.atomic():
        request.user.__class__.objects.select_for_update().get(pk=request.user.pk)
        produit = get_object_or_404(
            ProduitRecompense.objects.select_for_update(), pk=produit_id,
            statut=ProduitRecompense.Statut.PUBLIE, sponsor__actif=True,
        )
        if produit.stock < 1:
            messages.error(request, "Ce produit n'est plus en stock.")
            return redirect("impact:portefeuille")
        if solde_points(request.user) < produit.cout_points:
            messages.error(request, "Votre solde de points est insuffisant.")
            return redirect("impact:portefeuille")
        CommandeRecompense.objects.create(
            utilisateur=request.user, produit=produit, points_utilises=produit.cout_points,
            prix_remise=produit.prix_remise,
        )
        TransactionPoints.objects.create(
            utilisateur=request.user, montant=-produit.cout_points,
            motif=f"Récompense : {produit.nom}",
        )
        produit.stock -= 1
        produit.save(update_fields=["stock"])
    messages.success(request, "Récompense réservée. Le sponsor vous contactera pour la remise du produit.")
    return redirect("impact:portefeuille")


@login_required
@require_POST
def valider_recette(request):
    form = RecetteAssistantForm(request.POST)
    formset = IngredientExtraitFormSet(request.POST, prefix="ingredients")
    if not (form.is_valid() and formset.is_valid()):
        lignes = _lignes_apercu(formset, request.user)
        ingredients_valides = [
            f.cleaned_data for f in formset.forms if f.is_valid() and not f.cleaned_data.get("DELETE")
        ]
        analyse = analyser_ingredients(ingredients_valides, request.user) if ingredients_valides else None
        return render(request, "impact/assistant_recette.html", {
            "form": form,
            "apercu": {"formset": formset, "lignes": lignes, "analyse": analyse, "source": request.POST.get("source", "LOCAL")},
        }, status=400)

    source = request.POST.get("source")
    if source not in ExtractionRecetteIA.Source.values:
        source = ExtractionRecetteIA.Source.LOCAL

    with transaction.atomic():
        repas = Repas.objects.create(
            utilisateur=request.user,
            type_repas=form.cleaned_data["type_repas"],
            date=form.cleaned_data["date"],
            note=form.cleaned_data["note"] or "Recette analysée par IA",
        )
        adoptions = []
        for formulaire in formset:
            d = formulaire.cleaned_data
            if d.get("DELETE"):
                continue
            aliment, categorie = d["aliment"], d["categorie"]
            alternative = proposer_alternative(aliment, categorie, request.user)
            if d.get("utiliser_alternative") and alternative:
                analyse_ligne = analyser_ingredients([{
                    "aliment": aliment, "categorie": categorie, "quantite_g": d["quantite_g"],
                }], request.user)
                proposition = next(
                    (a for a in analyse_ligne["alternatives"] if a["id"] == alternative.pk), None
                )
                if proposition:
                    adoptions.append((alternative, aliment, proposition))
                    aliment = alternative.remplacement
                    categorie = alternative.facteur_remplacement.categorie
            ElementRepas.objects.create(
                repas=repas, aliment=aliment, categorie=categorie, quantite_g=d["quantite_g"]
            )
        ExtractionRecetteIA.objects.create(
            utilisateur=request.user, repas=repas,
            texte_original=form.cleaned_data["texte"], source=source,
        )
        for alternative, original, proposition in adoptions:
            AlternativeAdoptee.objects.create(
                utilisateur=request.user, repas=repas, alternative=alternative,
                aliment_original=original, remplacement=alternative.remplacement,
                co2_evite=proposition["gains"]["co2"],
                eau_economisee=proposition["gains"]["eau"],
                terres_preservees=proposition["gains"]["terres"],
            )
    messages.success(request, "Recette vérifiée et ajoutée à vos repas.")
    return redirect("repas:detail", pk=repas.pk)


@login_required
@require_POST
def adopter_alternative(request, repas_id, alternative_id):
    repas = get_object_or_404(Repas, pk=repas_id, utilisateur=request.user)
    analyse = analyser_repas(repas, request.user)
    proposition = next((a for a in analyse["alternatives"] if a["id"] == alternative_id), None)
    if proposition is None:
        raise Http404("Cette alternative ne correspond pas à ce repas.")

    try:
        with transaction.atomic():
            _, creee = AlternativeAdoptee.objects.get_or_create(
                utilisateur=request.user,
                repas=repas,
                alternative_id=alternative_id,
                defaults={
                    "aliment_original": proposition["aliment"],
                    "remplacement": proposition["remplacement"],
                    "co2_evite": proposition["gains"]["co2"],
                    "eau_economisee": proposition["gains"]["eau"],
                    "terres_preservees": proposition["gains"]["terres"],
                },
            )
    except IntegrityError:
        creee = False
    if creee:
        messages.success(request, "Alternative adoptée : vos économies ont été ajoutées au bilan.")
    else:
        messages.info(request, "Cette alternative figure déjà dans votre bilan.")
    return redirect("repas:detail", pk=repas.pk)
