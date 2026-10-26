from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse


class Publication(models.Model):
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="publications_communaute"
    )
    texte = models.TextField(max_length=2200, blank=True)
    image = models.ImageField(
        upload_to="community/%Y/%m/", blank=True, null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
    )
    publication_originale = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="republications"
    )
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Mention", related_name="publications_mentionnees", blank=True
    )
    est_masquee = models.BooleanField(default=False)
    creee_le = models.DateTimeField(auto_now_add=True)
    modifiee_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creee_le"]
        verbose_name = "publication communautaire"
        verbose_name_plural = "publications communautaires"
        constraints = [
            models.UniqueConstraint(
                fields=["auteur", "publication_originale"],
                condition=models.Q(publication_originale__isnull=False),
                name="republication_unique_par_auteur",
            )
        ]

    def __str__(self):
        return f"Publication de {self.auteur} — {self.creee_le:%d/%m/%Y}"

    def clean(self):
        if not (self.texte or "").strip() and not self.image and not self.publication_originale_id:
            raise ValidationError("Ajoutez un texte ou une image.")
        if self.publication_originale_id and self.publication_originale_id == self.pk:
            raise ValidationError("Une publication ne peut pas se repartager elle-même.")

    def get_absolute_url(self):
        return reverse("community:detail", args=[self.pk])

    @property
    def contenu_source(self):
        return self.publication_originale or self


class Mention(models.Model):
    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="liens_mentions")
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentions_recues")
    creee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["publication", "utilisateur"], name="mention_unique_par_publication")
        ]


class Jaime(models.Model):
    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="jaimes")
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jaimes_communaute")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["publication", "utilisateur"], name="jaime_unique_par_publication")
        ]


class Commentaire(models.Model):
    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="commentaires")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="commentaires_communaute")
    contenu = models.CharField(max_length=500)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cree_le"]

    def __str__(self):
        return f"Commentaire de {self.auteur}"
