"""
Module « Utilisateurs & profils ».

- Utilisateur : modèle personnalisé (AbstractUser) avec rôle.
- ProfilAlimentaire : habitudes et préférences, utilisées par les autres modules
  (suivi des repas, impact carbone, alternatives végétales).
- AnalyseProfilIA : historique des analyses IA du profil (résultat, source,
  temps de réponse) -> sert aussi aux métriques de performance.
"""
from decimal import Decimal

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
