"""Fonctions IA locales, explicables et gratuites pour Food Rescue."""
import re
import unicodedata
from datetime import timedelta
from difflib import SequenceMatcher

from django.db.models import Count, Q
from django.utils import timezone

from impact.recipe_ai import proposer_recettes_garde_manger

from .models import AnnonceSurplus, ProfilBeneficiaire, ReservationSurplus


STOP = {"de", "des", "du", "la", "le", "les", "un", "une", "et", "avec", "pour", "dans", "sur"}


def _tokens(texte):
    brut = unicodedata.normalize("NFKD", (texte or "").casefold()).encode("ascii", "ignore").decode()
    return {x for x in re.findall(r"[a-z0-9]{3,}", brut) if x not in STOP}


def similarite_semantique(a, b):
    """Score hybride caractères + concepts, stable sans service externe."""
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    sequence = SequenceMatcher(None, (a or "").casefold(), (b or "").casefold()).ratio()
    return round(100 * (0.7 * jaccard + 0.3 * sequence))


def doublons_probables(annonce, seuil=72):
    texte = f"{annonce.titre} {annonce.description}"
    candidats = AnnonceSurplus.objects.exclude(pk=annonce.pk).filter(
        donateur=annonce.donateur, creee_le__gte=timezone.now() - timedelta(days=30)
    )[:30]
    resultats = []
    for autre in candidats:
        score = similarite_semantique(texte, f"{autre.titre} {autre.description}")
        if score >= seuil:
            resultats.append({"annonce": autre, "score": score})
    return sorted(resultats, key=lambda x: -x["score"])


def risque_non_collecte(utilisateur):
    historique = ReservationSurplus.objects.filter(beneficiaire=utilisateur)
    terminees = historique.filter(statut=ReservationSurplus.Statut.COLLECTEE).count()
    annulees = historique.filter(statut=ReservationSurplus.Statut.ANNULEE).count()
    en_cours_retard = historique.filter(
        statut=ReservationSurplus.Statut.ACCEPTEE, heure_collecte__lt=timezone.now()
    ).count()
    total = terminees + annulees + en_cours_retard
    risque = 10 if total == 0 else min(95, round(100 * (annulees + en_cours_retard) / total))
    raisons = []
    if annulees:
        raisons.append(f"{annulees} annulation(s)")
    if en_cours_retard:
        raisons.append(f"{en_cours_retard} collecte(s) en retard")
    if not raisons:
        raisons.append("aucun incident historique")
    return {"score": risque, "niveau": "ELEVE" if risque >= 60 else "MOYEN" if risque >= 30 else "FAIBLE", "raisons": raisons}


def score_matching(utilisateur, annonce):
    profil = utilisateur.profil
    eligibilite = ProfilBeneficiaire.objects.filter(utilisateur=utilisateur, statut="VALIDEE").first()
    if not eligibilite:
        return None
    texte_annonce = f"{annonce.titre} {annonce.description} {annonce.allergenes}"
    preferences = f"{profil.aliments_aimes} {profil.regime}"
    evites = _tokens(profil.aliments_evites)
    if evites & _tokens(texte_annonce):
        return None
    score, raisons = 25, ["profil bénéficiaire validé"]
    semantique = similarite_semantique(preferences, texte_annonce)
    score += min(20, round(semantique * 0.2))
    if semantique >= 30:
        raisons.append("préférences compatibles")
    if profil.ville and profil.ville.casefold() == annonce.ville.casefold():
        score += 20
        raisons.append(f"dans votre ville ({profil.ville})")
    urgence = {"CRITIQUE": 20, "ELEVEE": 16, "MOYENNE": 10, "FAIBLE": 5}.get(annonce.urgence_ia, 5)
    score += urgence
    recus = ReservationSurplus.objects.filter(beneficiaire=utilisateur, statut="COLLECTEE").count()
    equite = max(0, 20 - min(20, recus * 4))
    score += equite
    if equite >= 12:
        raisons.append("priorité d'équité")
    risque = risque_non_collecte(utilisateur)
    score += max(0, 15 - round(risque["score"] * 0.15))
    return {"score": min(100, score), "raisons": raisons, "risque": risque}


def recettes_pour_annonce(annonce, utilisateur):
    texte = f"{annonce.titre}, {annonce.description}"
    return proposer_recettes_garde_manger(texte, getattr(utilisateur, "profil", None))


def repondre_assistant(utilisateur, question):
    q = (question or "").casefold().strip()
    q_normalisee = unicodedata.normalize("NFKD", q).encode("ascii", "ignore").decode()
    if not q:
        return "Posez une question sur les dons, vos points, votre éligibilité ou les surplus disponibles."
    if "point" in q:
        from impact.services import solde_points
        return f"Votre portefeuille contient actuellement {solde_points(utilisateur)} points."
    if "eligib" in q_normalisee or "etudiant" in q_normalisee or "association" in q_normalisee:
        profil = ProfilBeneficiaire.objects.filter(utilisateur=utilisateur).first()
        return (f"Votre demande d'éligibilité est : {profil.get_statut_display()}." if profil
                else "Vous devez demander puis faire valider un profil Étudiant ou Association avant de réserver.")
    disponibles = AnnonceSurplus.objects.filter(statut="DISPONIBLE", disponible_jusquau__gt=timezone.now())
    ville = getattr(utilisateur.profil, "ville", "")
    if ville and ("près" in q or "ville" in q or ville.casefold() in q):
        disponibles = disponibles.filter(ville__iexact=ville)
    noms = list(disponibles.values_list("titre", flat=True)[:5])
    return ("Surplus disponibles : " + "; ".join(noms) if noms else "Aucun surplus compatible n'est disponible actuellement.")


def statistiques_intelligentes():
    annonces = AnnonceSurplus.objects.all()
    return {
        "total": annonces.count(),
        "urgentes": annonces.filter(urgence_ia__in=["CRITIQUE", "ELEVEE"], statut="DISPONIBLE").count(),
        "collectees": annonces.filter(statut="COLLECTEE").count(),
        "eligibles": ProfilBeneficiaire.objects.filter(statut="VALIDEE").count(),
        "par_categorie": list(annonces.values("categorie").annotate(total=Count("id")).order_by("-total")),
        "retards": ReservationSurplus.objects.filter(statut="ACCEPTEE", heure_collecte__lt=timezone.now()).count(),
    }
