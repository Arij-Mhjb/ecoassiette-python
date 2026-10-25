from django.apps import AppConfig, apps
from django.db.models.signals import post_delete, post_save


class RepasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'repas'

    def ready(self):
        # un facteur modifié dans /admin/ (module impact) est pris en compte immédiatement
        from .facteurs import FACTEURS_CO2
        try:
            facteur = apps.get_model("impact", "FacteurImpact")
        except LookupError:
            return
        post_save.connect(FACTEURS_CO2.invalider, sender=facteur, dispatch_uid="repas.facteurs.save")
        post_delete.connect(FACTEURS_CO2.invalider, sender=facteur, dispatch_uid="repas.facteurs.delete")
