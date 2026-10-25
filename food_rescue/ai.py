"""Analyse multimodale d'un surplus avec Gemini et repli local gratuit."""
import base64
import json
import unicodedata
from datetime import timedelta

from django.utils import timezone

from users.ai import ErreurIA, generer

from .models import AnnonceSurplus


MOTS_CATEGORIES = {
    AnnonceSurplus.Categorie.FRUITS_LEGUMES: (
        "tomate", "pomme", "orange", "banane", "legume", "fruit", "salade", "courgette", "carotte"
    ),
    AnnonceSurplus.Categorie.BOULANGERIE: ("pain", "baguette", "croissant", "gateau", "patisserie"),
    AnnonceSurplus.Categorie.PLAT_PREPARE: (
        "couscous", "kosksi", "pates", "pizza", "riz", "soupe", "lablabi", "ojja", "plat"
    ),
    AnnonceSurplus.Categorie.PRODUIT_LAITIER: ("lait", "yaourt", "fromage", "beurre", "creme"),
    AnnonceSurplus.Categorie.EPICERIE: ("conserve", "farine", "semoule", "huile", "sucre", "lentille"),
}
ALLERGENES = {
    "gluten": ("pain", "pates", "semoule", "farine", "couscous", "pizza"),
    "lait": ("lait", "fromage", "yaourt", "beurre", "creme"),
    "oeufs": ("oeuf", "omelette", "gateau"),
    "fruits à coque": ("amande", "noix", "pistache", "cacahuete"),
}
FACTEURS_CO2_KG = {
    AnnonceSurplus.Categorie.FRUITS_LEGUMES: 0.9,
    AnnonceSurplus.Categorie.BOULANGERIE: 1.4,
    AnnonceSurplus.Categorie.PLAT_PREPARE: 3.5,
    AnnonceSurplus.Categorie.EPICERIE: 1.8,
    AnnonceSurplus.Categorie.PRODUIT_LAITIER: 6.0,
    AnnonceSurplus.Categorie.AUTRE: 2.5,
}


def _normaliser(texte):
    brut = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    return " ".join(brut.split())


def analyser_localement(annonce):
    texte = _normaliser(f"{annonce.titre} {annonce.description}")
    titre = _normaliser(annonce.titre)
    description = _normaliser(annonce.description)
    scores = {
        categorie: 2 * sum(mot in titre for mot in mots) + sum(mot in description for mot in mots)
        for categorie, mots in MOTS_CATEGORIES.items()
    }
    categorie = max(scores, key=scores.get) if max(scores.values(), default=0) else annonce.categorie
    allergenes = [nom for nom, mots in ALLERGENES.items() if any(mot in texte for mot in mots)]
    restant = annonce.disponible_jusquau - timezone.now()
    if restant <= timedelta(hours=6):
        urgence = "CRITIQUE"
    elif restant <= timedelta(hours=24):
        urgence = "ELEVEE"
    elif restant <= timedelta(days=2):
        urgence = "MOYENNE"
    else:
        urgence = "FAIBLE"
    poids = float(annonce.quantite)
    if annonce.unite == "PORTION":
        poids *= 0.35
    elif annonce.unite == "UNITE":
        poids *= 0.25
    return {
        "categorie": categorie,
        "allergenes_possibles": allergenes,
        "urgence": urgence,
        "confiance": 0.72 if scores.get(categorie, 0) else 0.45,
        "co2_evite_estime": round(poids * FACTEURS_CO2_KG.get(categorie, 2.5), 2),
        "resume": "Analyse locale fondée sur la description et la fenêtre de collecte.",
        "verification_humaine_requise": True,
        "source": "LOCAL",
    }


def _valider(brut, annonce):
    if not isinstance(brut, dict):
        raise ErreurIA("Réponse IA non structurée")
    categorie = str(brut.get("categorie", annonce.categorie)).upper()
    if categorie not in AnnonceSurplus.Categorie.values:
        categorie = annonce.categorie
    urgence = str(brut.get("urgence", "MOYENNE")).upper()
    if urgence not in ("FAIBLE", "MOYENNE", "ELEVEE", "CRITIQUE"):
        urgence = "MOYENNE"
    try:
        confiance = min(1.0, max(0.0, float(brut.get("confiance", 0.5))))
        co2 = max(0.0, min(10000.0, float(brut.get("co2_evite_estime", 0))))
    except (TypeError, ValueError) as exc:
        raise ErreurIA("Scores IA invalides") from exc
    allergenes = brut.get("allergenes_possibles", [])
    if not isinstance(allergenes, list):
        allergenes = []
    return {
        "categorie": categorie,
        "allergenes_possibles": [str(a)[:40] for a in allergenes[:8]],
        "urgence": urgence,
        "confiance": round(confiance, 3),
        "co2_evite_estime": round(co2, 2),
        "resume": str(brut.get("resume", ""))[:300],
        "verification_humaine_requise": True,
        "source": "GEMINI",
    }


def analyser_avec_gemini(annonce):
    prompt = (
        "Tu aides à publier un surplus alimentaire, sans jamais certifier sa sécurité sanitaire. "
        "Analyse les informations et la photo éventuelle. Réponds uniquement en JSON avec: "
        '"categorie" parmi FRUITS_LEGUMES, BOULANGERIE, PLAT_PREPARE, EPICERIE, PRODUIT_LAITIER, AUTRE; '
        '"allergenes_possibles" liste; "urgence" parmi FAIBLE, MOYENNE, ELEVEE, CRITIQUE; '
        '"confiance" entre 0 et 1; "co2_evite_estime" en kg; "resume" court. '
        "Les allergènes sont seulement des alertes à vérifier. Données: "
        + json.dumps({
            "titre": annonce.titre, "description": annonce.description,
            "categorie_declaree": annonce.categorie, "quantite": str(annonce.quantite),
            "unite": annonce.unite, "conservation": annonce.conservation,
            "disponible_jusquau": annonce.disponible_jusquau.isoformat(),
        }, ensure_ascii=False)
    )
    parts = [{"text": prompt}]
    if annonce.photo:
        with annonce.photo.open("rb") as fichier:
            parties_image = base64.b64encode(fichier.read()).decode()
        extension = annonce.photo.name.rsplit(".", 1)[-1].lower()
        mime = "image/png" if extension == "png" else "image/webp" if extension == "webp" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": parties_image}})
    return _valider(generer(parts, temperature=0.1), annonce)


def analyser_surplus(annonce):
    try:
        return analyser_avec_gemini(annonce)
    except ErreurIA as exc:
        resultat = analyser_localement(annonce)
        resultat["erreur_gemini"] = str(exc)[:200]
        return resultat

