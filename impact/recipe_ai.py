"""Extraction structurée d'une recette par Gemini, avec repli local déterministe."""
import json
import re

from users.ai import ErreurIA, appeler_gemini


CATEGORIES = {
    "VIANDE_ROUGE": ("boeuf", "bœuf", "agneau", "mouton", "porc", "viande", "merguez", "steak"),
    "VOLAILLE": ("poulet", "dinde", "volaille"),
    "POISSON": ("poisson", "thon", "saumon", "sardine", "crevette", "fruits de mer"),
    "LAITIER": ("lait", "fromage", "yaourt", "beurre", "crème", "creme", "oeuf", "œuf"),
    "LEGUMINEUSE": ("lentille", "pois chiche", "haricot", "fève", "feve", "tofu", "soja", "seitan", "tempeh"),
    "FECULENT": ("riz", "pâte", "pate", "semoule", "couscous", "pain", "pomme de terre", "quinoa", "avoine"),
    "FRUIT_LEGUME": ("tomate", "carotte", "courgette", "aubergine", "oignon", "ail", "poivron", "salade", "pomme", "banane", "citron", "légume", "legume", "fruit", "champignon"),
}

POIDS_UNITE = {"kg": 1000, "g": 1, "gramme": 1, "grammes": 1, "l": 1000, "litre": 1000, "litres": 1000, "ml": 1}
POIDS_PIECE = {"tomate": 120, "oignon": 100, "carotte": 80, "courgette": 200, "aubergine": 300, "oeuf": 60, "œuf": 60, "citron": 80}


def categoriser(nom):
    texte = nom.casefold()
    for categorie, mots in CATEGORIES.items():
        if any(mot in texte for mot in mots):
            return categorie
    return "FRUIT_LEGUME"


def _nettoyer_nom(nom):
    nom = re.sub(r"\b(de|du|des|d'|environ|haché(?:e)?s?|coupé(?:e)?s?|émincé(?:e)?s?)\b", " ", nom, flags=re.I)
    nom = re.sub(r"[^a-zA-ZÀ-ÿœŒ' -]", " ", nom)
    return re.sub(r"\s+", " ", nom).strip(" -.,").lower()[:100]


def extraire_localement(texte):
    morceaux = re.split(r"[,;\n]+", texte)
    resultat = []
    motif = re.compile(
        r"(?P<q>\d+(?:[.,]\d+)?)\s*(?P<u>kg|g|grammes?|ml|litres?|pièces?|pieces?)?\s*(?:de\s+|d')?(?P<n>.+)", re.I
    )
    for morceau in morceaux:
        # Une introduction comme « Couscous pour 2 : 300 g d'agneau » ne doit
        # pas transformer « 2 personnes » en ingrédient.
        morceau = morceau.rsplit(":", 1)[-1]
        correspondance = motif.search(morceau.strip())
        if not correspondance:
            continue
        nom = _nettoyer_nom(correspondance.group("n"))
        if not nom or len(nom) < 2:
            continue
        quantite = float(correspondance.group("q").replace(",", "."))
        unite = (correspondance.group("u") or "piece").casefold()
        if unite.startswith("pi") or unite == "piece":
            poids = next((val for mot, val in POIDS_PIECE.items() if mot in nom), 100)
            grammes = round(quantite * poids)
        else:
            grammes = round(quantite * POIDS_UNITE.get(unite, 1))
        if 1 <= grammes <= 3000:
            resultat.append({"aliment": nom, "categorie": categoriser(nom), "quantite_g": grammes})
    return resultat[:20]


def _valider_ingredients(brut):
    if not isinstance(brut, dict) or not isinstance(brut.get("ingredients"), list):
        raise ErreurIA("Liste d'ingrédients absente")
    resultat = []
    for valeur in brut["ingredients"][:20]:
        try:
            nom = _nettoyer_nom(str(valeur["aliment"]))
            grammes = int(round(float(valeur["quantite_g"])))
            categorie = str(valeur.get("categorie") or categoriser(nom))
        except (KeyError, TypeError, ValueError):
            continue
        if categorie not in CATEGORIES:
            categorie = categoriser(nom)
        if nom and 1 <= grammes <= 3000:
            resultat.append({"aliment": nom, "categorie": categorie, "quantite_g": grammes})
    if not resultat:
        raise ErreurIA("Aucun ingrédient exploitable")
    return resultat


def extraire_recette(texte):
    prompt = (
        "Extrais les ingrédients et leurs quantités de cette recette. Réponds uniquement en JSON sous la forme "
        '{"ingredients":[{"aliment":"nom simple","quantite_g":150,"categorie":"FECULENT"}]}. '
        "Convertis kg, litres et pièces en grammes estimés. La catégorie doit être exactement parmi : "
        f"{', '.join(CATEGORIES)}. Ignore les durées, températures et instructions. Recette : {json.dumps(texte, ensure_ascii=False)}"
    )
    try:
        return _valider_ingredients(appeler_gemini(prompt)), "GEMINI", ""
    except ErreurIA as erreur:
        ingredients = extraire_localement(texte)
        if not ingredients:
            raise ErreurIA(
                "Aucun ingrédient avec quantité n'a été détecté. Exemple attendu : 200 g de poulet, 2 tomates."
            ) from erreur
        return ingredients, "LOCAL", str(erreur)[:200]
