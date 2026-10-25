"""
Connaissances « aliments » du module repas (sans IA) :

- détection de la catégorie d'un aliment à partir de son nom (français, tounsi en
  lettres latines ou arabes) ;
- extraction de plusieurs aliments dans une phrase (« klit kosksi b l3allouch w slata ») ;
- portions par défaut quand la quantité n'est pas donnée ;
- remplacements végétaux pour le simulateur « Et si… ».

Si plusieurs catégories correspondent (« couscous au poulet »), on garde la PLUS émettrice :
l'estimation de CO2 reste prudente (on ne sous-estime pas).
"""
import re
import unicodedata

from .models import FACTEURS_CO2

MOTS_CLES = {
    "VIANDE_ROUGE": [
        "boeuf", "agneau", "mouton", "veau", "merguez", "kefta", "steak", "burger", "viande", "viande hachee",
        "osbane", "mloukhia", "kamounia", "chevreau", "jarret",
        # tounsi
        "3allouch", "l3allouch", "allouch", "lham", "l7am", "la7m", "lahm", "osben", "mergaz",
        "علوش", "لحم", "مرقاز", "عصبان", "ملوخية",
    ],
    "VOLAILLE": [
        "poulet", "dinde", "escalope", "chawarma", "shawarma", "nuggets", "cordon bleu", "canard",
        "djej", "djaj", "jej", "dajaj", "دجاج", "جاج",
    ],
    "POISSON": [
        "poisson", "thon", "sardine", "saumon", "crevette", "calamar", "poulpe", "dorade", "loup",
        "maquereau", "fruits de mer", "moule",
        "7out", "hout", "7outa", "sardina", "قمبري", "حوت", "سردينة",
    ],
    "LAITIER": [
        "lait", "fromage", "yaourt", "yogourt", "beurre", "oeuf", "creme", "ricotta", "lben", "rayeb",
        "omelette", "mozzarella", "gruyere",
        "7lib", "hlib", "jben", "3dham", "adham", "3adham", "ya8ourt", "yaghourt",
        "حليب", "جبن", "عظم", "ياغرت", "لبن", "رايب",
    ],
    "LEGUMINEUSE": [
        "lentille", "pois chiche", "haricot", "feve", "lablabi", "houmous", "hummus", "tofu", "soja",
        "jelbana", "petit pois", "tempeh", "falafel",
        "3des", "adess", "7ommos", "hommos", "loubia", "foul", "lablebi",
        "لبلابي", "عدس", "حمص", "لوبيا", "فول", "جلبانة",
    ],
    "FECULENT": [
        "couscous", "semoule", "pain", "pate", "spaghetti", "macaroni", "riz", "mlawi", "chapati", "baguette",
        "frite", "pomme de terre", "lasagne", "pizza", "avoine", "cereale", "mhamsa", "nwasser", "tabouna",
        "bsissa", "quinoa", "boulgour", "brick", "chorba",
        "kosksi", "kousksi", "kseksi", "khobz", "5obz", "ma9rouna", "makrouna", "makarouna", "rouz", "batata",
        "kaskrout", "casse croute", "chapatti", "brik",
        "كسكسي", "خبز", "مقرونة", "رز", "بطاطا", "ملاوي", "شربة", "بريك", "بسيسة",
    ],
    "FRUIT_LEGUME": [
        "salade", "tomate", "legume", "carotte", "courgette", "poivron", "pomme", "orange", "banane", "fraise",
        "datte", "figue", "olive", "mechouia", "aubergine", "epinard", "oignon", "raisin", "pasteque", "melon",
        "fruit", "concombre", "citron", "champignon",
        "slata", "salata", "tmatem", "felfel", "9ra3", "bsal", "dgla", "tmar", "karmous", "ommek houria",
        "سلاطة", "طماطم", "فلفل", "قرع", "بصل", "دقلة", "تمر", "غلال", "خضرة", "مشوية",
    ],
}

# Nom affiché (français) pour les mots tounsi / arabes
NOMS_AFFICHAGE = {
    "3allouch": "agneau", "l3allouch": "agneau", "allouch": "agneau", "علوش": "agneau",
    "lham": "viande", "l7am": "viande", "la7m": "viande", "lahm": "viande", "لحم": "viande",
    "osben": "osbane", "mergaz": "merguez", "مرقاز": "merguez", "عصبان": "osbane", "ملوخية": "mloukhia",
    "djej": "poulet", "djaj": "poulet", "jej": "poulet", "dajaj": "poulet", "دجاج": "poulet", "جاج": "poulet",
    "7out": "poisson", "hout": "poisson", "7outa": "poisson", "حوت": "poisson",
    "sardina": "sardines", "سردينة": "sardines", "قمبري": "crevettes",
    "7lib": "lait", "hlib": "lait", "حليب": "lait", "jben": "fromage", "جبن": "fromage",
    "3dham": "œufs", "adham": "œufs", "3adham": "œufs", "عظم": "œufs",
    "ya8ourt": "yaourt", "yaghourt": "yaourt", "ياغرت": "yaourt", "لبن": "lben", "رايب": "rayeb",
    "3des": "lentilles", "adess": "lentilles", "عدس": "lentilles", "7ommos": "pois chiches",
    "hommos": "pois chiches", "حمص": "pois chiches", "loubia": "haricots", "لوبيا": "haricots",
    "foul": "fèves", "فول": "fèves", "لبلابي": "lablabi", "lablebi": "lablabi", "جلبانة": "petits pois",
    "kosksi": "couscous", "kousksi": "couscous", "kseksi": "couscous", "كسكسي": "couscous",
    "khobz": "pain", "5obz": "pain", "خبز": "pain", "ma9rouna": "pâtes", "makrouna": "pâtes",
    "makarouna": "pâtes", "مقرونة": "pâtes", "rouz": "riz", "رز": "riz", "batata": "pommes de terre",
    "بطاطا": "pommes de terre", "kaskrout": "casse-croûte", "ملاوي": "mlawi",
    "شربة": "chorba", "بريك": "brick", "brik": "brick", "بسيسة": "bsissa",
    "slata": "salade", "salata": "salade", "سلاطة": "salade", "tmatem": "tomates", "طماطم": "tomates",
    "felfel": "poivrons", "فلفل": "poivrons", "9ra3": "courgettes", "قرع": "courgettes", "bsal": "oignons",
    "بصل": "oignons", "dgla": "dattes", "دقلة": "dattes", "tmar": "dattes", "تمر": "dattes",
    "karmous": "figues", "غلال": "fruits", "خضرة": "légumes", "مشوية": "mechouia",
}

# Portion par défaut (g) quand la quantité n'est pas précisée
PORTIONS = {
    "VIANDE_ROUGE": 150, "VOLAILLE": 150, "POISSON": 150, "LAITIER": 100,
    "LEGUMINEUSE": 200, "FECULENT": 250, "FRUIT_LEGUME": 150,
}

# Remplacement végétal par défaut, par catégorie : (aliment, catégorie, idée)
REMPLACEMENTS = {
    "VIANDE_ROUGE": ("lentilles", "LEGUMINEUSE", "Lentilles mijotées aux épices (cumin, carvi, harissa)"),
    "VOLAILLE": ("pois chiches", "LEGUMINEUSE", "Pois chiches rôtis au citron et cumin"),
    "POISSON": ("tofu mariné", "LEGUMINEUSE", "Tofu mariné aux algues et citron"),
    "LAITIER": ("boisson au soja", "LEGUMINEUSE", "Boisson ou yaourt au soja"),
}


def normaliser(texte):
    texte = (texte or "").lower().replace("œ", "oe")
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# mot-clé en mot entier, chaque mot pouvant être au pluriel (-s/-x) : « pommes de terre ».
# En arabe, on accepte les préfixes collés : و / ب / ف / ل / ال (« بالعلوش », « والسلاطة »).
def _motif(mot):
    if mot and not mot[0].isascii():
        return re.compile(r"(?<!\w)(?:[وبفكل]?ال|[وبفكل])?" + re.escape(mot) + r"(?!\w)")
    return re.compile(r"\b" + r"[sx]?\s+".join(map(re.escape, mot.split())) + r"[sx]?\b")


_MOTIFS = [(_motif(normaliser(mot)), cat, mot) for cat, mots in MOTS_CLES.items() for mot in mots]


def deviner_categorie(aliment):
    """Retourne la catégorie la plus émettrice trouvée dans le nom, ou None."""
    nom = normaliser(aliment)
    trouvees = {cat for motif, cat, _ in _MOTIFS if motif.search(nom)}
    if not trouvees:
        return None
    return max(trouvees, key=lambda c: FACTEURS_CO2[c])


def nom_affiche(mot):
    return NOMS_AFFICHAGE.get(mot, mot)


def trouver_aliments(texte):
    """Aliments distincts cités dans un texte, dans l'ordre : [(nom affiché, catégorie)].
    En cas de chevauchement (« pommes de terre » / « pomme »), la correspondance la plus longue gagne."""
    nom = normaliser(texte)
    candidats = [(m.start(), m.end(), nom_affiche(mot), cat)
                 for motif, cat, mot in _MOTIFS for m in motif.finditer(nom)]
    candidats.sort(key=lambda c: c[0] - c[1])          # du plus long au plus court
    retenus, noms = [], set()
    for debut, fin, affiche, cat in candidats:
        if affiche in noms or any(debut < f and d < fin for d, f, _, _ in retenus):
            continue
        retenus.append((debut, fin, affiche, cat))
        noms.add(affiche)
    return [(affiche, cat) for _, _, affiche, cat in sorted(retenus)]


def remplacement_pour(aliment, categorie):
    """(nom, catégorie, idée) d'une alternative végétale, ou None si l'aliment est déjà peu émetteur."""
    if categorie not in REMPLACEMENTS:
        return None
    from users.ai import SUBSTITUTIONS  # idées « tunisiennes » partagées avec l'IA du profil

    nom = normaliser(aliment)
    for mot, _origine, remplacement, idee in SUBSTITUTIONS:
        if mot in nom:
            cat = deviner_categorie(remplacement) or "LEGUMINEUSE"
            if FACTEURS_CO2[cat] < FACTEURS_CO2[categorie]:
                return remplacement, cat, idee
    return REMPLACEMENTS[categorie]


def donnees_js():
    """Données pour l'aperçu en direct dans le formulaire (json_script)."""
    return {"mots": {c: [normaliser(m) for m in ms] for c, ms in MOTS_CLES.items()}, "facteurs": FACTEURS_CO2}
