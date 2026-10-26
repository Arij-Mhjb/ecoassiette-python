from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envoie un e-mail de test et vérifie la configuration sans afficher le mot de passe."

    def add_arguments(self, parser):
        parser.add_argument(
            "destinataire",
            nargs="?",
            default=settings.EMAIL_HOST_USER,
            help="Adresse destinataire (par défaut : le compte SMTP configuré).",
        )

    def handle(self, *args, **options):
        destinataire = options["destinataire"].strip()
        if not destinataire:
            raise CommandError("Indiquez un destinataire ou configurez MAIL_USERNAME.")

        backend = settings.EMAIL_BACKEND
        if backend.endswith("smtp.EmailBackend"):
            if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
                raise CommandError(
                    "Configuration SMTP incomplète : MAIL_USERNAME et MAIL_PASSWORD sont obligatoires."
                )
            if settings.EMAIL_HOST_PASSWORD == "mot_de_passe_application_gmail":
                raise CommandError(
                    "MAIL_PASSWORD contient encore la valeur d'exemple. Utilisez un vrai mot de passe "
                    "d'application Gmail de 16 caractères."
                )

        self.stdout.write(
            f"Test via {backend} — serveur {settings.EMAIL_HOST}:{settings.EMAIL_PORT} — "
            f"expéditeur {settings.DEFAULT_FROM_EMAIL}"
        )
        try:
            resultat = send_mail(
                "Test e-mail EcoAssiette",
                "Votre configuration e-mail EcoAssiette fonctionne correctement.",
                settings.DEFAULT_FROM_EMAIL,
                [destinataire],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f"Échec de l'envoi : {exc}") from exc

        if resultat != 1:
            raise CommandError("Le serveur n'a confirmé aucun envoi.")
        self.stdout.write(self.style.SUCCESS(f"E-mail de test envoyé à {destinataire}."))
