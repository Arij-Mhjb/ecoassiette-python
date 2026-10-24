"""
Détection automatique de la catégorie d'un aliment à partir de son nom.

Principe : on cherche des mots-clés (avec le pluriel en -s/-x) dans le nom normalisé
(minuscules, sans accents). Si plusieurs catégories correspondent (« couscous au poulet »),
on garde la PLUS émettrice : l'estimation de CO2 reste prudente (on ne sous-estime pas).
La même liste est envoyée au JavaScript du formulaire (aperçu en direct).
"""
import re
import unicodedata

from .models import FACTEURS_CO2

MOTS_CLES = {
    "VIANDE_ROUGE": ["boeuf", "agneau", "mouton", "veau", "merguez", "kefta", "steak", "burger",
                     "viande", "viande hachee", "osbane", "mloukhia", "kamounia", "chevreau", "jarret"],
    "VOLAILLE": ["poulet", "dinde", "escalope", "chawarma", "shawarma", "nuggets", "cordon bleu", "canard"],
    "POISSON": ["poisson", "thon", "sardine", "saumon", "crevette", "calamar", "poulpe", "dorade",
                "loup", "maquereau", "fruits de mer", "moule"],
    "LAITIER": ["lait", "fromage", "yaourt", "yogourt", "beurre", "oeuf", "creme", "ricotta", "lben",
                "rayeb", "omelette", "mozzarella", "gruyere"],
    "LEGUMINEUSE": ["lentille", "pois chiche", "haricot", "feve", "lablabi", "houmous", "hummus", "tofu",
                    "soja", "jelbana", "petit pois", "tempeh", "falafel"],
    "FECULENT": ["couscous", "semoule", "pain", "pate", "spaghetti", "macaroni", "riz", "mlawi", "chapati",
                 "baguette", "frite", "pomme de terre", "lasagne", "pizza", "avoine", "cereale", "mhamsa",
                 "nwasser", "tabouna", "bsissa", "quinoa", "boulgour", "brick", "chorba"],
    "FRUIT_LEGUME": ["salade", "tomate", "legume", "carotte", "courgette", "poivron", "pomme", "orange",
                     "banane", "fraise", "datte", "figue", "olive", "mechouia", "aubergine", "epinard",
                     "oignon", "raisin", "pasteque", "melon", "fruit", "concombre", "citron", "champignon"],
}


def normaliser(texte):
    texte = (texte or "").lower().replace("œ", "oe")
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# mot-clé en mot entier, chaque mot pouvant être au pluriel (-s/-x) : « pommes de terre »
def _motif(mot):
    return re.compile(r"\b" + r"[sx]?\s+".join(map(re.escape, mot.split())) + r"[sx]?\b")


_MOTIFS = [(_motif(mot), cat) for cat, mots in MOTS_CLES.items() for mot in mots]


def deviner_categorie(aliment):
    """Retourne la catégorie la plus émettrice trouvée dans le nom, ou None."""
    nom = normaliser(aliment)
    trouvees = {cat for motif, cat in _MOTIFS if motif.search(nom)}
    if not trouvees:
        return None
    return max(trouvees, key=lambda c: FACTEURS_CO2[c])


def donnees_js():
    """Données pour l'aperçu en direct dans le formulaire (json_script)."""
    return {"mots": MOTS_CLES, "facteurs": FACTEURS_CO2}
