from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from urllib.parse import quote_plus


class PlanMenu(models.Model):
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plans_menus"
    )
    semaine_du = models.DateField("semaine du")
    objectif_co2 = models.DecimalField(
        "objectif carbone hebdomadaire (kg CO₂e)", max_digits=7, decimal_places=2,
        default=20, validators=[MinValueValidator(0.1)],
    )
    source = models.CharField(max_length=8, choices=[("GEMINI", "Gemini"), ("LOCAL", "Moteur local")])
    numero_generation = models.PositiveIntegerField(default=1, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-semaine_du"]
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "semaine_du"], name="plan_unique_par_semaine")
        ]

    def __str__(self):
        return f"Semaine du {self.semaine_du:%d/%m/%Y} — {self.utilisateur}"

    @property
    def total_co2(self):
        return round(sum(float(menu.co2_estime) for menu in self.menus.all()), 2)

    @property
    def respecte_objectif(self):
        return self.total_co2 <= float(self.objectif_co2)


class MenuPlanifie(models.Model):
    plan = models.ForeignKey(PlanMenu, on_delete=models.CASCADE, related_name="menus")
    date = models.DateField()
    type_repas = models.CharField(max_length=10, choices=[("DEJEUNER", "Déjeuner"), ("DINER", "Dîner")])
    nom = models.CharField(max_length=160)
    ingredients = models.JSONField(default=list)
    instructions = models.JSONField(default=list)
    nutrition = models.JSONField(default=dict)
    co2_estime = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    repas_source = models.ForeignKey(
        "repas.Repas", on_delete=models.SET_NULL, null=True, blank=True, related_name="menus_alternatifs"
    )
    repas_realise = models.OneToOneField(
        "repas.Repas", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="menu_planifie", verbose_name="repas ajouté",
    )
    produit_vegetal = models.ForeignKey(
        "impact.ProduitRecompense", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="menus_planifies", verbose_name="produit végétal recommandé",
    )
    co2_avant = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    explication = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["date", "type_repas"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "date", "type_repas"], name="menu_unique_par_creneau")
        ]

    @property
    def economie_co2(self):
        if self.co2_avant is None:
            return 0
        return round(max(0, float(self.co2_avant) - float(self.co2_estime)), 2)

    @property
    def tutoriel_video_url(self):
        recherche = quote_plus(f"tutoriel recette {self.nom} facile en français")
        return f"https://www.youtube.com/results?search_query={recherche}"

    def __str__(self):
        return f"{self.nom} — {self.date:%d/%m/%Y}"
