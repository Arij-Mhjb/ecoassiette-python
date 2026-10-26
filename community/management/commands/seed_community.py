from django.core.management import call_command
from django.core.management.base import BaseCommand

from community.models import Commentaire, Jaime, Mention, Publication
from users.models import Utilisateur


class Command(BaseCommand):
    help = "Crée un scénario communautaire de démonstration idempotent."

    def handle(self, *args, **options):
        if not Utilisateur.objects.filter(username="amine").exists():
            call_command("seed_demo")
        membres = {u.username: u for u in Utilisateur.objects.filter(username__in=["amine", "yasmine", "karim", "leila"])}
        donnees = [
            ("amine", "Premier couscous aux pois chiches réussi ! Merci @yasmine pour l'idée 🌱"),
            ("yasmine", "Mon défi de la semaine : trois repas végétaux et zéro gaspillage."),
            ("karim", "Notre association a collecté des pains invendus pour le quartier. #FoodRescue"),
        ]
        posts = {}
        for auteur, texte in donnees:
            post, cree = Publication.objects.get_or_create(auteur=membres[auteur], texte=texte)
            posts[auteur] = post
            self.stdout.write(f"{'+' if cree else '='} publication @{auteur}")
        Mention.objects.get_or_create(publication=posts["amine"], utilisateur=membres["yasmine"])
        Jaime.objects.get_or_create(publication=posts["amine"], utilisateur=membres["karim"])
        Jaime.objects.get_or_create(publication=posts["karim"], utilisateur=membres["amine"])
        Commentaire.objects.get_or_create(
            publication=posts["amine"], auteur=membres["yasmine"],
            contenu="Bravo ! La prochaine fois, essaie aussi les légumes rôtis.",
        )
        Publication.objects.get_or_create(auteur=membres["leila"], publication_originale=posts["karim"])
        self.stdout.write(self.style.SUCCESS("Scénario Communauté prêt : publications, mention, likes, commentaire et repartage."))
