from django.core.validators import MinValueValidator
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
