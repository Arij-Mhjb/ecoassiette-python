"""
IA du module repas : transformer une PHOTO d'assiette ou une PHRASE (français / tounsi)
en liste d'aliments prête à enregistrer.

- Photo : Gemini multimodal (image envoyée en base64). Pas de repli possible sans IA :
  on renvoie une erreur claire et l'utilisateur saisit à la main.
- Texte / voix : Gemini, avec repli local (mots-clés français + tounsi + portions par défaut)
  si l'API est indisponible.

La réponse de Gemini est toujours validée (catégories connues, quantités bornées) :
on ne fait jamais confiance aveuglément à un modèle génératif.
"""
import base64
import re
import time

from django.utils import timezone

from users.ai import ErreurIA, generer

from .categories import PORTIONS, deviner_categorie, normaliser, trouver_aliments
from .models import FACTEURS_CO2, Repas

MAX_ALIMENTS = 8
CATEGORIES = ", ".join(FACTEURS_CO2)

CONSIGNE = (
    "Tu es un assistant de suivi alimentaire. Réponds UNIQUEMENT en JSON avec les clés : "
    '"type_repas" (une valeur parmi PETIT_DEJ, DEJEUNER, DINER, COLLATION, ou null), '
    '"description" (une phrase courte en français), '
    '"aliments" : liste (au plus 8) d\'objets {"aliment": nom court en français, '
    f'"categorie": une valeur parmi {CATEGORIES}, '
    '"quantite_g": estimation entière en grammes pour UNE personne}. '
    "Sépare les composants d'un plat (ex. couscous à l'agneau = couscous + agneau + légumes). "
    "Ignore l'eau, le sel, les épices et l'huile."
)


def _appeler_gemini(parts):
    """Gemini avec bascule automatique vers un modèle de secours si le principal est surchargé."""
    return generer(parts, temperature=0.2)


def type_selon_heure(maintenant=None):
    h = timezone.localtime(maintenant).hour if maintenant else timezone.localtime().hour
    if 5 <= h < 11:
        return "PETIT_DEJ"
    if 11 <= h < 16:
        return "DEJEUNER"
    if 16 <= h < 19:
        return "COLLATION"
    return "DINER"


def valider(brut):
    """Nettoie la réponse (de Gemini ou du moteur local). Lève ErreurIA si rien d'exploitable."""
    if not isinstance(brut, dict) or not isinstance(brut.get("aliments"), list):
        raise ErreurIA("Format de réponse inattendu")
    aliments = []
    for a in brut["aliments"][:MAX_ALIMENTS]:
        if not isinstance(a, dict):
            continue
        nom = str(a.get("aliment", "")).strip()[:100]
        if not nom or nom.isdigit():
            continue
        cat = a.get("categorie")
        if cat not in FACTEURS_CO2:
            cat = deviner_categorie(nom)
        if not cat:
            continue
        try:
            q = int(float(a.get("quantite_g") or PORTIONS[cat]))
        except (TypeError, ValueError):
            q = PORTIONS[cat]
        q = max(1, min(q, 3000))
        aliments.append({
            "aliment": nom.lower(), "categorie": cat, "quantite_g": q,
            "co2_kg": round(q / 1000 * FACTEURS_CO2[cat], 2),
        })
    if not aliments:
        raise ErreurIA("Aucun aliment reconnu")
    type_repas = brut.get("type_repas")
    if type_repas not in Repas.TypeRepas.values:
        type_repas = type_selon_heure()
    return {
        "type_repas": type_repas,
        "description": str(brut.get("description") or "")[:200],
        "aliments": aliments,
        "co2_total_kg": round(sum(a["co2_kg"] for a in aliments), 2),
    }


# ------------------------------------------------------------------ moteur local (texte)
MOTS_TYPE = {
    "PETIT_DEJ": ["petit dej", "petit-dej", "petit dejeuner", "ftour", "sbe7", "sba7", "فطور", "الصباح"],
    "DEJEUNER": ["dejeuner", "midi", "ghda", "ghde", "lghda", "الغداء", "الغدا", "غدا"],
    "DINER": ["diner", "soir", "3cha", "acha", "l3cha", "العشاء", "عشا"],
    "COLLATION": ["collation", "gouter", "snack", "lounja", "9ahwa", "قهوة"],
}
# nombre isolé (« 3cha » n'est pas une quantité), unité facultative
_QTE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(kg|g|gr|grammes?|غ)?(?![\w])")


def analyse_locale_texte(texte):
    nom = normaliser(texte)
    type_repas = next((t for t, mots in MOTS_TYPE.items() if any(m in nom for m in mots)), None)
    # découpe en morceaux : « , » « et » « w » « و » « + » « avec »
    morceaux = re.split(r"(?<!\d),|,(?!\d)|;|\+|\n|\bet\b|\bavec\b|\bw\b|(?<!\w)و(?!\w)", nom)
    aliments = []
    for morceau in morceaux:
        trouves = trouver_aliments(morceau)
        if not trouves:
            continue
        q = None
        m = _QTE.search(morceau)
        if m and len(trouves) == 1:
            valeur = float(m.group(1).replace(",", "."))
            if m.group(2) == "kg":
                q = valeur * 1000
            elif m.group(2):
                q = valeur
            elif "oeuf" in trouves[0][0] or "œuf" in trouves[0][0]:
                q = valeur * 55            # « 2 oeufs » ≈ 110 g
        for nom_aliment, cat in trouves:
            aliments.append({"aliment": nom_aliment, "categorie": cat, "quantite_g": round(q) if q else PORTIONS[cat]})
    return {"type_repas": type_repas, "description": "", "aliments": aliments}


# --------------------------------------------------------------------------- API
def depuis_photo(donnees, mime):
    """Photo d'assiette -> aliments. Lève ErreurIA si l'IA est indisponible (pas de repli possible)."""
    t0 = time.perf_counter()
    brut = _appeler_gemini([
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(donnees).decode()}},
        {"text": CONSIGNE + " Analyse la photo de ce repas."},
    ])
    resultat = valider(brut)
    resultat.update(source="GEMINI", duree_ms=int((time.perf_counter() - t0) * 1000))
    return resultat


LANGUES = {"ar-TN": "en tounsi (dialecte tunisien)", "fr-FR": "en français"}


def depuis_audio(donnees, mime, langue=""):
    """Enregistrement vocal -> transcription + aliments (Gemini écoute directement l'audio)."""
    t0 = time.perf_counter()
    brut = _appeler_gemini([
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(donnees).decode()}},
        {"text": CONSIGNE + " Ajoute aussi la clé \"transcription\" : ce que la personne a dit, tel quel. "
                 f"Écoute cet enregistrement où la personne décrit son repas {LANGUES.get(langue, '')}."},
    ])
    resultat = valider(brut)
    resultat.update(source="GEMINI", transcription=str(brut.get("transcription") or "")[:500],
                    duree_ms=int((time.perf_counter() - t0) * 1000))
    return resultat


def depuis_texte(texte):
    """Phrase (français / tounsi, lettres latines ou arabes) -> aliments, avec repli local."""
    t0 = time.perf_counter()
    erreur = ""
    try:
        resultat = valider(_appeler_gemini([{"text": CONSIGNE + f" Repas décrit par l'utilisateur : « {texte} »"}]))
        source = "GEMINI"
    except ErreurIA as e:
        erreur = str(e)
        resultat = valider(analyse_locale_texte(texte))   # peut lever ErreurIA « Aucun aliment reconnu »
        source = "LOCAL"
    resultat.update(source=source, erreur=erreur, duree_ms=int((time.perf_counter() - t0) * 1000))
    return resultat
