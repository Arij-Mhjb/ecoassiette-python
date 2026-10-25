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

from .forms import IngredientExtraitFormSet, RecetteAssistantForm
from .models import AlternativeAdoptee, ExtractionRecetteIA
from .recipe_ai import extraire_recette
from .services import analyser_ingredients, analyser_repas, proposer_alternative


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
    if request.method == "POST":
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
    return render(request, "impact/assistant_recette.html", {"form": form, "apercu": apercu})


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
