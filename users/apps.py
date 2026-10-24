from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Utilisateurs & profils"

    def ready(self):
        from . import signals

        post_migrate.connect(signals.creer_groupes, sender=self)
