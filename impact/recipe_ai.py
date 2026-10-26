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

# Portions indicatives pour un repas adulte. L'utilisateur peut les corriger
# dans le brouillon avant d'enregistrer le repas.
PORTIONS_G = {
    "tofu": 150, "seitan": 150, "tempeh": 150,
    "pois chiche": 160, "lentille": 160, "haricot": 160, "fève": 160,
    "riz": 100, "pâte": 100, "pate": 100, "semoule": 100, "quinoa": 100,
    "cajou": 25, "noix": 25, "amande": 25,
    "tomate": 120, "courgette": 180, "aubergine": 200, "oignon": 60,
    "oignion": 60, "carotte": 100, "poivron": 120, "champignon": 150,
}


def categoriser(nom):
    texte = nom.casefold()
    # Comprendre le rôle de « burger » : le pain est un féculent, tandis que
    # le plat/steak burger est traité comme une viande à végétaliser.
    if any(expression in texte for expression in ("pain burger", "pain hamburger", "burger bun", "bun burger")):
        return "FECULENT"
    if any(expression in texte for expression in ("hamburger", "cheeseburger", "burger", "steak haché", "steak hache")):
        return "VIANDE_ROUGE"
    for categorie, mots in CATEGORIES.items():
        if any(mot in texte for mot in mots):
            return categorie
    return "FRUIT_LEGUME"


def _nettoyer_nom(nom):
    nom = re.sub(r"\b(de|du|des|d'|environ|haché(?:e)?s?|coupé(?:e)?s?|émincé(?:e)?s?)\b", " ", nom, flags=re.I)
    nom = re.sub(r"[^a-zA-ZÀ-ÿœŒ' -]", " ", nom)
    return re.sub(r"\s+", " ", nom).strip(" -.,").lower()[:100]


def _quantite_portion(nom):
    texte = nom.casefold()
    return next((grammes for mot, grammes in PORTIONS_G.items() if mot in texte), 120)


def _quantifier_ingredients(ingredients):
    """Garantit « N g de produit » pour que l'extracteur suivant soit fiable."""
    resultat = []
    for valeur in ingredients:
        texte = str(valeur).strip()
        if not texte:
            continue
        extraits = extraire_localement(texte)
        if extraits:
            ingredient = extraits[0]
            article = "d'" if ingredient["aliment"][:1].casefold() in "aeiouyh" else "de "
            resultat.append(f"{ingredient['quantite_g']} g {article}{ingredient['aliment']}")
        else:
            nom = _nettoyer_nom(texte)
            if nom:
                article = "d'" if nom[:1].casefold() in "aeiouyh" else "de "
                resultat.append(f"{_quantite_portion(nom)} g {article}{nom}")
    return resultat[:12]


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


def proposer_recettes_garde_manger(texte, profil=None):
    """Propose des recettes végétales à partir d'ingrédients disponibles."""
    evites = getattr(profil, "aliments_evites", "") if profil else ""
    prompt = (
        "Propose exactement 3 recettes écologiques et végétales POUR UNE PERSONNE en utilisant en priorité les ingrédients disponibles. "
        "Chaque ingrédient doit obligatoirement avoir une quantité en grammes adaptée à un repas. "
        "Réponds uniquement en JSON : "
        '{"recettes":[{"nom":"...","ingredients":["150 g ..."],"etapes":["..."],"raison_ecologique":"..."}]}. '
        f"N'utilise aucun aliment évité ({evites}). Ingrédients disponibles : {json.dumps(texte, ensure_ascii=False)}"
    )
    try:
        brut = appeler_gemini(prompt)
        recettes = brut.get("recettes", []) if isinstance(brut, dict) else []
        propres = []
        for recette in recettes[:3]:
            if not isinstance(recette, dict) or not recette.get("nom") or not recette.get("ingredients"):
                continue
            ingredients_quantifies = _quantifier_ingredients(recette["ingredients"])
            if not ingredients_quantifies:
                continue
            propres.append({
                "nom": str(recette["nom"])[:120],
                "ingredients": ingredients_quantifies,
                "etapes": [str(x)[:250] for x in recette.get("etapes", [])[:8]],
                "raison_ecologique": str(recette.get("raison_ecologique", ""))[:300],
            })
        if propres:
            return propres, "GEMINI"
    except ErreurIA:
        pass

    noms = [x.strip() for x in re.split(r"[,;\n]+|\s+et\s+", texte, flags=re.I) if x.strip()][:10]
    ingredients = _quantifier_ingredients(noms)
    base = ", ".join(noms) or "légumes disponibles"
    return [
        {"nom": "Poêlée végétale du garde-manger", "ingredients": ingredients,
         "etapes": [f"Coupez et faites revenir {base} avec des épices.", "Ajoutez une légumineuse si disponible."],
         "raison_ecologique": "Utilise les produits déjà disponibles et limite le gaspillage."},
        {"nom": "Bowl végétal anti-gaspillage", "ingredients": ingredients,
         "etapes": [f"Cuisez puis assemblez {base}.", "Assaisonnez avec citron, huile et herbes."],
         "raison_ecologique": "Repas végétal adaptable qui valorise les restes."},
    ], "LOCAL"
