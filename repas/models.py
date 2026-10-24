from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class Repas(models.Model):
    class TypeRepas(models.TextChoices):
        PETIT_DEJ = "PETIT_DEJ", "Petit-déjeuner"
        DEJEUNER = "DEJEUNER", "Déjeuner"
        DINER = "DINER", "Dîner"
        COLLATION = "COLLATION", "Collation"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="repas"
    )
    type_repas = models.CharField(max_length=10, choices=TypeRepas.choices)
    date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-cree_le"]
        verbose_name_plural = "repas"

    def __str__(self):
        return f"{self.get_type_repas_display()} du {self.date:%d/%m/%Y}"


class ElementRepas(models.Model):
    class Categorie(models.TextChoices):
        VIANDE_ROUGE = "VIANDE_ROUGE", "Viande rouge"
        VOLAILLE = "VOLAILLE", "Volaille"
        POISSON = "POISSON", "Poisson / fruits de mer"
        LAITIER = "LAITIER", "Produits laitiers / œufs"
        LEGUMINEUSE = "LEGUMINEUSE", "Légumineuses"
        FECULENT = "FECULENT", "Céréales / féculents"
        FRUIT_LEGUME = "FRUIT_LEGUME", "Fruits / légumes"

    repas = models.ForeignKey(Repas, on_delete=models.CASCADE, related_name="elements")
    aliment = models.CharField(max_length=100)
    categorie = models.CharField(max_length=15, choices=Categorie.choices)
    quantite_g = models.PositiveIntegerField(
        "quantité (g)", validators=[MinValueValidator(1), MaxValueValidator(3000)]
    )

    class Meta:
        verbose_name = "aliment du repas"
        verbose_name_plural = "aliments des repas"

    def __str__(self):
        return f"{self.aliment} ({self.quantite_g} g)"