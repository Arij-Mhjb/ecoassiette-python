import logging
import threading
import time

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .ai import analyser_surplus
from .models import AnalyseSurplusIA, AnnonceSurplus

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    shared_task = None


def executer(analyse_id):
    try:
        analyse = AnalyseSurplusIA.objects.select_related("annonce").get(pk=analyse_id)
    except AnalyseSurplusIA.DoesNotExist:
        return
    analyse.statut = AnalyseSurplusIA.Statut.EN_COURS
    analyse.save(update_fields=["statut"])
    debut = time.perf_counter()
    try:
        resultat = analyser_surplus(analyse.annonce)
        analyse.resultat = resultat
        analyse.source = resultat["source"]
        analyse.statut = AnalyseSurplusIA.Statut.TERMINEE
        annonce = analyse.annonce
        annonce.categorie = resultat["categorie"]
        annonce.urgence_ia = resultat["urgence"]
        annonce.confiance_ia = resultat["confiance"]
        annonce.co2_evite_estime = resultat["co2_evite_estime"]
        if not annonce.allergenes and resultat["allergenes_possibles"]:
            annonce.allergenes = ", ".join(resultat["allergenes_possibles"])
        annonce.save(update_fields=[
            "categorie", "urgence_ia", "confiance_ia", "co2_evite_estime", "allergenes", "modifiee_le"
        ])
    except Exception as exc:  # filet de sécurité: une analyse ne reste jamais bloquée
        logger.exception("Analyse Food Rescue %s impossible", analyse_id)
        analyse.statut = AnalyseSurplusIA.Statut.ECHEC
        analyse.erreur = f"{exc.__class__.__name__}: {exc}"[:300]
    analyse.duree_ms = int((time.perf_counter() - debut) * 1000)
    analyse.terminee_le = timezone.now()
    analyse.save()


if shared_task:
    @shared_task(name="food_rescue.analyser_surplus")
    def analyser_surplus_task(analyse_id):  # pragma: no cover
        executer(analyse_id)


def _dans_thread(analyse_id):
    try:
        executer(analyse_id)
    finally:
        close_old_connections()


def lancer(annonce):
    analyse, _ = AnalyseSurplusIA.objects.get_or_create(annonce=annonce)
    analyse.statut = AnalyseSurplusIA.Statut.EN_ATTENTE
    analyse.erreur = ""
    analyse.save(update_fields=["statut", "erreur"])
    if settings.IA_SYNCHRONE:
        executer(analyse.pk)
        analyse.refresh_from_db()
    elif settings.USE_CELERY and shared_task:  # pragma: no cover
        analyser_surplus_task.delay(analyse.pk)
    else:
        threading.Thread(target=_dans_thread, args=(analyse.pk,), daemon=True).start()
    return analyse

