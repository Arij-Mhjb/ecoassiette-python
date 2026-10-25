from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Utilisateurs & profils"

    def ready(self):
        from . import securite, signals  # noqa: F401  (enregistre les receivers de connexion)

        # sans « sender » : relancé après chaque app, donc les permissions de « repas » existent déjà
        post_migrate.connect(signals.creer_groupes, dispatch_uid="users.creer_groupes")
