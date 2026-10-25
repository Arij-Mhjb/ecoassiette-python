"""
Bilan carbone de l'utilisateur sur 7 jours : chiffres, graphe par jour, « forêt vivante »,
équivalences concrètes, série verte et badges.
"""
import math

from django.db.models import Sum
from django.utils import timezone

from .models import Remplacement, Repas

JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
KG_PAR_KM_VOITURE = 0.2          # voiture thermique moyenne ≈ 0,2 kg CO2e/km (ADEME, Base Carbone)
KG_ABSORBES_ARBRE_SEMAINE = 25 / 52   # un arbre adulte absorbe ≈ 25 kg de CO2 par an
NB_ARBRES = 14


def _objectif(user):
    profil = getattr(user, "profil", None)
    if profil is None:
        return None, ""
    if profil.objectif_co2_hebdo:
        return float(profil.objectif_co2_hebdo), "votre objectif"
    return float(profil.emission_estimee_hebdo), "l'empreinte moyenne de votre régime"


def _totaux_par_jour(user, debut):
    totaux = {}
    for r in Repas.objects.filter(utilisateur=user, date__gte=debut).prefetch_related("elements"):
        totaux[r.date] = totaux.get(r.date, 0) + r.co2_kg
    return totaux


def foret(ratio, a_des_repas):
    """Etat de la forêt selon le ratio émissions / objectif (0 = parfait, 1 = objectif atteint)."""
    borne = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    sains = round(NB_ARBRES * borne((1.3 - ratio) / 0.7)) if a_des_repas else NB_ARBRES
    morts = round(NB_ARBRES * borne((ratio - 1.0) / 0.3)) if a_des_repas else 0
    fatigues = max(0, NB_ARBRES - sains - morts)
    etats = ["sain"] * sains + ["fatigue"] * fatigues + ["mort"] * morts
    # mélange déterministe pour que les arbres malades soient répartis dans la forêt
    ordre = sorted(range(NB_ARBRES), key=lambda i: (i * 7) % NB_ARBRES)
    arbres = []
    for rang, i in enumerate(ordre):
        arbres.append({
            "x": 18 + i * (564 / (NB_ARBRES - 1)) + ((i * 37) % 11) - 5,
            "y": 150 + (i % 2) * 22,
            "echelle": round(0.75 + ((i * 53) % 40) / 100, 2),
            "etat": etats[rang],
            "delai": round((i * 0.37) % 2.4, 2),
        })
    arbres.sort(key=lambda a: a["y"])          # les arbres du fond sont dessinés en premier
    if not a_des_repas:
        message = "Ajoutez vos repas : votre forêt réagit à chacun d'eux 🌱"
    elif ratio <= 0.6:
        message = "Votre forêt est luxuriante 🌳 Continuez comme ça !"
    elif ratio <= 1:
        message = "Votre forêt tient bon : chaque repas végétal la renforce."
    elif ratio <= 1.3:
        message = "Votre forêt souffre : quelques arbres jaunissent."
    else:
        message = "Alerte : votre forêt dépérit 🍂 Essayez le simulateur « Et si… » sur vos repas."
    return {"arbres": arbres, "sains": sains, "fatigues": fatigues, "morts": morts, "message": message}


def serie_verte(user, objectif, totaux=None):
    """Nombre de jours consécutifs (jusqu'à aujourd'hui ou hier) sous l'objectif journalier."""
    if not objectif:
        return 0
    aujourd_hui = timezone.localdate()
    if totaux is None:
        totaux = _totaux_par_jour(user, aujourd_hui - timezone.timedelta(days=60))
    jour = aujourd_hui if aujourd_hui in totaux else aujourd_hui - timezone.timedelta(days=1)
    serie = 0
    while jour in totaux and totaux[jour] <= objectif / 7:
        serie += 1
        jour -= timezone.timedelta(days=1)
    return serie


def badges(nb_repas, nb_remplacements, gain_total, serie):
    regles = [
        ("🍽️", "Assidu", "7 repas enregistrés", nb_repas >= 7),
        ("🌱", "Premier pas", "Un premier remplacement végétal", nb_remplacements >= 1),
        ("🥗", "Éco-cuisinier", "5 remplacements végétaux", nb_remplacements >= 5),
        ("🌳", "Planteur", "10 kg de CO₂e évités", gain_total >= 10),
        ("🔥", "Série verte", "3 jours de suite sous l'objectif", serie >= 3),
    ]
    return [{"icone": i, "nom": n, "desc": d, "obtenu": ok} for i, n, d, ok in regles]


def bilan_semaine(user):
    aujourd_hui = timezone.localdate()
    debut = aujourd_hui - timezone.timedelta(days=6)
    totaux_60 = _totaux_par_jour(user, aujourd_hui - timezone.timedelta(days=60))
    jours_semaine = [debut + timezone.timedelta(days=i) for i in range(7)]
    valeurs = [totaux_60.get(j, 0) for j in jours_semaine]
    total = round(sum(valeurs), 1)
    nb_repas = Repas.objects.filter(utilisateur=user, date__gte=debut).count()

    objectif, source = _objectif(user)
    pct = round(100 * total / objectif) if objectif else None
    objectif_jour = objectif / 7 if objectif else 0
    echelle = max(max(valeurs), objectif_jour, 0.1)
    jours = [{
        "label": JOURS[j.weekday()], "date": j, "kg": round(v, 1),
        "hauteur": round(100 * v / echelle), "depasse": bool(objectif_jour and v > objectif_jour),
        "aujourd_hui": j == aujourd_hui,
    } for j, v in zip(jours_semaine, valeurs)]

    agregat = Remplacement.objects.filter(utilisateur=user).aggregate(gain=Sum("gain_kg"))
    gain_total = round(agregat["gain"] or 0, 1)
    nb_remplacements = Remplacement.objects.filter(utilisateur=user).count()
    serie = serie_verte(user, objectif, totaux_60)

    return {
        "total": total, "nb_repas": nb_repas, "objectif": objectif, "source": source,
        "pct": pct, "pct_barre": min(pct or 0, 100), "depasse": bool(pct and pct > 100),
        "jours": jours,
        "ligne_objectif": round(100 * objectif_jour / echelle) if objectif_jour else None,
        "objectif_jour": round(objectif_jour, 1),
        "foret": foret(total / objectif if objectif else 0, nb_repas > 0),
        "km_voiture": round(total / KG_PAR_KM_VOITURE),
        "arbres_semaine": math.ceil(total / KG_ABSORBES_ARBRE_SEMAINE) if total else 0,
        "gain_total": gain_total, "nb_remplacements": nb_remplacements, "serie": serie,
        "badges": badges(Repas.objects.filter(utilisateur=user).count(), nb_remplacements, gain_total, serie),
    }
