"""
« Remplir avec l'IA » en arrière-plan : un appel Gemini (photo ou texte) prend 5 à 30 s,
il ne doit pas bloquer la requête HTTP ni un worker du serveur.

La vue crée une AnalyseRepasIA, répond 202, et le navigateur interroge son état (polling, 1 s).
Même mécanisme que l'analyse du profil (users/tasks.py) :
  USE_CELERY=True -> worker Celery (Redis) · sinon thread d'arrière-plan · IA_SYNCHRONE=True -> immédiat (tests).
"""
import base64
import logging
import threading
import time

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from users.ai import ErreurIA

from . import ia
from .models import AnalyseRepasIA

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    shared_task = None

MESSAGE_PHOTO = ("L'analyse de la photo est indisponible pour le moment. "
                 "Décrivez votre repas avec le texte ou la voix, ou saisissez-le à la main.")
MESSAGE_AUDIO = ("Je n'ai pas pu analyser l'enregistrement. Parlez distinctement (ex. « klit kosksi b djej »), "
                 "ou écrivez votre repas.")
MESSAGE_TEXTE = "Aucun aliment reconnu. Essayez par exemple : « kosksi b l3allouch w slata »."


def executer(analyse_id):
    try:
        a = AnalyseRepasIA.objects.get(pk=analyse_id)
    except AnalyseRepasIA.DoesNotExist:
        logger.error("Analyse repas %s introuvable", analyse_id)
        return
    a.statut = AnalyseRepasIA.Statut.EN_COURS
    a.save(update_fields=["statut"])
    t0 = time.perf_counter()
    try:
        if a.mode == AnalyseRepasIA.Mode.PHOTO:
            resultat = ia.depuis_photo(base64.b64decode(a.image_b64), a.mime)
        elif a.mode == AnalyseRepasIA.Mode.AUDIO:
            resultat = ia.depuis_audio(base64.b64decode(a.image_b64), a.mime, a.texte)
        else:
            resultat = ia.depuis_texte(a.texte)
        a.resultat, a.source, a.statut = resultat, resultat.get("source", ""), AnalyseRepasIA.Statut.TERMINE
        a.erreur = resultat.get("erreur", "")[:300]
    except ErreurIA as e:
        logger.warning("Analyse repas %s (%s) impossible : %s", a.pk, a.mode, e)
        a.statut, a.erreur = AnalyseRepasIA.Statut.ECHEC, str(e)[:300]
        a.message = {AnalyseRepasIA.Mode.PHOTO: MESSAGE_PHOTO, AnalyseRepasIA.Mode.AUDIO: MESSAGE_AUDIO}.get(a.mode, MESSAGE_TEXTE)
        if settings.DEBUG and a.mode != AnalyseRepasIA.Mode.TEXTE:   # en développement : la cause aide à corriger
            a.message = f"{a.message} [Détail : {e}]"[:300]
    except Exception as e:  # filet de sécurité : jamais d'analyse bloquée « en cours »
        logger.exception("Échec inattendu de l'analyse repas %s", a.pk)
        a.statut, a.erreur = AnalyseRepasIA.Statut.ECHEC, f"Erreur interne : {e.__class__.__name__}"
        a.message = "Une erreur inattendue est survenue. Réessayez ou saisissez le repas à la main."
    a.duree_ms = int((time.perf_counter() - t0) * 1000)
    a.image_b64 = ""                                   # la photo n'est pas conservée
    a.termine_le = timezone.now()
    a.save()


if shared_task:
    @shared_task(name="repas.analyser_repas")
    def analyser_repas_task(analyse_id):  # pragma: no cover - nécessite Redis
        executer(analyse_id)


def _dans_thread(analyse_id):
    try:
        executer(analyse_id)
    finally:
        close_old_connections()


def lancer(utilisateur, mode, texte="", donnees=b"", mime=""):
    a = AnalyseRepasIA.objects.create(utilisateur=utilisateur, mode=mode, texte=texte[:500], mime=mime,
                                      image_b64=base64.b64encode(donnees).decode() if donnees else "")
    if settings.IA_SYNCHRONE:
        executer(a.pk)
        a.refresh_from_db()
    elif settings.USE_CELERY and shared_task:  # pragma: no cover - nécessite Redis
        analyser_repas_task.delay(a.pk)
    else:
        threading.Thread(target=_dans_thread, args=(a.pk,), daemon=True).start()
    return a


# ------------------------------------------------------------------ laboratoire IA (évaluation)
def executer_evaluation(evaluation_id, limite=None):
    from .evaluation.metriques import charger_jeu, evaluer
    from .models import EvaluationIA

    ev = EvaluationIA.objects.get(pk=evaluation_id)
    ev.nb_phrases = min(limite or 10**6, len(charger_jeu()))
    ev.save(update_fields=["nb_phrases"])

    def progression(i, n):
        EvaluationIA.objects.filter(pk=ev.pk).update(avancement=i)

    t0 = time.perf_counter()
    try:
        pause = getattr(settings, "GEMINI_PAUSE_S", 0) if ev.moteur == EvaluationIA.Moteur.GEMINI else 0
        ev.metriques = evaluer(ev.moteur, limite=limite, pause_s=pause, progression=progression)
        ev.statut, ev.avancement = EvaluationIA.Statut.TERMINE, ev.nb_phrases
    except Exception as e:  # filet de sécurité
        logger.exception("Évaluation %s impossible", ev.pk)
        ev.statut, ev.erreur = EvaluationIA.Statut.ECHEC, f"{e.__class__.__name__} : {e}"[:300]
    ev.duree_ms = int((time.perf_counter() - t0) * 1000)
    ev.termine_le = timezone.now()
    ev.save()


if shared_task:
    @shared_task(name="repas.evaluer_ia", time_limit=1800)
    def evaluer_ia_task(evaluation_id, limite=None):  # pragma: no cover - nécessite Redis
        executer_evaluation(evaluation_id, limite)


def _evaluation_dans_thread(evaluation_id, limite):
    try:
        executer_evaluation(evaluation_id, limite)
    finally:
        close_old_connections()


def lancer_evaluation(moteur, utilisateur=None, limite=None):
    from .models import EvaluationIA
    ev = EvaluationIA.objects.create(moteur=moteur, lance_par=utilisateur)
    if settings.IA_SYNCHRONE or moteur == EvaluationIA.Moteur.LOCAL:     # le moteur local répond en < 1 s
        executer_evaluation(ev.pk, limite)
        ev.refresh_from_db()
    elif settings.USE_CELERY and shared_task:  # pragma: no cover - nécessite Redis
        evaluer_ia_task.delay(ev.pk, limite)
    else:
        threading.Thread(target=_evaluation_dans_thread, args=(ev.pk, limite), daemon=True).start()
    return ev
