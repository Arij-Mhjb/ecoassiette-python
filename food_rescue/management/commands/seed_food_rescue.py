"""Crée un scénario Food Rescue complet et idempotent pour la soutenance."""
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from food_rescue.ai import analyser_localement
from food_rescue.models import AnalyseSurplusIA, AnnonceSurplus, CollecteSurplus, ReservationSurplus
from users.models import Utilisateur


class Command(BaseCommand):
    help = "Crée des surplus, réservations et collectes de démonstration."

    def handle(self, *args, **options):
        if not Utilisateur.objects.filter(username="amine").exists():
            call_command("seed_demo")
        utilisateurs = {nom: Utilisateur.objects.get(username=nom) for nom in ("amine", "yasmine", "karim", "leila")}
        maintenant = timezone.now()
        donnees = [
            ("Cagette de légumes du marché", "Tomates, courgettes et carottes fraîches non utilisées.", "FRUITS_LEGUMES", 4, "KG", "AMBIANTE", "Tunis", 18, "DISPONIBLE", "amine"),
            ("Six portions de couscous végétal", "Couscous aux pois chiches, semoule et légumes préparé ce matin.", "PLAT_PREPARE", 6, "PORTION", "REFRIGERE", "Tunis", 5, "DISPONIBLE", "yasmine"),
            ("Pain complet de la journée", "Huit pains complets emballés, à récupérer avant fermeture.", "BOULANGERIE", 8, "UNITE", "AMBIANTE", "Ariana", 9, "RESERVEE", "karim"),
            ("Yaourts nature non ouverts", "Lot conservé au froid, date indiquée sur les emballages.", "PRODUIT_LAITIER", 10, "UNITE", "REFRIGERE", "Sousse", 30, "COLLECTEE", "leila"),
        ]
        annonces = {}
        for titre, description, categorie, quantite, unite, conservation, ville, heures, statut, auteur in donnees:
            annonce, creee = AnnonceSurplus.objects.update_or_create(
                donateur=utilisateurs[auteur], titre=titre,
                defaults={
                    "description": description, "categorie": categorie, "quantite": quantite,
                    "unite": unite, "conservation": conservation, "ville": ville,
                    "lieu_collecte": f"Point de collecte partenaire - {ville}",
                    "disponible_jusquau": maintenant + timedelta(hours=heures), "statut": statut,
                },
            )
            resultat = analyser_localement(annonce)
            for champ, cle in (("categorie", "categorie"), ("urgence_ia", "urgence"), ("confiance_ia", "confiance"), ("co2_evite_estime", "co2_evite_estime")):
                setattr(annonce, champ, resultat[cle])
            annonce.save()
            AnalyseSurplusIA.objects.update_or_create(
                annonce=annonce,
                defaults={"statut": "TERMINEE", "source": "LOCAL", "resultat": resultat, "duree_ms": 1, "terminee_le": maintenant},
            )
            annonces[titre] = annonce
            self.stdout.write(f"{'+' if creee else '='} {titre}")

        reservee = annonces["Pain complet de la journée"]
        reservation, _ = ReservationSurplus.objects.update_or_create(
            annonce=reservee, beneficiaire=utilisateurs["amine"],
            defaults={"heure_collecte": maintenant + timedelta(hours=3), "message": "Je peux venir à 17 h.", "statut": "ACCEPTEE", "traitee_le": maintenant},
        )
        CollecteSurplus.objects.get_or_create(reservation=reservation)

        collectee = annonces["Yaourts nature non ouverts"]
        reservation_finie, _ = ReservationSurplus.objects.update_or_create(
            annonce=collectee, beneficiaire=utilisateurs["karim"],
            defaults={"heure_collecte": maintenant + timedelta(hours=1), "message": "Collecte avec sac isotherme.", "statut": "COLLECTEE", "traitee_le": maintenant},
        )
        CollecteSurplus.objects.update_or_create(
            reservation=reservation_finie,
            defaults={"confirmee_par_donateur": True, "confirmee_par_beneficiaire": True, "confirmee_le": maintenant},
        )
        self.stdout.write(self.style.SUCCESS("Scénario Food Rescue prêt : 4 annonces, 2 réservations et 1 collecte."))

