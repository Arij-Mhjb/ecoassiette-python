try:  # Celery est optionnel : le projet fonctionne sans (repli thread).
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except ImportError:  # pragma: no cover
    celery_app = None
