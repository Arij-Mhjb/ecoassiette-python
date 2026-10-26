import re

from django import forms
from django.contrib.auth import get_user_model

from .models import Commentaire, Mention, Publication

User = get_user_model()


class PublicationForm(forms.ModelForm):
    mentions = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={"class": "js-mentions-select"}),
        help_text="Tapez @ dans le texte, recherchez un utilisateur puis sélectionnez-le.",
    )

    class Meta:
        model = Publication
        fields = ["texte", "image"]
        widgets = {
            "texte": forms.Textarea(attrs={
                "rows": 5, "placeholder": "Partagez une recette, une astuce ou votre progrès… Tapez @ pour mentionner quelqu'un.",
                "data-mention-input": "",
            }),
        }
        help_texts = {"image": "JPEG, PNG ou WebP, 8 Mo maximum."}

    def __init__(self, *args, utilisateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.utilisateur = utilisateur
        qs = User.objects.filter(is_active=True).order_by("username")
        if utilisateur:
            qs = qs.exclude(pk=utilisateur.pk)
        self.fields["mentions"].queryset = qs
        if self.instance.pk:
            self.fields["mentions"].initial = self.instance.mentions.all()

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image:
            return image
        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("L'image dépasse 8 Mo.")
        type_contenu = getattr(image, "content_type", "")
        if type_contenu and type_contenu not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Utilisez une image JPEG, PNG ou WebP.")
        return image

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("texte") or "").strip() and not cleaned.get("image") and not self.instance.image:
            raise forms.ValidationError("Ajoutez un texte ou une image à votre publication.")
        texte = cleaned.get("texte") or ""
        for utilisateur in cleaned.get("mentions") or []:
            if not re.search(rf"(?<![\w@])@{re.escape(utilisateur.username)}\b", texte, re.IGNORECASE):
                texte = f"{texte.rstrip()} @{utilisateur.username}".strip()
        cleaned["texte"] = texte
        self.instance.texte = texte
        return cleaned

    def enregistrer_mentions(self, publication):
        choisis = self.cleaned_data.get("mentions") or []
        Mention.objects.filter(publication=publication).exclude(utilisateur__in=choisis).delete()
        for utilisateur in choisis:
            Mention.objects.get_or_create(publication=publication, utilisateur=utilisateur)


class CommentaireForm(forms.ModelForm):
    class Meta:
        model = Commentaire
        fields = ["contenu"]
        widgets = {"contenu": forms.TextInput(attrs={"placeholder": "Ajouter un commentaire…", "maxlength": 500})}
