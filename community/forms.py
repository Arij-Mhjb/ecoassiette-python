import re

from django import forms
from django.contrib.auth import get_user_model

from .ai import ErreurGenerationImage, decoder_token_image

from .models import Commentaire, Mention, MentionCommentaire, Publication

User = get_user_model()


class PublicationForm(forms.ModelForm):
    image_ia_token = forms.CharField(required=False, widget=forms.HiddenInput())
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

    def clean_image_ia_token(self):
        token = self.cleaned_data.get("image_ia_token", "")
        self.chemin_image_ia = ""
        if token:
            try:
                self.chemin_image_ia = decoder_token_image(token, self.utilisateur.pk)
            except ErreurGenerationImage as exc:
                raise forms.ValidationError(str(exc)) from exc
        return token

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("texte") or "").strip() and not cleaned.get("image") and not cleaned.get("image_ia_token") and not self.instance.image:
            raise forms.ValidationError("Ajoutez un texte ou une image à votre publication.")
        texte = cleaned.get("texte") or ""
        for utilisateur in cleaned.get("mentions") or []:
            if not re.search(rf"(?<![\w@])@{re.escape(utilisateur.username)}\b", texte, re.IGNORECASE):
                texte = f"{texte.rstrip()} @{utilisateur.username}".strip()
        cleaned["texte"] = texte
        self.instance.texte = texte
        return cleaned

    def appliquer_image_ia(self, publication):
        if self.cleaned_data.get("image"):
            publication.image_generee_ia = False
            publication.modele_image_ia = ""
            return False
        if not getattr(self, "chemin_image_ia", ""):
            return False
        publication.image.name = self.chemin_image_ia
        publication.image_generee_ia = True
        publication.modele_image_ia = "Pollinations / Flux"
        return True

    def enregistrer_mentions(self, publication):
        choisis = self.cleaned_data.get("mentions") or []
        Mention.objects.filter(publication=publication).exclude(utilisateur__in=choisis).delete()
        nouveaux = []
        for utilisateur in choisis:
            _, creee = Mention.objects.get_or_create(publication=publication, utilisateur=utilisateur)
            if creee:
                nouveaux.append(utilisateur)
        return nouveaux


class CommentaireForm(forms.ModelForm):
    class Meta:
        model = Commentaire
        fields = ["contenu"]
        widgets = {"contenu": forms.TextInput(attrs={
            "placeholder": "Ajouter un commentaire… Utilisez @ pour mentionner",
            "maxlength": 500, "data-mention-input": "",
        })}

    def enregistrer_mentions(self, commentaire):
        pseudos = set(re.findall(r"(?<![\w@])@([\w.-]{1,150})", commentaire.contenu))
        utilisateurs = User.objects.filter(username__in=pseudos, is_active=True).exclude(pk=commentaire.auteur_id)
        for utilisateur in utilisateurs:
            MentionCommentaire.objects.get_or_create(commentaire=commentaire, utilisateur=utilisateur)
        return list(utilisateurs)
