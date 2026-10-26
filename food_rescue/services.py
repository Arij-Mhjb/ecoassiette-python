from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from impact.models import TransactionPoints

from .models import AnnonceSurplus, CollecteSurplus, ProfilBeneficiaire
from .intelligence import score_matching


URGENCE_POIDS = {"CRITIQUE": 40, "ELEVEE": 30, "MOYENNE": 20, "FAIBLE": 10, "": 0}


def annonces_recommandees(utilisateur, limite=6):
    """Classement explicable, gratuit et déterministe des surplus disponibles."""
    if not ProfilBeneficiaire.objects.filter(
        utilisateur=utilisateur, statut=ProfilBeneficiaire.Statut.VALIDEE
    ).exists():
        return []
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
        matching = score_matching(utilisateur, annonce)
        if not matching:
            continue
        resultats.append({"annonce": annonce, **matching})
        if len(resultats) >= limite:
            break
    return resultats


def crediter_donateur(collecte):
    """Crédite une collecte confirmée exactement une fois."""
    with transaction.atomic():
        collecte = CollecteSurplus.objects.select_for_update().select_related(
            "reservation__annonce__donateur"
        ).get(pk=collecte.pk)
        if not collecte.est_confirmee or collecte.points_attribues:
            return False, collecte.points_attribues
        annonce = collecte.reservation.annonce
        points = 50 + min(150, int(annonce.co2_evite_estime * 10))
        TransactionPoints.objects.create(
            utilisateur=annonce.donateur,
            montant=points,
            motif=f"Don Food Rescue collecté — {annonce.titre} (collecte #{collecte.pk})",
        )
        collecte.points_attribues = points
        collecte.save(update_fields=["points_attribues"])
        return True, points

