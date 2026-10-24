"""
Traitement asynchrone de l'analyse IA.

L'appel à Gemini peut prendre plusieurs secondes : il ne doit pas bloquer la
requête HTTP. La vue crée une AnalyseProfilIA « EN_ATTENTE », répond 202, puis
le navigateur interroge l'état (polling) jusqu'à « TERMINE ».

- USE_CELERY=True  : tâche Celery (worker + Redis), solution de production.
- USE_CELERY=False : thread d'arrière-plan (démo locale / Render gratuit sans Redis).
- IA_SYNCHRONE=True : exécution immédiate (tests automatisés).
"""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import ai
from .models import AnalyseProfilIA

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    shared_task = None


def executer_analyse(analyse_id):
    try:
        analyse = AnalyseProfilIA.objects.select_related("profil__utilisateur").get(pk=analyse_id)
    except AnalyseProfilIA.DoesNotExist:
        logger.error("Analyse %s introuvable", analyse_id)
        return
    analyse.statut = AnalyseProfilIA.Statut.EN_COURS
    analyse.save(update_fields=["statut"])
    try:
        resultat, source, erreur, duree = ai.analyser(analyse.profil)
        analyse.resultat, analyse.source, analyse.erreur, analyse.duree_ms = resultat, source, erreur, duree
        analyse.statut = AnalyseProfilIA.Statut.TERMINE
    except Exception as e:  # filet de sécurité : l'analyse ne reste jamais bloquée
        logger.exception("Échec de l'analyse %s", analyse_id)
        analyse.statut = AnalyseProfilIA.Statut.ECHEC
        analyse.erreur = f"Erreur interne : {e.__class__.__name__}"
    analyse.termine_le = timezone.now()
    analyse.save()


if shared_task:
    @shared_task(name="users.analyser_profil")
    def analyser_profil_task(analyse_id):
        executer_analyse(analyse_id)


def _executer_dans_thread(analyse_id):
    try:
        executer_analyse(analyse_id)
    finally:
        close_old_connections()


def lancer_analyse(profil):
    """Crée l'analyse et la planifie ; retourne immédiatement l'objet."""
    analyse = AnalyseProfilIA.objects.create(profil=profil)
    if settings.IA_SYNCHRONE:
        executer_analyse(analyse.pk)
        analyse.refresh_from_db()
    elif settings.USE_CELERY and shared_task:  # pragma: no cover - nécessite Redis
        analyser_profil_task.delay(analyse.pk)
    else:  # pragma: no cover - testé via IA_SYNCHRONE
        threading.Thread(target=_executer_dans_thread, args=(analyse.pk,), daemon=True).start()
    return analyse
