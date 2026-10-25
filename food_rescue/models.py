import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class AnnonceSurplus(models.Model):
    class Categorie(models.TextChoices):
        FRUITS_LEGUMES = "FRUITS_LEGUMES", "Fruits et légumes"
        BOULANGERIE = "BOULANGERIE", "Pain et pâtisserie"
        PLAT_PREPARE = "PLAT_PREPARE", "Plat préparé"
        EPICERIE = "EPICERIE", "Épicerie"
        PRODUIT_LAITIER = "PRODUIT_LAITIER", "Produit laitier"
        AUTRE = "AUTRE", "Autre"

    class Conservation(models.TextChoices):
        AMBIANTE = "AMBIANTE", "Température ambiante"
        REFRIGERE = "REFRIGERE", "Réfrigéré"
        CONGELE = "CONGELE", "Congelé"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        DISPONIBLE = "DISPONIBLE", "Disponible"
        RESERVEE = "RESERVEE", "Réservée"
        COLLECTEE = "COLLECTEE", "Collectée"
        EXPIREE = "EXPIREE", "Expirée"
        ANNULEE = "ANNULEE", "Annulée"

    donateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="surplus_donnes"
    )
    titre = models.CharField(max_length=160)
    description = models.TextField(max_length=1200, blank=True)
    categorie = models.CharField(max_length=20, choices=Categorie.choices, default=Categorie.AUTRE)
    quantite = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)])
    unite = models.CharField(
        max_length=12,
        choices=[("PORTION", "portion(s)"), ("KG", "kg"), ("UNITE", "unité(s)")],
        default="PORTION",
    )
    conservation = models.CharField(max_length=12, choices=Conservation.choices)
    allergenes = models.CharField(max_length=300, blank=True)
    ville = models.CharField(max_length=100)
    lieu_collecte = models.CharField(
        max_length=200, help_text="L'adresse précise ne sera visible qu'après acceptation d'une réservation."
    )
    disponible_jusquau = models.DateTimeField("disponible jusqu'au")
    photo = models.ImageField(
        upload_to="food_rescue/%Y/%m/", blank=True, null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
    )
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.BROUILLON)
    urgence_ia = models.CharField(max_length=10, blank=True)
    confiance_ia = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    co2_evite_estime = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["disponible_jusquau", "-creee_le"]
        permissions = [("moderer_surplus", "Peut modérer les annonces Food Rescue")]

    def __str__(self):
        return f"{self.titre} - {self.ville}"

    def clean(self):
        if self.disponible_jusquau and self.disponible_jusquau <= timezone.now():
            raise ValidationError({"disponible_jusquau": "La fin de disponibilité doit être dans le futur."})

    def get_absolute_url(self):
        return reverse("food_rescue:detail", args=[self.pk])

    @property
    def est_reservable(self):
        return self.statut == self.Statut.DISPONIBLE and self.disponible_jusquau > timezone.now()


class AnalyseSurplusIA(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_COURS = "EN_COURS", "En cours"
        TERMINEE = "TERMINEE", "Terminée"
        ECHEC = "ECHEC", "Échec"

    annonce = models.OneToOneField(AnnonceSurplus, on_delete=models.CASCADE, related_name="analyse_ia")
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    source = models.CharField(max_length=10, blank=True)
    resultat = models.JSONField(default=dict, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    duree_ms = models.PositiveIntegerField(null=True, blank=True)
    creee_le = models.DateTimeField(auto_now_add=True)
    terminee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creee_le"]

    @property
    def est_terminee(self):
        return self.statut in (self.Statut.TERMINEE, self.Statut.ECHEC)


class ReservationSurplus(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REFUSEE = "REFUSEE", "Refusée"
        ANNULEE = "ANNULEE", "Annulée"
        COLLECTEE = "COLLECTEE", "Collectée"

    annonce = models.ForeignKey(AnnonceSurplus, on_delete=models.CASCADE, related_name="reservations")
    beneficiaire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reservations_surplus"
    )
    message = models.CharField(max_length=500, blank=True)
    heure_collecte = models.DateTimeField()
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    code_collecte = models.CharField(max_length=8, unique=True, editable=False)
    creee_le = models.DateTimeField(auto_now_add=True)
    traitee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creee_le"]
        constraints = [
            models.UniqueConstraint(fields=["annonce", "beneficiaire"], name="reservation_unique_par_beneficiaire")
        ]

    def __str__(self):
        return f"{self.annonce} - {self.beneficiaire}"

    def save(self, *args, **kwargs):
        if not self.code_collecte:
            self.code_collecte = secrets.token_hex(4).upper()
        super().save(*args, **kwargs)

    def clean(self):
        if self.annonce_id and self.beneficiaire_id == self.annonce.donateur_id:
            raise ValidationError("Vous ne pouvez pas réserver votre propre surplus.")
        if self.beneficiaire_id and not ProfilBeneficiaire.objects.filter(
            utilisateur_id=self.beneficiaire_id, statut=ProfilBeneficiaire.Statut.VALIDEE
        ).exists():
            raise ValidationError("Seuls les étudiants et associations validés peuvent réserver un surplus.")
        if self.heure_collecte and self.annonce_id and self.heure_collecte > self.annonce.disponible_jusquau:
            raise ValidationError({"heure_collecte": "La collecte doit précéder la fin de disponibilité."})


class CollecteSurplus(models.Model):
    reservation = models.OneToOneField(
        ReservationSurplus, on_delete=models.PROTECT, related_name="collecte"
    )
    confirmee_par_donateur = models.BooleanField(default=False)
    confirmee_par_beneficiaire = models.BooleanField(default=False)
    confirmee_le = models.DateTimeField(null=True, blank=True)
    points_attribues = models.PositiveIntegerField(default=0)

    @property
    def est_confirmee(self):
        return self.confirmee_par_donateur and self.confirmee_par_beneficiaire


class ProfilBeneficiaire(models.Model):
    class Type(models.TextChoices):
        ETUDIANT = "ETUDIANT", "Étudiant"
        ASSOCIATION = "ASSOCIATION", "Association"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente de validation"
        VALIDEE = "VALIDEE", "Validé"
        REFUSEE = "REFUSEE", "Refusé"

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profil_beneficiaire_food_rescue"
    )
    type_beneficiaire = models.CharField(max_length=12, choices=Type.choices)
    organisme = models.CharField(
        "établissement ou association", max_length=160,
        help_text="Nom de l'établissement d'études ou de l'association.",
    )
    reference_justificatif = models.CharField(
        "référence du justificatif", max_length=120,
        help_text="Ex. numéro de carte étudiant ou matricule de l'association. Ne déposez pas de document sensible.",
    )
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    motif_refus = models.CharField(max_length=300, blank=True)
    verifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="profils_beneficiaires_verifies",
    )
    soumis_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)
    verifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["statut", "-soumis_le"]
        verbose_name = "éligibilité Food Rescue"
        verbose_name_plural = "éligibilités Food Rescue"

    def __str__(self):
        return f"{self.utilisateur} — {self.get_type_beneficiaire_display()} ({self.get_statut_display()})"

    @property
    def est_valide(self):
        return self.statut == self.Statut.VALIDEE

