from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

# Facteurs d'émission : source unique partagée avec le module impact (voir repas/facteurs.py).
from .facteurs import FACTEURS_CO2  # noqa: E402

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
        contexte = f"{self.get_type_repas_display()} du {self.date:%d/%m/%Y}"
        return f"{self.note} — {contexte}" if self.note.strip() else contexte

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

class Remplacement(models.Model):
    """Trace d'un remplacement fait avec le simulateur « Et si… » (sert aux badges et au gain total)."""
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="remplacements")
    repas = models.ForeignKey(Repas, on_delete=models.SET_NULL, null=True, blank=True, related_name="remplacements")
    ancien_aliment = models.CharField(max_length=100)
    nouvel_aliment = models.CharField(max_length=100)
    gain_kg = models.FloatField("CO₂e évité (kg)")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.ancien_aliment} → {self.nouvel_aliment} (−{self.gain_kg} kg)"


class AnalyseRepasIA(models.Model):
    """
    Une demande « Remplir avec l'IA » (photo ou texte), traitée en arrière-plan.
    Sert aussi d'historique de performance (temps de réponse, source, taux de succès) pour le laboratoire IA.
    La photo n'est conservée que le temps du traitement (vidée ensuite : minimisation des données).
    """

    class Mode(models.TextChoices):
        PHOTO = "PHOTO", "Photo"
        TEXTE = "TEXTE", "Texte / voix"
        AUDIO = "AUDIO", "Enregistrement vocal"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_COURS = "EN_COURS", "En cours"
        TERMINE = "TERMINE", "Terminée"
        ECHEC = "ECHEC", "Échec"

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analyses_repas")
    mode = models.CharField(max_length=6, choices=Mode.choices)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    texte = models.CharField(max_length=500, blank=True)
    image_b64 = models.TextField(blank=True)
    mime = models.CharField(max_length=20, blank=True)
    resultat = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=10, blank=True)          # GEMINI / LOCAL
    erreur = models.CharField(max_length=300, blank=True)         # cause technique (journal)
    message = models.CharField(max_length=300, blank=True)        # message affiché à l'utilisateur
    duree_ms = models.PositiveIntegerField(null=True, blank=True)
    cree_le = models.DateTimeField(default=timezone.now, db_index=True)
    termine_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "analyse IA d'un repas"
        verbose_name_plural = "analyses IA des repas"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.get_mode_display()} #{self.pk} — {self.get_statut_display()}"

    @property
    def est_terminee(self):
        return self.statut in (self.Statut.TERMINE, self.Statut.ECHEC)


class EvaluationIA(models.Model):
    """Une campagne d'évaluation du laboratoire IA (moteur local ou Gemini) sur le jeu de test annoté."""

    class Moteur(models.TextChoices):
        LOCAL = "LOCAL", "Moteur local (mots-clés FR + tounsi)"
        GEMINI = "GEMINI", "Gemini (API)"

    class Statut(models.TextChoices):
        EN_COURS = "EN_COURS", "En cours"
        TERMINE = "TERMINE", "Terminée"
        ECHEC = "ECHEC", "Échec"

    moteur = models.CharField(max_length=8, choices=Moteur.choices)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.EN_COURS)
    nb_phrases = models.PositiveSmallIntegerField(default=0)
    avancement = models.PositiveSmallIntegerField(default=0)
    metriques = models.JSONField(default=dict, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    duree_ms = models.PositiveIntegerField(null=True, blank=True)
    lance_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cree_le = models.DateTimeField(default=timezone.now)
    termine_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "évaluation IA"
        verbose_name_plural = "évaluations IA (laboratoire)"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.get_moteur_display()} — {self.cree_le:%d/%m/%Y %H:%M} ({self.get_statut_display()})"

    @property
    def pourcentage(self):
        return round(100 * self.avancement / self.nb_phrases) if self.nb_phrases else 0
