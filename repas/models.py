from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

# Facteurs d'émission moyens (kg CO2e par kg d'aliment), d'après Poore & Nemecek (2018), Science 360:987.
# Valeurs arrondies par catégorie (moyennes des aliments courants de la catégorie).
FACTEURS_CO2 = {
    "VIANDE_ROUGE": 60.0,   # bœuf ≈ 99,5 · agneau ≈ 39,7
    "VOLAILLE": 9.9,
    "POISSON": 13.6,
    "LAITIER": 9.0,         # fromage ≈ 23,9 · lait ≈ 3,2 · œufs ≈ 4,7
    "LEGUMINEUSE": 1.0,     # lentilles, pois chiches, fèves
    "FECULENT": 1.6,        # blé, pâtes, pain, semoule
    "FRUIT_LEGUME": 0.7,
}
# Seuils d'un repas (kg CO2e) pour la pastille de couleur
SEUIL_FAIBLE, SEUIL_ELEVE = 0.5, 1.5


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

    @property
    def co2_kg(self):
        """Empreinte totale du repas (kg CO2e). Utilise les éléments préchargés."""
        return round(sum(e.co2_kg for e in self.elements.all()), 2)

    @property
    def niveau_co2(self):
        if self.co2_kg < SEUIL_FAIBLE:
            return "faible"
        return "moyen" if self.co2_kg < SEUIL_ELEVE else "eleve"

    @property
    def element_le_plus_emetteur(self):
        return max(self.elements.all(), key=lambda e: e.co2_kg, default=None)


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

    @property
    def co2_kg(self):
        """quantité (kg) × facteur d'émission de la catégorie."""
        return round(self.quantite_g / 1000 * FACTEURS_CO2.get(self.categorie, 0), 2)