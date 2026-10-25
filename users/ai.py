"""
Analyse IA du profil alimentaire.

Rôle de l'IA dans le module : à partir des habitudes déclarées (régime, aliments
aimés/évités, foyer, temps de cuisine), produire
  - une estimation de l'empreinte hebdomadaire,
  - un objectif CO2 réaliste (pré-rempli dans le profil),
  - des conseils et alternatives végétales adaptés aux goûts.

Chaîne de traitement :
  1. Gemini (API REST, clé dans GEMINI_API_KEY) -> réponse JSON imposée ;
  2. validation stricte de la réponse (schéma + règles métier) ;
  3. repli sur un moteur local déterministe si la clé manque, si l'API échoue
     ou si la réponse est invalide -> l'utilisateur obtient toujours un résultat.
"""
import json
import logging
import time
from decimal import Decimal

import requests
from django.conf import settings

from .models import EMISSIONS_JOUR_PAR_REGIME, ProfilAlimentaire

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class ErreurIA(Exception):
    """Erreur côté fournisseur IA (réseau, quota, réponse invalide…)."""


# Facteurs d'émission (kg CO2e / kg de produit), Poore & Nemecek 2018, Science 360:987.
FACTEURS = {
    "boeuf": 99.5, "agneau": 39.7, "mouton": 39.7, "crevettes": 26.9, "fromage": 23.9,
    "poisson": 13.6, "porc": 12.3, "poulet": 9.9, "dinde": 9.9, "oeufs": 4.7, "lait": 3.2,
    "tofu": 3.2, "pois chiches": 0.9, "lentilles": 0.9, "haricots": 0.9, "fèves": 0.9,
    "champignons": 1.0, "seitan": 1.6, "boisson d'avoine": 0.9, "noix de cajou": 0.4,
    "aubergines": 0.9, "tempeh": 1.0,
}

# mot-clé détecté -> (aliment d'origine, remplacement végétal, idée concrète)
SUBSTITUTIONS = [
    ("couscous", "agneau", "pois chiches", "Couscous aux légumes et pois chiches, harissa et raisins secs"),
    ("merguez", "agneau", "champignons", "Ojja aux champignons et poivrons, sans merguez"),
    ("kafteji", "oeufs", "pois chiches", "Kafteji garni de pois chiches grillés au lieu de l'œuf"),
    ("boeuf", "boeuf", "lentilles", "Bolognaise ou kefta aux lentilles"),
    ("steak", "boeuf", "seitan", "Steak de seitan mariné"),
    ("burger", "boeuf", "haricots", "Burger aux haricots rouges et betterave"),
    ("agneau", "agneau", "pois chiches", "Tajine de pois chiches et légumes"),
    ("mouton", "mouton", "fèves", "Marka aux fèves et petits pois"),
    ("poulet", "poulet", "tofu", "Tofu mariné au citron et cumin, grillé"),
    ("dinde", "dinde", "tempeh", "Escalope de tempeh panée"),
    ("porc", "porc", "seitan", "Émincé de seitan aux oignons"),
    ("crevette", "crevettes", "champignons", "Pleurotes sautées à l'ail façon crevettes"),
    ("poisson", "poisson", "tofu", "Tofu mariné aux algues et citron"),
    ("thon", "poisson", "pois chiches", "Salade de « thon » de pois chiches écrasés"),
    ("fromage", "fromage", "noix de cajou", "Crème de noix de cajou au citron"),
    ("pizza", "fromage", "aubergines", "Pizza aux légumes grillés, moins de fromage"),
    ("lait", "lait", "boisson d'avoine", "Boisson d'avoine dans le café et le porridge"),
    ("oeuf", "oeufs", "tofu", "Tofu brouillé au curcuma"),
    ("brick", "oeufs", "pois chiches", "Brick à la purée de pois chiches et persil"),
]

PAR_DEFAUT = {
    "OMNIVORE_FORT": ["boeuf", "poulet", "fromage"],
    "OMNIVORE": ["boeuf", "poulet", "lait"],
    "FLEXITARIEN": ["poulet", "fromage", "lait"],
    "PESCETARIEN": ["poisson", "fromage", "lait"],
    "VEGETARIEN": ["fromage", "oeuf", "lait"],
    "VEGAN": [],
}

PRODUITS_ANIMAUX = ("boeuf", "agneau", "mouton", "porc", "poulet", "dinde", "poisson", "thon",
                    "crevette", "fromage", "lait", "oeuf", "œuf", "merguez", "viande", "beurre", "miel")
# « lait d'avoine », « fromage végétal », « beurre de cacahuète »… restent végétaux
MARQUEURS_VEGETAUX = ("végétal", "vegetal", "avoine", "amande", "soja", "coco", "cacahu", "riz", "cajou")


# ----------------------------------------------------------------------------- utils
def _contient(texte, mots):
    t = (texte or "").lower()
    return any(m and m in t for m in mots)


def empreinte_hebdo(regime):
    return float((EMISSIONS_JOUR_PAR_REGIME[regime] * 7).quantize(Decimal("0.1")))


def score_durabilite(regime):
    """0 = régime le plus émetteur, 100 = régime végan (échelle Scarborough 2014)."""
    haut, bas = float(EMISSIONS_JOUR_PAR_REGIME["OMNIVORE_FORT"]), float(EMISSIONS_JOUR_PAR_REGIME["VEGAN"])
    val = float(EMISSIONS_JOUR_PAR_REGIME[regime])
    return int(round(100 * (haut - val) / (haut - bas)))


def objectif_recommande(regime):
    """Réduction visée : -25 % (omnivores), -15 % (flexi/pesc./végé), -5 % (végan). Plancher 5 kg."""
    reduction = {"OMNIVORE_FORT": 0.25, "OMNIVORE": 0.25, "VEGAN": 0.05}.get(regime, 0.15)
    return max(5.0, round(empreinte_hebdo(regime) * (1 - reduction), 1))


def fr(x):
    """50.3 -> '50,3' (affichage français)."""
    return f"{x:.1f}".replace(".", ",")


def donnees_profil(profil: ProfilAlimentaire):
    return {
        "regime": profil.regime,
        "regime_libelle": profil.get_regime_display(),
        "aliments_aimes": profil.liste_aimes,
        "aliments_evites": profil.liste_evites,
        "taille_foyer": profil.taille_foyer,
        "niveau_activite": profil.get_niveau_activite_display(),
        "temps_cuisine": profil.get_temps_cuisine_display(),
        "ville": profil.ville,
        "empreinte_estimee_kg": empreinte_hebdo(profil.regime),
    }


# ------------------------------------------------------------------- moteur local
def analyse_locale(d):
    evites = d["aliments_evites"]
    candidats = []
    for aime in d["aliments_aimes"]:
        for mot, origine, remplacement, idee in SUBSTITUTIONS:
            if mot in aime:
                candidats.append((origine, remplacement, idee, aime))
                break
    for mot in PAR_DEFAUT[d["regime"]]:
        for m, origine, remplacement, idee in SUBSTITUTIONS:
            if m == mot:
                candidats.append((origine, remplacement, idee, None))
    alternatives, vus = [], set()
    for origine, remplacement, idee, plat in candidats:
        if origine in vus or _contient(remplacement, evites) or _contient(idee, evites):
            continue
        vus.add(origine)
        alternatives.append({
            "aliment": plat or origine,
            "remplacement": remplacement,
            "idee": idee,
            "economie_kg_par_kg": round(FACTEURS[origine] - FACTEURS[remplacement], 1),
        })
    alternatives = alternatives[:4]

    conseils = []
    if d["regime"] in ("OMNIVORE_FORT", "OMNIVORE"):
        conseils.append("Commencez par 2 journées sans viande par semaine : c'est l'action la plus efficace.")
    if d["regime"] != "VEGAN":
        conseils.append("Privilégiez les légumineuses (lentilles, pois chiches, fèves) : riches en protéines et très peu émettrices.")
    if d["temps_cuisine"].startswith("Moins"):
        conseils.append("Gardez des pois chiches et lentilles en conserve : un repas végétal prêt en 10 minutes.")
    else:
        conseils.append("Cuisinez en grande quantité (batch cooking) et congelez des portions de plats végétaux.")
    if d["taille_foyer"] > 1:
        conseils.append(f"Pour un foyer de {d['taille_foyer']} personnes, planifiez les menus de la semaine pour limiter le gaspillage.")
    conseils.append("Achetez des fruits et légumes de saison, produits localement, au marché.")

    return {
        "resume": (
            f"Votre régime « {d['regime_libelle']} » émet environ {fr(d['empreinte_estimee_kg'])} kg CO₂e par semaine. "
            f"En remplaçant quelques produits animaux par des alternatives végétales, vous pouvez viser "
            f"{fr(objectif_recommande(d['regime']))} kg."
        ),
        "empreinte_estimee_kg": d["empreinte_estimee_kg"],
        "objectif_recommande_kg": objectif_recommande(d["regime"]),
        "score_durabilite": score_durabilite(d["regime"]),
        "conseils": conseils[:5],
        "alternatives": alternatives,
    }


# --------------------------------------------------------------------------- Gemini
def construire_prompt(d):
    return (
        "Tu es un nutritionniste spécialiste de l'alimentation durable en Tunisie et en France. "
        "Analyse ce profil et réponds UNIQUEMENT en JSON, en français, avec exactement les clés : "
        '"resume" (2 phrases), "objectif_recommande_kg" (nombre, kg CO2e/semaine/personne, '
        f"entre 5 et {d['empreinte_estimee_kg']}), "
        '"conseils" (liste de 3 à 5 phrases courtes et concrètes), '
        '"alternatives" (liste de 2 à 4 objets {"aliment", "remplacement", "idee"}: '
        "remplacer un produit animal que la personne aime par une option VÉGÉTALE adaptée à ses goûts). "
        "Ne propose jamais un aliment de la liste « aliments_evites ». "
        f"Profil : {json.dumps(d, ensure_ascii=False)}"
    )


# Codes qui veulent dire « ce modèle est occupé / indisponible » : on essaie le modèle suivant.
CODES_MODELE_SUIVANT = {404, 429, 500, 503, 504}


def modeles_gemini():
    """Modèle principal puis modèles de secours (sans doublon)."""
    noms = [settings.GEMINI_MODEL] + list(getattr(settings, "GEMINI_MODELES_SECOURS", []))
    return list(dict.fromkeys(n for n in noms if n))


def generer(parts, temperature=0.2):
    """
    Appelle Gemini et renvoie le JSON produit. Si un modèle est surchargé (503 « high demand »),
    sans quota (429), introuvable (404) ou trop lent, on passe automatiquement au modèle de secours suivant.
    Une clé refusée (400/401/403) arrête tout de suite : changer de modèle n'y changerait rien.
    """
    if not settings.GEMINI_API_KEY:
        raise ErreurIA("Clé GEMINI_API_KEY absente")
    erreurs = []
    for modele in modeles_gemini():
        try:
            r = requests.post(
                GEMINI_URL.format(model=modele),
                headers={"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
                },
                timeout=getattr(settings, "GEMINI_TIMEOUT_MODELE", settings.GEMINI_TIMEOUT),
            )
        except requests.Timeout:
            erreurs.append(f"{modele} : délai dépassé")
            logger.warning("Gemini %s : délai dépassé, modèle suivant", modele)
            continue
        except requests.RequestException as e:
            raise ErreurIA(f"Erreur réseau/API Gemini : {e.__class__.__name__}") from e
        if r.status_code in CODES_MODELE_SUIVANT:
            erreurs.append(f"{modele} : HTTP {r.status_code}")
            logger.warning("Gemini %s indisponible (HTTP %s), modèle suivant", modele, r.status_code)
            continue
        try:
            r.raise_for_status()                      # clé refusée, requête invalide… : inutile d'insister
        except requests.HTTPError as e:
            raise ErreurIA(f"API Gemini HTTP {r.status_code} : {str(r.text)[:200]}".replace("\n", " ")) from e
        try:
            return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ErreurIA("Réponse Gemini illisible") from e
    if erreurs and all("délai" in e for e in erreurs):
        raise ErreurIA("Délai dépassé pour l'API Gemini (" + " ; ".join(erreurs) + ")")
    raise ErreurIA("Gemini surchargé, tous les modèles ont échoué (" + " ; ".join(erreurs) + ")")


def appeler_gemini(prompt):
    return generer([{"text": prompt}], temperature=0.4)


def valider_resultat(brut, d):
    """Vérifie le schéma et les règles métier. Lève ErreurIA si la réponse est inexploitable."""
    if not isinstance(brut, dict):
        raise ErreurIA("Réponse non JSON-objet")
    try:
        objectif = float(brut["objectif_recommande_kg"])
        conseils = [str(c).strip() for c in brut["conseils"] if str(c).strip()]
        alts = brut["alternatives"]
        resume = str(brut["resume"]).strip()
    except (KeyError, TypeError, ValueError) as e:
        raise ErreurIA("Champs manquants dans la réponse IA") from e
    if not resume or len(conseils) < 2 or not isinstance(alts, list):
        raise ErreurIA("Réponse IA incomplète")
    plafond = d["empreinte_estimee_kg"]
    objectif = round(min(max(objectif, 5.0), plafond), 1)

    propres = []
    for a in alts:
        if not isinstance(a, dict) or not a.get("remplacement"):
            continue
        rempl, idee = str(a["remplacement"]), str(a.get("idee", ""))
        # règles métier : rien d'évité, rien d'animal dans le remplacement
        animal = _contient(rempl, PRODUITS_ANIMAUX) and not _contient(rempl, MARQUEURS_VEGETAUX)
        if _contient(rempl, d["aliments_evites"]) or animal:
            continue
        propres.append({"aliment": str(a.get("aliment", ""))[:80], "remplacement": rempl[:80], "idee": idee[:160]})
    if not propres and d["regime"] != "VEGAN":
        raise ErreurIA("Aucune alternative valide dans la réponse IA")
    return {
        "resume": resume[:500],
        "empreinte_estimee_kg": plafond,
        "objectif_recommande_kg": objectif,
        "score_durabilite": score_durabilite(d["regime"]),
        "conseils": [c[:200] for c in conseils[:5]],
        "alternatives": propres[:4],
    }


def analyser(profil: ProfilAlimentaire):
    """Retourne (resultat, source, erreur, duree_ms). Ne lève jamais : repli local garanti."""
    d = donnees_profil(profil)
    debut = time.perf_counter()
    erreur = ""
    try:
        resultat = valider_resultat(appeler_gemini(construire_prompt(d)), d)
        source = "GEMINI"
    except ErreurIA as e:
        logger.warning("IA indisponible, repli local : %s", e)
        erreur = str(e)[:300]
        resultat = analyse_locale(d)
        source = "LOCAL"
    duree = int((time.perf_counter() - debut) * 1000)
    return resultat, source, erreur, duree
