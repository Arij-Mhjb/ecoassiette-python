"""Création automatique des groupes/permissions et du profil alimentaire."""
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ProfilAlimentaire, Utilisateur

# Rôle -> (nom du groupe, permissions codename)
GROUPES = {
    Utilisateur.Role.CITOYEN: ("Citoyen", []),
    Utilisateur.Role.NUTRITIONNISTE: (
        "Nutritionniste",
        ["view_profilalimentaire", "view_analyseprofilia"],
    ),
    Utilisateur.Role.ADMIN: (
        "Administrateur",
        [
            "gerer_utilisateurs", "voir_statistiques",
            "view_utilisateur", "add_utilisateur", "change_utilisateur", "delete_utilisateur",
            "view_profilalimentaire", "change_profilalimentaire",
            "view_analyseprofilia", "delete_analyseprofilia",
        ],
    ),
}


def creer_groupes(sender=None, **kwargs):
    """Appelé après chaque `migrate` (post_migrate) : idempotent."""
    for nom, codenames in GROUPES.values():
        groupe, _ = Group.objects.get_or_create(name=nom)
        perms = Permission.objects.filter(content_type__app_label="users", codename__in=codenames)
        groupe.permissions.set(perms)


@receiver(post_save, sender=Utilisateur)
def synchroniser_utilisateur(sender, instance, created, **kwargs):
    if created:
        ProfilAlimentaire.objects.get_or_create(utilisateur=instance)
    # Le groupe suit toujours le rôle (une seule source de vérité : `role`).
    noms = [nom for nom, _ in GROUPES.values()]
    nom_cible = GROUPES[instance.role][0]
    groupe, _ = Group.objects.get_or_create(name=nom_cible)
    instance.groups.remove(*instance.groups.filter(name__in=noms).exclude(name=nom_cible))
    instance.groups.add(groupe)
    # Les administrateurs ont accès au dashboard /admin/
    doit_etre_staff = instance.role == Utilisateur.Role.ADMIN or instance.is_superuser
    if instance.is_staff != doit_etre_staff:
        Utilisateur.objects.filter(pk=instance.pk).update(is_staff=doit_etre_staff)
        instance.is_staff = doit_etre_staff
