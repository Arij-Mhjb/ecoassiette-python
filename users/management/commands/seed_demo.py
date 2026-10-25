"""python manage.py seed_demo  — crée des comptes de démonstration (idempotent)."""
from django.core.management.base import BaseCommand

from users.models import DemandeNutritionniste, ProfilAlimentaire, Utilisateur

MDP = "EcoDemo2026!"

COMPTES = [
    ("admin_eco", "Admin", "EcoAssiette", "ADMIN", None),
    ("nutri_sarra", "Sarra", "Ben Salah", "NUTRITIONNISTE", None),
    ("amine", "Amine", "Trabelsi", "CITOYEN",
     dict(regime="OMNIVORE_FORT", aliments_aimes="couscous à l'agneau, burger, pizza",
          aliments_evites="aubergines", taille_foyer=4, temps_cuisine="RAPIDE", ville="Tunis")),
    ("yasmine", "Yasmine", "Gharbi", "CITOYEN",
     dict(regime="FLEXITARIEN", aliments_aimes="poulet, lait, pâtes", aliments_evites="champignons",
          taille_foyer=2, temps_cuisine="MOYEN", ville="Sousse")),
    ("karim", "Karim", "Mansouri", "CITOYEN",
     dict(regime="VEGETARIEN", aliments_aimes="fromage, oeufs, lablabi", taille_foyer=1,
          temps_cuisine="LONG", ville="Ariana", profil_public=False)),
    ("leila", "Leïla", "Haddad", "CITOYEN", dict(regime="FLEXITARIEN", ville="Tunis")),
]


class Command(BaseCommand):
    help = "Crée des comptes de démonstration pour la soutenance."

    def handle(self, *args, **opts):
        for username, prenom, nom, role, profil in COMPTES:
            u, cree = Utilisateur.objects.get_or_create(
                username=username,
                defaults=dict(first_name=prenom, last_name=nom, email=f"{username}@ecoassiette.tn", role=role,
                              email_verifie=True),
            )
            if cree:
                u.set_password(MDP)
                u.save()
            Utilisateur.objects.filter(pk=u.pk).update(email_verifie=True)
            if profil:
                ProfilAlimentaire.objects.filter(utilisateur=u).update(**profil)
            self.stdout.write(f"{'+' if cree else '='} {username} ({role})")
        # une demande de statut nutritionniste en attente, pour montrer la validation pendant la démo
        leila = Utilisateur.objects.get(username="leila")
        if leila.role == Utilisateur.Role.CITOYEN and not leila.demandes_nutritionniste.exists():
            DemandeNutritionniste.objects.create(utilisateur=leila, numero_ordre="DN-2019-0457",
                                                 etablissement="Cabinet de diététique, Lac 2 — Tunis",
                                                 message="Diététicienne-nutritionniste, 6 ans d'expérience.")
            self.stdout.write("+ demande nutritionniste en attente (leila)")
        self.stdout.write(self.style.SUCCESS(f"Mot de passe commun des comptes démo : {MDP}"))
