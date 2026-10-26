"""Estimations nutritionnelles indicatives par portion (valeurs moyennes pour 100 g)."""
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP


# kcal, protéines, glucides, lipides, fibres — moyennes d'aliments cuits/prêts à manger.
REFERENTIEL = (
    (("lentille",), (116, 9.0, 20.1, 0.4, 7.9)),
    (("pois chiche",), (164, 8.9, 27.4, 2.6, 7.6)),
    (("haricot",), (127, 8.7, 22.8, 0.5, 6.4)),
    (("tofu",), (144, 12.0, 2.8, 8.7, 1.0)),
    (("seitan",), (141, 24.7, 12.3, 1.9, 0.6)),
    (("tempeh",), (195, 19.9, 7.6, 11.4, 3.8)),
    (("quinoa",), (120, 4.4, 21.3, 1.9, 2.8)),
    (("riz",), (130, 2.7, 28.2, 0.3, 0.4)),
    (("pate", "pâtes"), (131, 5.0, 25.0, 1.1, 1.8)),
    (("semoule", "couscous"), (112, 3.8, 23.2, 0.2, 1.4)),
    (("pain",), (265, 9.0, 49.0, 3.2, 2.7)),
    (("avoine",), (379, 13.2, 67.7, 6.5, 10.1)),
    (("pomme de terre", "pommes de terre"), (87, 1.9, 20.1, 0.1, 1.8)),
    (("tomate",), (18, 0.9, 3.9, 0.2, 1.2)),
    (("courgette",), (17, 1.2, 3.1, 0.3, 1.0)),
    (("carotte",), (41, 0.9, 9.6, 0.2, 2.8)),
    (("poivron",), (31, 1.0, 6.0, 0.3, 2.1)),
    (("oignon",), (40, 1.1, 9.3, 0.1, 1.7)),
    (("salade", "crudite", "legume", "concombre"), (20, 1.0, 3.5, 0.2, 1.5)),
    (("huile",), (884, 0.0, 0.0, 100.0, 0.0)),
)
NOMS = ("kcal", "proteines", "glucides", "lipides", "fibres")


def normaliser_nom(texte):
    texte = str(texte or "").replace("œ", "oe").replace("Œ", "OE")
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().casefold()


def valeurs_100g(nom, produit=None):
    if produit and all(
        getattr(produit, champ, None) is not None
        for champ in ("calories_100g", "proteines_100g", "glucides_100g", "lipides_100g", "fibres_100g")
    ):
        return tuple(float(getattr(produit, champ)) for champ in (
            "calories_100g", "proteines_100g", "glucides_100g", "lipides_100g", "fibres_100g"
        )), "PRODUIT"
    texte = normaliser_nom(nom)
    for mots, valeurs in REFERENTIEL:
        if any(normaliser_nom(mot) in texte for mot in mots):
            return valeurs, "MOYENNE"
    return (80, 3.0, 12.0, 2.0, 2.0), "MOYENNE"


def calculer_nutrition(ingredients, produits=None):
    """ingredients: dicts nom/quantite_g. produits: mapping facultatif nom normalisé -> produit."""
    totaux = {nom: Decimal("0") for nom in NOMS}
    sources = set()
    produits = produits or {}
    for ingredient in ingredients:
        nom = ingredient.get("nom", "")
        produit = produits.get(normaliser_nom(nom))
        valeurs, source = valeurs_100g(nom, produit)
        sources.add(source)
        facteur = Decimal(str(ingredient.get("quantite_g", 0))) / Decimal("100")
        for cle, valeur in zip(NOMS, valeurs):
            totaux[cle] += Decimal(str(valeur)) * facteur
    resultat = {
        cle: float(valeur.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        for cle, valeur in totaux.items()
    }
    resultat["source"] = "PRODUIT" if sources == {"PRODUIT"} else "ESTIMATION"
    return resultat


def calculer_produit(produit, quantite_g):
    return calculer_nutrition(
        [{"nom": produit.nom, "quantite_g": quantite_g}],
        {normaliser_nom(produit.nom): produit},
    )


def nombre_nutrition(valeur):
    correspondance = re.search(r"\d+(?:[.,]\d+)?", str(valeur or ""))
    return float(correspondance.group().replace(",", ".")) if correspondance else None
