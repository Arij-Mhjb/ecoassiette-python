from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.conf import settings
from django.db import models


class FacteurImpact(models.Model):
    """Facteurs moyens par kg d'aliment, avec une source traçable."""

    class RisqueDeforestation(models.TextChoices):
        FAIBLE = "FAIBLE", "Faible"
        MOYEN = "MOYEN", "Moyen"
        ELEVE = "ELEVE", "Élevé"

    categorie = models.CharField("catégorie", max_length=15, unique=True)
    co2_kg_par_kg = models.DecimalField(
        "kg CO₂e par kg", max_digits=9, decimal_places=3, validators=[MinValueValidator(0)]
    )
    eau_litres_par_kg = models.DecimalField(
        "litres d'eau par kg", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    terres_m2_par_kg = models.DecimalField(
        "m² de terres par kg", max_digits=10, decimal_places=3, validators=[MinValueValidator(0)]
    )
    risque_deforestation = models.CharField(
        max_length=8, choices=RisqueDeforestation.choices, default=RisqueDeforestation.FAIBLE
    )
    source = models.CharField(max_length=250)

    class Meta:
        ordering = ["categorie"]
        verbose_name = "facteur d'impact"
        verbose_name_plural = "facteurs d'impact"

    def __str__(self):
        return self.categorie


class AlternativeVegetale(models.Model):
    """Substitution locale vérifiée, utilisée avant de solliciter une API IA."""

    aliment_source = models.CharField(
        max_length=100, blank=True,
        help_text="Mot à détecter dans l'aliment, par exemple bœuf. Laisser vide pour toute la catégorie.",
    )
    categorie_source = models.CharField("catégorie d'origine", max_length=15)
    remplacement = models.CharField(max_length=100)
    idee = models.CharField("conseil de préparation", max_length=250, blank=True)
    facteur_remplacement = models.ForeignKey(
        FacteurImpact, on_delete=models.PROTECT, related_name="alternatives"
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["categorie_source", "aliment_source", "remplacement"]
        verbose_name = "alternative végétale"
        verbose_name_plural = "alternatives végétales"

    def __str__(self):
        origine = self.aliment_source or self.categorie_source
        return f"{origine} → {self.remplacement}"


class AlternativeAdoptee(models.Model):
    """Historique immuable des économies effectivement déclarées par l'utilisateur."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alternatives_adoptees"
    )
    repas = models.ForeignKey(
        "repas.Repas", on_delete=models.CASCADE, related_name="alternatives_adoptees"
    )
    alternative = models.ForeignKey(
        AlternativeVegetale, on_delete=models.PROTECT, related_name="adoptions"
    )
    aliment_original = models.CharField(max_length=100)
    remplacement = models.CharField(max_length=100)
    co2_evite = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    eau_economisee = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    terres_preservees = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    adoptee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-adoptee_le"]
        verbose_name = "alternative adoptée"
        verbose_name_plural = "alternatives adoptées"

    def __str__(self):
        return f"{self.aliment_original} → {self.remplacement}"


class ExtractionRecetteIA(models.Model):
    class Source(models.TextChoices):
        GEMINI = "GEMINI", "Gemini"
        LOCAL = "LOCAL", "Moteur local"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extractions_recettes"
    )
    repas = models.OneToOneField(
        "repas.Repas", on_delete=models.CASCADE, related_name="extraction_ia"
    )
    texte_original = models.TextField(max_length=5000)
    source = models.CharField(max_length=8, choices=Source.choices)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]
        verbose_name = "extraction de recette IA"
        verbose_name_plural = "extractions de recettes IA"

    def __str__(self):
        return f"Extraction du repas {self.repas_id} ({self.source})"


class Sponsor(models.Model):
    nom = models.CharField(max_length=120, unique=True)
    site_web = models.URLField(blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class ProduitRecompense(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon à vérifier"
        PUBLIE = "PUBLIE", "Publié"
        ARCHIVE = "ARCHIVE", "Archivé"

    sponsor = models.ForeignKey(Sponsor, on_delete=models.PROTECT, related_name="produits")
    nom = models.CharField(max_length=160)
    description = models.TextField(max_length=800)
    image = models.ImageField(upload_to="recompenses/", blank=True, null=True)
    prix_public = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(0)])
    remise_pourcent = models.PositiveSmallIntegerField(
        default=50, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    cout_points = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    stock = models.PositiveIntegerField(default=0)
    produit_vegetal = models.BooleanField(default=True)
    url_source = models.URLField(
        blank=True, help_text="Page officielle du produit à vérifier avant publication."
    )
    propose_par_ia = models.BooleanField(default=False, editable=False)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)

    class Meta:
        ordering = ["sponsor", "nom"]

    @property
    def prix_remise(self):
        return self.prix_public * (100 - self.remise_pourcent) / 100

    def __str__(self):
        return f"{self.nom} — {self.sponsor}"


class PreuveRepas(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        APPROUVEE = "APPROUVEE", "Approuvée"
        REFUSEE = "REFUSEE", "Refusée"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preuves_repas"
    )
    repas = models.OneToOneField(
        "repas.Repas", on_delete=models.CASCADE, related_name="preuve_ecologique"
    )
    media = models.FileField(
        upload_to="preuves/%Y/%m/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "mp4", "webm", "mov"])],
    )
    type_media = models.CharField(max_length=10, choices=[("IMAGE", "Photo"), ("VIDEO", "Vidéo")])
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    commentaire_admin = models.CharField(max_length=300, blank=True)
    points_attribues = models.PositiveIntegerField(default=0)
    soumise_le = models.DateTimeField(auto_now_add=True)
    traitee_le = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-soumise_le"]

    def __str__(self):
        return f"Preuve de {self.utilisateur} — {self.get_statut_display()}"


class TransactionPoints(models.Model):
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions_points"
    )
    montant = models.IntegerField(help_text="Positif pour un crédit, négatif pour une dépense.")
    motif = models.CharField(max_length=200)
    preuve = models.OneToOneField(
        PreuveRepas, on_delete=models.PROTECT, blank=True, null=True, related_name="transaction_points"
    )
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return f"{self.utilisateur}: {self.montant:+d} points"


class CommandeRecompense(models.Model):
    class Statut(models.TextChoices):
        CONFIRMEE = "CONFIRMEE", "Confirmée"
        LIVREE = "LIVREE", "Livrée"
        ANNULEE = "ANNULEE", "Annulée"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="commandes_recompenses"
    )
    produit = models.ForeignKey(ProduitRecompense, on_delete=models.PROTECT, related_name="commandes")
    points_utilises = models.PositiveIntegerField()
    prix_remise = models.DecimalField(max_digits=9, decimal_places=2)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.CONFIRMEE)
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creee_le"]

    def __str__(self):
        return f"Commande {self.pk} — {self.produit.nom}"
