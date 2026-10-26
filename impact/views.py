from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from repas.models import ElementRepas, Repas

from users.ai import ErreurIA

from .forms import GardeMangerForm, IngredientExtraitFormSet, PreuveRepasForm, RecetteAssistantForm
from .models import (
    AlternativeAdoptee, BrouillonRecette, CommandeRecompense, ExtractionRecetteIA, PreuveRepas,
    ProduitRecompense, TransactionPoints,
)
from .recipe_ai import extraire_recette, proposer_recettes_garde_manger
from .nutrition import calculer_produit
from .services import (
    analyser_ingredients, analyser_repas, proposer_alternative, proposer_recette_alternative,
    recommander_produits, solde_points,
)
from .voucher_pdf import generer_bon_pdf


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
        produits_recommandes = recommander_produits(
            donnees.get("aliment", ""), alternative
        ) if donnees and not donnees.get("DELETE") else []
        for recommandation in produits_recommandes:
            recommandation["nutrition"] = calculer_produit(
                recommandation["produit"], donnees.get("quantite_g", 100)
            )
        recette_maison = proposer_recette_alternative(
            donnees.get("aliment", ""), alternative, donnees.get("quantite_g", 100)
        ) if donnees and not donnees.get("DELETE") and alternative else None
        lignes.append({
            "form": formulaire,
            "alternative": alternative,
            "produits_recommandes": produits_recommandes,
            "recette_maison": recette_maison,
        })
    return lignes


def _ingredients_formset(formset):
    return [
        {
            "aliment": f.cleaned_data["aliment"],
            "categorie": f.cleaned_data["categorie"],
            "quantite_g": f.cleaned_data["quantite_g"],
            "utiliser_alternative": bool(f.cleaned_data.get("utiliser_alternative")),
            "produit_alternatif_id": f.cleaned_data.get("produit_alternatif_id"),
        }
        for f in formset.forms if f.is_valid() and not f.cleaned_data.get("DELETE")
    ]


def _contexte_assistant(request, **supplement):
    contexte = {
        "brouillons": BrouillonRecette.objects.filter(utilisateur=request.user)[:10],
    }
    contexte.update(supplement)
    return contexte


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
                "brouillons": BrouillonRecette.objects.filter(utilisateur=request.user)[:10],
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
                brouillon = BrouillonRecette.objects.create(
                    utilisateur=request.user,
                    type_repas=form.cleaned_data["type_repas"],
                    date=form.cleaned_data["date"],
                    note=form.cleaned_data["note"],
                    texte_original=form.cleaned_data["texte"],
                    source=source,
                    ingredients=ingredients,
                )
                apercu = {
                    "formset": formset,
                    "lignes": _lignes_apercu(formset, request.user),
                    "analyse": analyse,
                    "source": source,
                    "erreur_ia": erreur,
                    "brouillon": brouillon,
                }
    else:
        form = RecetteAssistantForm()
    return render(request, "impact/assistant_recette.html", {
        "form": form, "apercu": apercu, "garde_form": garde_form,
        "recettes_garde_manger": recettes_garde_manger,
        "brouillons": BrouillonRecette.objects.filter(utilisateur=request.user)[:10],
    })


@login_required
def reprendre_brouillon(request, brouillon_id):
    brouillon = get_object_or_404(BrouillonRecette, pk=brouillon_id, utilisateur=request.user)
    form = RecetteAssistantForm(initial={
        "type_repas": brouillon.type_repas,
        "date": brouillon.date,
        "note": brouillon.note,
        "texte": brouillon.texte_original,
    })
    formset = IngredientExtraitFormSet(initial=brouillon.ingredients, prefix="ingredients")
    analyse = analyser_ingredients(brouillon.ingredients, request.user) if brouillon.ingredients else None
    apercu = {
        "formset": formset,
        "lignes": _lignes_apercu(formset, request.user),
        "analyse": analyse,
        "source": brouillon.source,
        "brouillon": brouillon,
    }
    return render(request, "impact/assistant_recette.html", _contexte_assistant(
        request, form=form, apercu=apercu, garde_form=GardeMangerForm(),
        recettes_garde_manger=None,
    ))


@login_required
@require_POST
def supprimer_brouillon(request, brouillon_id):
    brouillon = get_object_or_404(BrouillonRecette, pk=brouillon_id, utilisateur=request.user)
    brouillon.delete()
    messages.success(request, "Brouillon supprimé.")
    return redirect("impact:assistant_recette")


@login_required
def portefeuille(request):
    solde = solde_points(request.user)
    produits = list(ProduitRecompense.objects.filter(
        statut=ProduitRecompense.Statut.PUBLIE, sponsor__actif=True
    ).select_related("sponsor"))
    for produit in produits:
        produit.points_manquants = max(0, produit.cout_points - solde)
    return render(request, "impact/portefeuille.html", {
        "solde": solde, "produits": produits,
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
        initial = {}
        repas_id = request.GET.get("repas")
        if repas_id and Repas.objects.filter(
            pk=repas_id, utilisateur=request.user, preuve_ecologique__isnull=True,
        ).exists():
            initial["repas"] = repas_id
        form = PreuveRepasForm(utilisateur=request.user, initial=initial)
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
    messages.success(
        request,
        "Récompense réservée. Votre bon PDF avec QR code est disponible dans le portefeuille.",
    )
    return redirect("impact:portefeuille")


@login_required
def telecharger_bon(request, commande_id):
    commande = get_object_or_404(
        CommandeRecompense.objects.select_related("produit__sponsor"),
        pk=commande_id, utilisateur=request.user,
    )
    url_verification = request.build_absolute_uri(
        reverse("impact:verifier_bon", args=[commande.code_bon])
    )
    contenu = generer_bon_pdf(commande, url_verification)
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="bon-{commande.code_bon}.pdf"'
    return reponse


@require_http_methods(["GET", "POST"])
def verifier_bon(request, code):
    commande = get_object_or_404(
        CommandeRecompense.objects.select_related("produit__sponsor", "utilisateur"),
        code_bon=code,
    )
    if request.method == "POST":
        if not request.user.is_authenticated or not request.user.is_staff:
            raise PermissionDenied("Seul un partenaire autorisé peut valider ce bon.")
        if commande.statut == CommandeRecompense.Statut.CONFIRMEE:
            commande.statut = CommandeRecompense.Statut.UTILISEE
            commande.utilise_le = timezone.now()
            commande.save(update_fields=["statut", "utilise_le"])
            messages.success(request, "Bon validé. La remise peut être appliquée.")
    return render(request, "impact/verifier_bon.html", {"commande": commande})


@login_required
@require_POST
def valider_recette(request):
    form = RecetteAssistantForm(request.POST)
    formset = IngredientExtraitFormSet(request.POST, prefix="ingredients")
    brouillon = None
    if request.POST.get("brouillon_id"):
        brouillon = get_object_or_404(
            BrouillonRecette, pk=request.POST["brouillon_id"], utilisateur=request.user
        )
    if not (form.is_valid() and formset.is_valid()):
        lignes = _lignes_apercu(formset, request.user)
        ingredients_valides = [
            f.cleaned_data for f in formset.forms if f.is_valid() and not f.cleaned_data.get("DELETE")
        ]
        analyse = analyser_ingredients(ingredients_valides, request.user) if ingredients_valides else None
        return render(request, "impact/assistant_recette.html", {
            "form": form,
            "apercu": {"formset": formset, "lignes": lignes, "analyse": analyse, "source": request.POST.get("source", "LOCAL"), "brouillon": brouillon},
            "brouillons": BrouillonRecette.objects.filter(utilisateur=request.user)[:10],
        }, status=400)

    source = request.POST.get("source")
    if source not in ExtractionRecetteIA.Source.values:
        source = ExtractionRecetteIA.Source.LOCAL

    ingredients_valides = _ingredients_formset(formset)
    if request.POST.get("action") == "enregistrer_brouillon":
        if brouillon is None:
            brouillon = BrouillonRecette(utilisateur=request.user)
        brouillon.type_repas = form.cleaned_data["type_repas"]
        brouillon.date = form.cleaned_data["date"]
        brouillon.note = form.cleaned_data["note"]
        brouillon.texte_original = form.cleaned_data["texte"]
        brouillon.source = source
        brouillon.ingredients = ingredients_valides
        brouillon.save()
        messages.success(request, "Brouillon enregistré. Vous pourrez reprendre l'analyse plus tard.")
        return redirect("impact:reprendre_brouillon", brouillon_id=brouillon.pk)

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
            produit_utilise = None
            produit_id = d.get("produit_alternatif_id")
            if produit_id and alternative:
                produit_utilise = next(
                    (
                        recommandation["produit"]
                        for recommandation in recommander_produits(aliment, alternative)
                        if recommandation["produit"].pk == produit_id
                    ),
                    None,
                )
            if (d.get("utiliser_alternative") or produit_utilise) and alternative:
                analyse_ligne = analyser_ingredients([{
                    "aliment": aliment, "categorie": categorie, "quantite_g": d["quantite_g"],
                }], request.user)
                proposition = next(
                    (a for a in analyse_ligne["alternatives"] if a["id"] == alternative.pk), None
                )
                if proposition:
                    remplacement = produit_utilise.nom if produit_utilise else alternative.remplacement
                    adoptions.append((alternative, aliment, remplacement, proposition, produit_utilise))
                    aliment = remplacement
                    categorie = alternative.facteur_remplacement.categorie
            ElementRepas.objects.create(
                repas=repas, aliment=aliment, categorie=categorie, quantite_g=d["quantite_g"]
            )
        noms_generiques = {
            "", "Recette analysée par IA", "Poêlée végétale du garde-manger",
            "Bowl végétal anti-gaspillage",
        }
        if repas.note.strip() in noms_generiques and adoptions:
            origines = " ".join(original.casefold() for _, original, _, _, _ in adoptions)
            produit_burger = any(
                produit and "burger" in produit.nom.casefold()
                for _, _, _, _, produit in adoptions
            )
            if "cheeseburger" in origines:
                repas.note = "Cheeseburger veggie"
            elif "hamburger" in origines or produit_burger:
                repas.note = "Hamburger veggie"
            elif "burger" in origines:
                repas.note = "Burger veggie"
            elif "steak" in origines:
                repas.note = "Steak veggie"
            else:
                repas.note = f"Repas végétal aux {adoptions[0][2]}"[:200]
            repas.save(update_fields=["note"])
        ExtractionRecetteIA.objects.create(
            utilisateur=request.user, repas=repas,
            texte_original=form.cleaned_data["texte"], source=source,
        )
        for alternative, original, remplacement, proposition, produit_utilise in adoptions:
            AlternativeAdoptee.objects.create(
                utilisateur=request.user, repas=repas, alternative=alternative,
                aliment_original=original, remplacement=remplacement,
                produit_utilise=produit_utilise,
                co2_evite=proposition["gains"]["co2"],
                eau_economisee=proposition["gains"]["eau"],
                terres_preservees=proposition["gains"]["terres"],
            )
        if brouillon:
            brouillon.delete()
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
