"""
Module « Utilisateurs & profils ».

- Utilisateur : modèle personnalisé (AbstractUser) avec rôle.
- ProfilAlimentaire : habitudes et préférences, utilisées par les autres modules
  (suivi des repas, impact carbone, alternatives végétales).
- AnalyseProfilIA : historique des analyses IA du profil (résultat, source,
  temps de réponse) -> sert aussi aux métriques de performance.
"""
import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Utilisateur(AbstractUser):
    class Role(models.TextChoices):
        CITOYEN = "CITOYEN", "Citoyen"
        NUTRITIONNISTE = "NUTRITIONNISTE", "Nutritionniste"
        ADMIN = "ADMIN", "Administrateur"

    email = models.EmailField("adresse e-mail", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CITOYEN)
    telephone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\+?[0-9 ]{8,15}$", "Numéro invalide (8 à 15 chiffres, + autorisé).")],
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    email_verifie = models.BooleanField(
        "e-mail confirmé", default=False,
        help_text="Passe à vrai quand l'utilisateur clique sur le lien reçu par e-mail.",
    )

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["-date_joined"]
        permissions = [
            ("gerer_utilisateurs", "Peut gérer les comptes utilisateurs (CRUD)"),
            ("voir_statistiques", "Peut consulter les statistiques des utilisateurs"),
        ]

    def __str__(self):
        return self.get_full_name() or self.username

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if self.is_superuser:
            self.role = self.Role.ADMIN
            self.email_verifie = True
        super().save(*args, **kwargs)

    @property
    def est_admin(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    def peut_gerer(self, cible):
        """Un compte administrateur ne peut être modifié, désactivé ou supprimé que par un super-administrateur."""
        return self.is_superuser or not cible.est_admin

    @property
    def est_nutritionniste(self):
        return self.role == self.Role.NUTRITIONNISTE


# Émissions moyennes d'un régime (kg CO2e / jour), Scarborough et al. 2014,
# Climatic Change 125:179-192 (régime britannique, 2 000 kcal/jour).
EMISSIONS_JOUR_PAR_REGIME = {
    "OMNIVORE_FORT": Decimal("7.19"),
    "OMNIVORE": Decimal("5.63"),
    "FLEXITARIEN": Decimal("4.67"),
    "PESCETARIEN": Decimal("3.91"),
    "VEGETARIEN": Decimal("3.81"),
    "VEGAN": Decimal("2.89"),
}


class ProfilAlimentaire(models.Model):
    class Regime(models.TextChoices):
        OMNIVORE_FORT = "OMNIVORE_FORT", "Omnivore (viande tous les jours)"
        OMNIVORE = "OMNIVORE", "Omnivore (viande régulièrement)"
        FLEXITARIEN = "FLEXITARIEN", "Flexitarien (viande occasionnelle)"
        PESCETARIEN = "PESCETARIEN", "Pescétarien"
        VEGETARIEN = "VEGETARIEN", "Végétarien"
        VEGAN = "VEGAN", "Végan"

    class Activite(models.TextChoices):
        SEDENTAIRE = "SEDENTAIRE", "Sédentaire"
        MODERE = "MODERE", "Modérée"
        ACTIF = "ACTIF", "Active"

    class Cuisine(models.TextChoices):
        RAPIDE = "RAPIDE", "Moins de 20 min"
        MOYEN = "MOYEN", "20 à 45 min"
        LONG = "LONG", "J'aime cuisiner longtemps"

    utilisateur = models.OneToOneField(Utilisateur, on_delete=models.CASCADE, related_name="profil")
    regime = models.CharField("régime actuel", max_length=20, choices=Regime.choices, default=Regime.OMNIVORE)
    aliments_aimes = models.CharField(
        "aliments / plats préférés", max_length=300, blank=True,
        help_text="Séparés par des virgules (ex. couscous, pâtes, poulet).",
    )
    aliments_evites = models.CharField(
        "aliments à éviter", max_length=300, blank=True,
        help_text="Aliments que vous ne mangez pas ou n'aimez pas, séparés par des virgules.",
    )
    taille_foyer = models.PositiveSmallIntegerField(
        "personnes dans le foyer", default=1, validators=[MinValueValidator(1), MaxValueValidator(15)]
    )
    niveau_activite = models.CharField(max_length=12, choices=Activite.choices, default=Activite.MODERE)
    temps_cuisine = models.CharField("temps de cuisine", max_length=10, choices=Cuisine.choices, default=Cuisine.MOYEN)
    ville = models.CharField(max_length=80, blank=True)
    objectif_co2_hebdo = models.DecimalField(
        "objectif CO₂ hebdomadaire (kg)", max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("5")), MaxValueValidator(Decimal("100"))],
        help_text="Entre 5 et 100 kg CO₂e par semaine et par personne.",
    )
    profil_public = models.BooleanField(
        "partager mon profil avec les nutritionnistes", default=True
    )
    mis_a_jour = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profil alimentaire"
        verbose_name_plural = "profils alimentaires"

    def __str__(self):
        return f"Profil de {self.utilisateur}"

    def get_absolute_url(self):
        return reverse("users:profil")

    @staticmethod
    def _liste(texte):
        return [t.strip().lower() for t in (texte or "").split(",") if t.strip()]

    @property
    def liste_aimes(self):
        return self._liste(self.aliments_aimes)

    @property
    def liste_evites(self):
        return self._liste(self.aliments_evites)

    @property
    def emission_estimee_hebdo(self):
        """Empreinte estimée du régime déclaré (kg CO2e / semaine / personne)."""
        return (EMISSIONS_JOUR_PAR_REGIME[self.regime] * 7).quantize(Decimal("0.1"))

    @property
    def taux_completion(self):
        champs = [self.aliments_aimes, self.aliments_evites, self.ville, self.objectif_co2_hebdo]
        return int(100 * (2 + sum(1 for c in champs if c)) / (2 + len(champs)))

    def clean(self):
        communs = set(self.liste_aimes) & set(self.liste_evites)
        if communs:
            raise ValidationError(
                {"aliments_evites": f"Un aliment ne peut pas être à la fois aimé et évité : {', '.join(sorted(communs))}."}
            )
        if self.objectif_co2_hebdo and self.objectif_co2_hebdo > self.emission_estimee_hebdo:
            raise ValidationError(
                {"objectif_co2_hebdo": (
                    f"L'objectif doit être inférieur à votre empreinte estimée "
                    f"({self.emission_estimee_hebdo} kg/semaine) pour représenter une réduction."
                )}
            )


class AnalyseProfilIA(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_COURS = "EN_COURS", "En cours"
        TERMINE = "TERMINE", "Terminée"
        ECHEC = "ECHEC", "Échec"

    class Source(models.TextChoices):
        GEMINI = "GEMINI", "Gemini (API)"
        LOCAL = "LOCAL", "Moteur local (repli)"

    profil = models.ForeignKey(ProfilAlimentaire, on_delete=models.CASCADE, related_name="analyses")
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    source = models.CharField(max_length=10, choices=Source.choices, blank=True)
    resultat = models.JSONField(default=dict, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    duree_ms = models.PositiveIntegerField(null=True, blank=True)
    cree_le = models.DateTimeField(default=timezone.now)
    termine_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "analyse IA du profil"
        verbose_name_plural = "analyses IA des profils"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Analyse #{self.pk} — {self.profil.utilisateur} ({self.get_statut_display()})"

    @property
    def est_terminee(self):
        return self.statut in (self.Statut.TERMINE, self.Statut.ECHEC)


# ============================================================ rôle nutritionniste
# Deux façons de devenir nutritionniste (jamais en se l'attribuant soi-même) :
#   1. Invitation : un administrateur invite une adresse e-mail -> lien unique (48 h) -> création du compte.
#   2. Demande : à l'inscription (ou depuis son profil), le citoyen demande le statut ; il reste CITOYEN
#      tant qu'un administrateur n'a pas validé la demande.
def _hash_jeton(jeton):
    return hashlib.sha256(jeton.encode()).hexdigest()


class Invitation(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        ANNULEE = "ANNULEE", "Annulée"

    email = models.EmailField("adresse e-mail")
    first_name = models.CharField("prénom", max_length=150, blank=True)
    last_name = models.CharField("nom", max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Utilisateur.Role.choices, default=Utilisateur.Role.NUTRITIONNISTE)
    # On ne stocke que l'empreinte SHA-256 du jeton : une fuite de la base ne donne pas de lien utilisable.
    jeton_hash = models.CharField(max_length=64, unique=True, editable=False)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    invite_par = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, related_name="invitations_envoyees")
    utilisateur = models.OneToOneField(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="invitation", help_text="Compte créé à partir de l'invitation.")
    cree_le = models.DateTimeField(default=timezone.now)
    expire_le = models.DateTimeField()
    acceptee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "invitation"
        verbose_name_plural = "invitations"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Invitation {self.get_role_display().lower()} — {self.email}"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def nouveau_jeton(self):
        """Génère un jeton aléatoire (256 bits), en garde l'empreinte, repousse l'expiration. Renvoie le jeton en clair."""
        jeton = secrets.token_urlsafe(32)
        self.jeton_hash = _hash_jeton(jeton)
        self.expire_le = timezone.now() + timedelta(hours=settings.INVITATION_DUREE_HEURES)
        return jeton

    @classmethod
    def depuis_jeton(cls, jeton):
        return cls.objects.filter(jeton_hash=_hash_jeton(jeton or "")).first()

    @property
    def est_expiree(self):
        return self.statut == self.Statut.EN_ATTENTE and timezone.now() >= self.expire_le

    @property
    def est_utilisable(self):
        return self.statut == self.Statut.EN_ATTENTE and not self.est_expiree

    @property
    def statut_affiche(self):
        return "Expirée" if self.est_expiree else self.get_statut_display()


class DemandeNutritionniste(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REFUSEE = "REFUSEE", "Refusée"

    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="demandes_nutritionniste")
    numero_ordre = models.CharField(
        "numéro d'inscription à l'ordre", max_length=30,
        validators=[RegexValidator(r"^[A-Za-z0-9\-/ ]{3,30}$", "Numéro invalide (lettres, chiffres, - et /).")],
        help_text="Numéro d'inscription au Conseil / à l'Ordre des diététiciens-nutritionnistes.",
    )
    etablissement = models.CharField("lieu d'exercice", max_length=150, help_text="Cabinet, hôpital, clinique…")
    message = models.TextField("message (facultatif)", max_length=500, blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    motif_refus = models.CharField("motif du refus", max_length=300, blank=True)
    traitee_par = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="demandes_traitees")
    cree_le = models.DateTimeField(default=timezone.now)
    traitee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "demande de statut nutritionniste"
        verbose_name_plural = "demandes de statut nutritionniste"
        ordering = ["-cree_le"]
        constraints = [
            # une seule demande en attente à la fois par utilisateur
            models.UniqueConstraint(fields=["utilisateur"], condition=models.Q(statut="EN_ATTENTE"),
                                    name="une_demande_en_attente_par_utilisateur"),
        ]

    def __str__(self):
        return f"Demande de {self.utilisateur} ({self.get_statut_display().lower()})"

    def accepter(self, admin):
        self.statut, self.traitee_par, self.traitee_le = self.Statut.ACCEPTEE, admin, timezone.now()
        self.save()
        u = self.utilisateur
        u.role = Utilisateur.Role.NUTRITIONNISTE
        u.save()            # le signal synchronise le groupe et donc les permissions

    def refuser(self, admin, motif):
        self.statut, self.traitee_par, self.traitee_le = self.Statut.REFUSEE, admin, timezone.now()
        self.motif_refus = motif
        self.save()


# ================================================== recommandations nutritionniste -> citoyen
class Recommandation(models.Model):
    class Theme(models.TextChoices):
        ALIMENTATION = "ALIMENTATION", "Alimentation"
        OBJECTIF = "OBJECTIF", "Objectif CO₂"
        RECETTE = "RECETTE", "Idée de recette"
        AUTRE = "AUTRE", "Autre"

    class Avis(models.TextChoices):
        UTILE = "UTILE", "Utile"
        PAS_UTILE = "PAS_UTILE", "Pas utile"

    auteur = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, related_name="recommandations_ecrites")
    citoyen = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="recommandations_recues")
    theme = models.CharField("thème", max_length=15, choices=Theme.choices, default=Theme.ALIMENTATION)
    titre = models.CharField(max_length=120)
    contenu = models.TextField("conseil", max_length=1500)
    cree_le = models.DateTimeField(default=timezone.now)
    lue_le = models.DateTimeField(null=True, blank=True)
    avis = models.CharField(max_length=10, choices=Avis.choices, blank=True)

    class Meta:
        verbose_name = "recommandation"
        verbose_name_plural = "recommandations"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.titre} — pour {self.citoyen}"


# ============================================================ sécurité de connexion
class HistoriqueConnexion(models.Model):
    """Chaque tentative de connexion (réussie ou non). Sert au blocage anti brute-force et à l'historique."""
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, null=True, blank=True, related_name="connexions")
    identifiant = models.CharField(max_length=254, db_index=True)       # tel que saisi (normalisé)
    succes = models.BooleanField(default=False)
    ip = models.CharField("adresse IP (masquée)", max_length=45, blank=True)
    navigateur = models.CharField(max_length=80, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    cree_le = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "connexion"
        verbose_name_plural = "historique des connexions"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{'✓' if self.succes else '✗'} {self.identifiant} — {self.cree_le:%d/%m/%Y %H:%M}"


# ================================================================== journal d'audit
class JournalAudit(models.Model):
    """Trace inaltérable des actions sensibles (qui, quoi, sur qui, quand)."""

    class Action(models.TextChoices):
        COMPTE_CREE = "COMPTE_CREE", "Compte créé"
        COMPTE_MODIFIE = "COMPTE_MODIFIE", "Compte modifié"
        COMPTE_SUPPRIME = "COMPTE_SUPPRIME", "Compte supprimé"
        COMPTE_ACTIVE = "COMPTE_ACTIVE", "Compte activé"
        COMPTE_DESACTIVE = "COMPTE_DESACTIVE", "Compte désactivé"
        SUPPRESSION_PAR_UTILISATEUR = "AUTO_SUPPRESSION", "Compte supprimé par son titulaire"
        DEMANDE_ACCEPTEE = "DEMANDE_ACCEPTEE", "Demande nutritionniste acceptée"
        DEMANDE_REFUSEE = "DEMANDE_REFUSEE", "Demande nutritionniste refusée"
        INVITATION_ENVOYEE = "INVITATION_ENVOYEE", "Invitation envoyée"
        INVITATION_RENVOYEE = "INVITATION_RENVOYEE", "Invitation renvoyée"
        INVITATION_ANNULEE = "INVITATION_ANNULEE", "Invitation annulée"
        INVITATION_ACCEPTEE = "INVITATION_ACCEPTEE", "Invitation acceptée"
        RECOMMANDATION = "RECOMMANDATION", "Recommandation envoyée"
        CONNEXION_BLOQUEE = "CONNEXION_BLOQUEE", "Connexion bloquée (trop d'échecs)"
        DECONNEXION_GLOBALE = "DECONNEXION_GLOBALE", "Déconnexion de tous les appareils"
        EXPORT_DONNEES = "EXPORT_DONNEES", "Export des données personnelles"
        # activité des utilisateurs (citoyens, nutritionnistes, administrateurs)
        INSCRIPTION = "INSCRIPTION", "Inscription"
        EMAIL_CONFIRME = "EMAIL_CONFIRME", "E-mail confirmé"
        CONNEXION = "CONNEXION", "Connexion"
        CONNEXION_ECHOUEE = "CONNEXION_ECHOUEE", "Connexion échouée"
        DECONNEXION = "DECONNEXION", "Déconnexion"
        INFOS_MODIFIEES = "INFOS_MODIFIEES", "Informations personnelles modifiées"
        PROFIL_MODIFIE = "PROFIL_MODIFIE", "Profil alimentaire modifié"
        MDP_MODIFIE = "MDP_MODIFIE", "Mot de passe modifié"
        MDP_REINITIALISE = "MDP_REINITIALISE", "Mot de passe réinitialisé"
        DEMANDE_ENVOYEE = "DEMANDE_ENVOYEE", "Demande nutritionniste envoyée"
        ANALYSE_IA = "ANALYSE_IA", "Analyse IA du profil lancée"
        REPAS_AJOUTE = "REPAS_AJOUTE", "Repas ajouté"
        REPAS_MODIFIE = "REPAS_MODIFIE", "Repas modifié"
        REPAS_SUPPRIME = "REPAS_SUPPRIME", "Repas supprimé"
        ALIMENT_REMPLACE = "ALIMENT_REMPLACE", "Aliment remplacé (alternative)"

    # regroupement pour le filtre « Type » du journal
    CATEGORIES = {
        "connexions": ("Connexions", ["CONNEXION", "CONNEXION_ECHOUEE", "DECONNEXION", "CONNEXION_BLOQUEE",
                                      "DECONNEXION_GLOBALE"]),
        "activite": ("Activité des utilisateurs", ["INSCRIPTION", "EMAIL_CONFIRME", "INFOS_MODIFIEES", "PROFIL_MODIFIE",
                                                   "MDP_MODIFIE", "MDP_REINITIALISE", "DEMANDE_ENVOYEE", "ANALYSE_IA",
                                                   "REPAS_AJOUTE", "REPAS_MODIFIE", "REPAS_SUPPRIME", "ALIMENT_REMPLACE",
                                                   "EXPORT_DONNEES", "AUTO_SUPPRESSION", "INVITATION_ACCEPTEE"]),
        "administration": ("Actions d'administration", ["COMPTE_CREE", "COMPTE_MODIFIE", "COMPTE_SUPPRIME",
                                                        "COMPTE_ACTIVE", "COMPTE_DESACTIVE", "DEMANDE_ACCEPTEE",
                                                        "DEMANDE_REFUSEE", "INVITATION_ENVOYEE", "INVITATION_RENVOYEE",
                                                        "INVITATION_ANNULEE", "RECOMMANDATION"]),
    }

    acteur = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    acteur_nom = models.CharField(max_length=150, blank=True)     # conservé même si le compte est supprimé
    action = models.CharField(max_length=25, choices=Action.choices, db_index=True)
    cible = models.CharField(max_length=200, blank=True)
    details = models.CharField(max_length=300, blank=True)
    ip = models.CharField(max_length=45, blank=True)
    cree_le = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-cree_le"]
        permissions = [("voir_journal", "Peut consulter le journal d'audit")]

    def __str__(self):
        return f"{self.cree_le:%d/%m/%Y %H:%M} — {self.acteur_nom or 'système'} : {self.get_action_display()}"
