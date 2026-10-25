from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from .models import AlternativeVegetale, FacteurImpact


ZERO = Decimal("0")
Q2 = Decimal("0.01")
RANG_RISQUE = {"FAIBLE": 1, "MOYEN": 2, "ELEVE": 3}


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
    candidats = AlternativeVegetale.objects.filter(
        categorie_source=element.categorie, actif=True
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
        facteur = facteurs.get(element.categorie)
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
