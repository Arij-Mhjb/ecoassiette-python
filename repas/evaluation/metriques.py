"""
Évaluation quantitative de l'IA « texte -> aliments » sur un jeu de test annoté (jeu_de_test.json).

Deux niveaux, comme pour un problème d'extraction d'entités puis de classification :
1. Détection des aliments  : précision, rappel, F1 (un aliment prédit est correct s'il correspond à un attendu ;
   « 3dham », « œufs » et « oeuf » sont considérés comme le même aliment).
2. Catégorie des aliments détectés : exactitude, précision / rappel / F1 par catégorie, F1 macro,
   matrice de confusion (catégorie attendue × catégorie prédite).
+ F1 de bout en bout (aliment ET catégorie justes), taux de phrases parfaites, temps de réponse (moyenne, p50, p95).
"""
import json
import math
import re
import time
from pathlib import Path

from users.ai import ErreurIA

from ..categories import normaliser, trouver_aliments
from ..models import FACTEURS_CO2

FICHIER = Path(__file__).with_name("jeu_de_test.json")
CATEGORIES = list(FACTEURS_CO2)


def charger_jeu():
    return json.loads(FICHIER.read_text(encoding="utf-8"))["phrases"]


# ----------------------------------------------------------------------- correspondances
def _cle(nom):
    return " ".join(re.sub(r"(?<=\w{3})[sx]$", "", m) for m in normaliser(nom).split())


def cles(nom):
    """Toutes les façons de reconnaître un aliment (nom brut + traductions tounsi/arabe -> français)."""
    return {_cle(nom)} | {_cle(affiche) for affiche, _ in trouver_aliments(nom)}


def apparier(attendus, predits):
    """Associe chaque aliment attendu à au plus un aliment prédit. Renvoie (paires, faux_positifs, faux_negatifs)."""
    restants = list(predits)
    paires, manques = [], []
    for a in attendus:
        ka = cles(a["aliment"])
        trouve = next((p for p in restants if ka & cles(p["aliment"])), None)
        if trouve:
            restants.remove(trouve)
            paires.append((a, trouve))
        else:
            manques.append(a)
    return paires, restants, manques


# ------------------------------------------------------------------------------ métriques
def _ratio(a, b):
    return round(a / b, 3) if b else 0.0


def _f1(p, r):
    return round(2 * p * r / (p + r), 3) if p + r else 0.0


def centile(valeurs, q):
    if not valeurs:
        return None
    v = sorted(valeurs)
    return v[max(0, math.ceil(q / 100 * len(v)) - 1)]


def calculer(resultats):
    """resultats : [{texte, attendu, predit, duree_ms, erreur}] -> dictionnaire de métriques."""
    tp = fp = fn = tp_bout = parfaites = erreurs_api = 0
    confusion = {a: {p: 0 for p in CATEGORIES} for a in CATEGORIES}
    details = []
    for r in resultats:
        paires, faux_pos, manques = apparier(r["attendu"], r["predit"])
        tp, fp, fn = tp + len(paires), fp + len(faux_pos), fn + len(manques)
        bonnes = 0
        for a, p in paires:
            confusion[a["categorie"]][p["categorie"]] += 1
            bonnes += a["categorie"] == p["categorie"]
        tp_bout += bonnes
        parfaite = not faux_pos and not manques and bonnes == len(paires)
        parfaites += parfaite
        erreurs_api += bool(r.get("erreur"))
        if not parfaite:
            details.append({
                "texte": r["texte"],
                "manques": [a["aliment"] for a in manques],
                "en_trop": [p["aliment"] for p in faux_pos],
                "mal_classes": [f"{a['aliment']} : {a['categorie']} → {p['categorie']}"
                                for a, p in paires if a["categorie"] != p["categorie"]],
                "erreur": r.get("erreur", ""),
            })
    precision, rappel = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    par_categorie = {}
    for c in CATEGORIES:
        vrais = confusion[c][c]
        predits_c = sum(confusion[a][c] for a in CATEGORIES)
        attendus_c = sum(confusion[c].values())
        pc, rc = _ratio(vrais, predits_c), _ratio(vrais, attendus_c)
        par_categorie[c] = {"precision": pc, "rappel": rc, "f1": _f1(pc, rc), "support": attendus_c}
    avec_support = [v["f1"] for v in par_categorie.values() if v["support"]]
    p_bout, r_bout = _ratio(tp_bout, tp + fp), _ratio(tp_bout, tp + fn)
    durees = [r["duree_ms"] for r in resultats if r.get("duree_ms") is not None]
    return {
        "nb_phrases": len(resultats), "nb_aliments_attendus": tp + fn,
        "detection": {"precision": precision, "rappel": rappel, "f1": _f1(precision, rappel),
                      "vrais_positifs": tp, "faux_positifs": fp, "faux_negatifs": fn},
        "categories": {"exactitude": _ratio(tp_bout, tp), "f1_macro": round(sum(avec_support) / len(avec_support), 3) if avec_support else 0.0,
                       "par_categorie": par_categorie, "confusion": confusion},
        "bout_en_bout": {"precision": p_bout, "rappel": r_bout, "f1": _f1(p_bout, r_bout)},
        "phrases_parfaites": _ratio(parfaites, len(resultats)),
        "erreurs_api": erreurs_api,
        "latence_ms": {"moyenne": round(sum(durees) / len(durees)) if durees else None,
                       "p50": centile(durees, 50), "p95": centile(durees, 95), "max": max(durees) if durees else None},
        "erreurs": details,
    }


# -------------------------------------------------------------------------------- moteurs
def predire_local(texte):
    from ..ia import analyse_locale_texte, valider
    try:
        return valider(analyse_locale_texte(texte))["aliments"], ""
    except ErreurIA:                                   # rien reconnu : ce n'est pas une erreur d'API
        return [], ""


def predire_gemini(texte):
    from ..ia import CONSIGNE, _appeler_gemini, valider
    try:
        return valider(_appeler_gemini([{"text": CONSIGNE + f" Repas décrit par l'utilisateur : « {texte} »"}]))["aliments"], ""
    except ErreurIA as e:
        return [], str(e)[:200]


MOTEURS = {"LOCAL": predire_local, "GEMINI": predire_gemini}


def evaluer(moteur, limite=None, pause_s=0.0, progression=None):
    """Lance le moteur sur le jeu de test. progression(i, n) est appelée après chaque phrase."""
    predire = MOTEURS[moteur]
    phrases = charger_jeu()[:limite] if limite else charger_jeu()
    resultats = []
    for i, ph in enumerate(phrases, 1):
        t0 = time.perf_counter()
        predit, erreur = predire(ph["texte"])
        resultats.append({"texte": ph["texte"], "attendu": ph["attendu"], "predit": predit, "erreur": erreur,
                          "duree_ms": int((time.perf_counter() - t0) * 1000)})
        if progression:
            progression(i, len(phrases))
        if pause_s and i < len(phrases):
            time.sleep(pause_s)                         # quota de l'API gratuite (requêtes / minute)
    return calculer(resultats)
