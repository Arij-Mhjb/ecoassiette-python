from decimal import Decimal, ROUND_HALF_UP
import re
from types import SimpleNamespace
import unicodedata
from urllib.parse import quote_plus

from django.db.models import Sum
from django.db import transaction
from django.utils import timezone

from .models import (
    AlternativeVegetale, FacteurImpact, PreuveRepas, ProduitRecompense, TransactionPoints,
)


ZERO = Decimal("0")
Q2 = Decimal("0.01")
RANG_RISQUE = {"FAIBLE": 1, "MOYEN": 2, "ELEVE": 3}
MOTS_PRODUIT_IGNORES = {
    "avec", "dans", "de", "des", "du", "et", "la", "le", "les", "pour",
    "produit", "produits", "vegetal", "vegetale", "vegan", "vegane",
}
MARQUEURS_PAIN_BURGER = ("pain burger", "pain hamburger", "burger bun", "bun burger")
MARQUEURS_PLAT_CARNE = (
    "hamburger", "cheeseburger", "burger", "steak", "viande hache", "boulette de viande",
)


def _normaliser_recherche(texte):
    texte = str(texte or "").replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", texte.casefold()))


def _termes_recherche(texte):
    return {
        mot for mot in _normaliser_recherche(texte).split()
        if len(mot) >= 3 and mot not in MOTS_PRODUIT_IGNORES
    }


def _est_pain_burger(aliment):
    texte = _normaliser_recherche(aliment)
    return any(expression in texte for expression in MARQUEURS_PAIN_BURGER)


def _categorie_semantique(aliment, categorie):
    texte = _normaliser_recherche(aliment)
    if _est_pain_burger(texte):
        return "FECULENT"
    if any(expression in texte for expression in MARQUEURS_PLAT_CARNE):
        return "VIANDE_ROUGE"
    return categorie


def recommander_produits(aliment, alternative=None, limite=3):
    """Classe les produits végétaux disponibles selon l'ingrédient détecté par l'assistant."""
    if _est_pain_burger(aliment):
        return []
    origine = _normaliser_recherche(aliment)
    remplacement = _normaliser_recherche(
        alternative.remplacement if alternative is not None else ""
    )
    termes_cibles = _termes_recherche(f"{origine} {remplacement}")
    recommandations = []
    produits = ProduitRecompense.objects.filter(
        statut=ProduitRecompense.Statut.PUBLIE,
        produit_vegetal=True,
        stock__gt=0,
        sponsor__actif=True,
    ).select_related("sponsor")

    for produit in produits:
        mots_cles = [
            _normaliser_recherche(mot)
            for mot in produit.mots_cles_recommandation.split(",") if mot.strip()
        ]
        texte_produit = _normaliser_recherche(
            f"{produit.nom} {produit.description} {' '.join(mots_cles)}"
        )
        termes_produit = _termes_recherche(texte_produit)
        score = 0
        raisons = []
        if origine and any(origine == mot or origine in mot or mot in origine for mot in mots_cles):
            score += 100
            raisons.append(f"correspond à « {aliment} »")
        elif origine and origine in texte_produit:
            score += 70
            raisons.append(f"correspond à « {aliment} »")
        if remplacement and remplacement in texte_produit:
            score += 45
            raisons.append(f"contient l'alternative « {alternative.remplacement} »")
        score += 12 * len(termes_cibles & termes_produit)
        if score > 0:
            recommandations.append({
                "produit": produit,
                "score": score,
                "raison": " et ".join(raisons) or "recommandé selon les ingrédients détectés",
            })

    recommandations.sort(key=lambda item: (-item["score"], item["produit"].nom.casefold()))
    return recommandations[:limite]


def proposer_recette_alternative(aliment, alternative, quantite_g):
    """Construit une préparation maison portionnée à partir de l'alternative retenue."""
    if not alternative:
        return None
    quantite = max(1, int(quantite_g or 100))
    source = _normaliser_recherche(aliment)
    remplacement = _normaliser_recherche(alternative.remplacement)
    burger = any(mot in source for mot in ("burger", "hamburger", "steak", "viande hache")) or (
        "boeuf" in source and remplacement in {"lentilles", "haricots", "pois chiches"}
    )

    if burger:
        base = alternative.remplacement
        ingredients = [
            (base, quantite),
            ("flocons d'avoine", max(15, round(quantite * 0.18))),
            ("oignon", max(20, round(quantite * 0.20))),
            ("huile végétale", max(5, round(quantite * 0.05))),
        ]
        nom = f"Burger végan maison aux {base}"
        etapes = [
            f"Écrasez les {base} puis mélangez-les avec l'oignon finement coupé.",
            "Ajoutez les flocons d'avoine, du paprika, du cumin, du sel et du poivre.",
            "Formez un steak et laissez-le reposer 10 minutes.",
            "Faites cuire 4 à 5 minutes de chaque côté dans une poêle légèrement huilée.",
        ]
    elif "tofu" in remplacement or "seitan" in remplacement:
        ingredients = [
            (alternative.remplacement, quantite),
            ("sauce soja", max(10, round(quantite * 0.10))),
            ("huile végétale", max(5, round(quantite * 0.05))),
            ("épices", max(2, round(quantite * 0.02))),
        ]
        nom = f"{alternative.remplacement.capitalize()} mariné maison"
        etapes = [
            f"Découpez le {alternative.remplacement} en morceaux réguliers.",
            "Mélangez la sauce soja, l'huile et les épices, puis marinez 10 minutes.",
            "Faites dorer à la poêle jusqu'à obtenir une surface croustillante.",
        ]
    else:
        ingredients = [
            (alternative.remplacement, quantite),
            ("oignon", max(20, round(quantite * 0.20))),
            ("tomates", max(40, round(quantite * 0.35))),
            ("épices", max(2, round(quantite * 0.02))),
        ]
        nom = f"Alternative maison aux {alternative.remplacement}"
        etapes = [
            "Faites revenir l'oignon avec les épices.",
            f"Ajoutez les {alternative.remplacement} et les tomates.",
            "Laissez mijoter jusqu'à obtenir la texture souhaitée, puis rectifiez l'assaisonnement.",
        ]

    recherche_video = quote_plus(f"recette {nom} facile en français")
    return {
        "nom": nom,
        "ingredients": [{"nom": nom_i, "quantite_g": poids} for nom_i, poids in ingredients],
        "etapes": etapes,
        "video_url": f"https://www.youtube.com/results?search_query={recherche_video}",
        "remplacement": alternative.remplacement,
    }


def solde_points(utilisateur):
    return TransactionPoints.objects.filter(utilisateur=utilisateur).aggregate(
        total=Sum("montant")
    )["total"] or 0


def crediter_preuve(preuve):
    """Approuve et crédite une preuve exactement une fois. Retourne (créé, points)."""
    with transaction.atomic():
        preuve = PreuveRepas.objects.select_for_update().select_related("repas").get(pk=preuve.pk)
        transaction_existante = TransactionPoints.objects.filter(preuve=preuve).first()
        if transaction_existante:
            return False, transaction_existante.montant
        co2 = sum(a.co2_evite for a in preuve.repas.alternatives_adoptees.all())
        points = 50 + min(150, int(co2 * 10))
        preuve.statut = PreuveRepas.Statut.APPROUVEE
        preuve.points_attribues = points
        preuve.traitee_le = timezone.now()
        preuve.save(update_fields=["statut", "points_attribues", "traitee_le"])
        TransactionPoints.objects.create(
            utilisateur=preuve.utilisateur, montant=points,
            motif=f"Preuve validée pour le repas #{preuve.repas_id}", preuve=preuve,
        )
        return True, points


def _arrondir(valeur):
    return Decimal(valeur).quantize(Q2, rounding=ROUND_HALF_UP)


def _impact(quantite_g, facteur):
    kg = Decimal(quantite_g) / Decimal("1000")
    return {
        "co2": kg * facteur.co2_kg_par_kg,
        "eau": kg * facteur.eau_litres_par_kg,
        "terres": kg * facteur.terres_m2_par_kg,
    }


def _mots_evites(utilisateur):
    try:
        texte = utilisateur.profil.aliments_evites or ""
    except (AttributeError, ObjectDoesNotExist):
        texte = ""
    return {mot.strip().casefold() for mot in texte.replace(";", ",").split(",") if mot.strip()}


# Import tardif évitant une dépendance Django au chargement du module.
from django.core.exceptions import ObjectDoesNotExist  # noqa: E402


def _alternative_pour(element, evites):
    categorie = _categorie_semantique(element.aliment, element.categorie)
    candidats = AlternativeVegetale.objects.filter(
        categorie_source=categorie, actif=True
    ).select_related("facteur_remplacement")
    nom = element.aliment.casefold()
    correspondances = [a for a in candidats if a.aliment_source and a.aliment_source.casefold() in nom]
    generiques = [a for a in candidats if not a.aliment_source]
    for alternative in correspondances + generiques:
        remplacement = alternative.remplacement.casefold()
        if not any(evite in remplacement or remplacement in evite for evite in evites):
            return alternative
    return None


def proposer_alternative(aliment, categorie, utilisateur=None):
    """Retourne une alternative autorisée pour un ingrédient, ou None."""
    evites = _mots_evites(utilisateur) if utilisateur else set()
    return _alternative_pour(SimpleNamespace(aliment=aliment, categorie=categorie), evites)


def analyser_ingredients(ingredients, utilisateur=None):
    """Analyse une liste de dicts aliment/categorie/quantite_g, même avant enregistrement."""
    elements = [SimpleNamespace(**ingredient) for ingredient in ingredients]
    return _analyser_elements(elements, utilisateur)


def _analyser_elements(elements, utilisateur=None):
    facteurs = {f.categorie: f for f in FacteurImpact.objects.all()}
    evites = _mots_evites(utilisateur) if utilisateur else set()
    totaux = {"co2": ZERO, "eau": ZERO, "terres": ZERO}
    economies = {"co2": ZERO, "eau": ZERO, "terres": ZERO}
    alternatives = []
    risque_max = "FAIBLE"

    for element in elements:
        categorie = _categorie_semantique(element.aliment, element.categorie)
        facteur = facteurs.get(categorie)
        if not facteur:
            continue
        actuel = _impact(element.quantite_g, facteur)
        for cle in totaux:
            totaux[cle] += actuel[cle]
        if RANG_RISQUE[facteur.risque_deforestation] > RANG_RISQUE[risque_max]:
            risque_max = facteur.risque_deforestation

        alternative = _alternative_pour(element, evites)
        if not alternative:
            continue
        propose = _impact(element.quantite_g, alternative.facteur_remplacement)
        gains = {cle: max(ZERO, actuel[cle] - propose[cle]) for cle in economies}
        for cle in economies:
            economies[cle] += gains[cle]
        alternatives.append({
            "id": alternative.pk,
            "aliment": element.aliment,
            "remplacement": alternative.remplacement,
            "categorie_remplacement": alternative.facteur_remplacement.categorie,
            "idee": alternative.idee,
            "quantite_g": element.quantite_g,
            "gains": {cle: _arrondir(valeur) for cle, valeur in gains.items()},
        })

    libelles = dict(FacteurImpact.RisqueDeforestation.choices)
    return {
        "totaux": {cle: _arrondir(valeur) for cle, valeur in totaux.items()},
        "economies": {cle: _arrondir(valeur) for cle, valeur in economies.items()},
        "alternatives": alternatives,
        "risque_deforestation": libelles.get(risque_max, "Faible"),
        "a_des_donnees": bool(facteurs),
    }


def analyser_repas(repas, utilisateur=None):
    """Calcule l'impact du repas et les gains possibles avec des substitutions végétales."""
    return _analyser_elements(repas.elements.all(), utilisateur)
