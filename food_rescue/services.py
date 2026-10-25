from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from .models import AnnonceSurplus


URGENCE_POIDS = {"CRITIQUE": 40, "ELEVEE": 30, "MOYENNE": 20, "FAIBLE": 10, "": 0}


def annonces_recommandees(utilisateur, limite=6):
    """Classement explicable, gratuit et déterministe des surplus disponibles."""
    profil = getattr(utilisateur, "profil", None)
    ville = (getattr(profil, "ville", "") or "").strip()
    evites = set(getattr(profil, "liste_evites", []) or [])
    qs = AnnonceSurplus.objects.filter(
        statut=AnnonceSurplus.Statut.DISPONIBLE,
        disponible_jusquau__gt=timezone.now(),
    ).exclude(donateur=utilisateur).select_related("donateur")
    qs = qs.annotate(
        priorite=Case(
            When(urgence_ia="CRITIQUE", then=Value(40)),
            When(urgence_ia="ELEVEE", then=Value(30)),
            When(urgence_ia="MOYENNE", then=Value(20)),
            default=Value(10), output_field=IntegerField(),
        )
    ).order_by("-priorite", "disponible_jusquau")
    resultats = []
    for annonce in qs[:50]:
        texte = f"{annonce.titre} {annonce.description} {annonce.allergenes}".lower()
        if any(mot and mot in texte for mot in evites):
            continue
        score = 50 + URGENCE_POIDS.get(annonce.urgence_ia, 0)
        raisons = [f"urgence {annonce.urgence_ia.lower()}" if annonce.urgence_ia else "disponible bientôt"]
        if ville and ville.lower() == annonce.ville.lower():
            score += 10
            raisons.append(f"dans votre ville ({ville})")
        resultats.append({"annonce": annonce, "score": min(score, 100), "raisons": raisons})
        if len(resultats) >= limite:
            break
    return resultats

