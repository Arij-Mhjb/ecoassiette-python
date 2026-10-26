from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Télécharge et met en cache le modèle local de génération d'images."

    def handle(self, *args, **options):
        try:
            from diffusers import AutoPipelineForText2Image
        except ImportError as exc:
            raise CommandError("Installez d'abord : pip install -r requirements-ai-local.txt") from exc
        self.stdout.write(f"Préparation de {settings.LOCAL_IMAGE_MODEL}…")
        try:
            AutoPipelineForText2Image.from_pretrained(
                settings.LOCAL_IMAGE_MODEL, use_safetensors=True,
            )
        except Exception as exc:
            raise CommandError(f"Téléchargement impossible : {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Modèle prêt. Il peut maintenant être utilisé hors ligne."))
