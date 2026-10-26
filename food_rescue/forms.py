from django import forms
from django.utils import timezone

from .models import AnnonceSurplus, ProfilBeneficiaire, ReservationSurplus


class AnnonceSurplusForm(forms.ModelForm):
    class Meta:
        model = AnnonceSurplus
        fields = [
            "titre", "description", "categorie", "quantite", "unite", "conservation",
            "allergenes", "ville", "lieu_collecte", "disponible_jusquau", "photo",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "disponible_jusquau": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }
        help_texts = {
            "allergenes": "À vérifier par le donateur. L'IA ne remplace pas l'étiquetage alimentaire.",
            "photo": "JPEG, PNG ou WebP, 8 Mo maximum. L'image est facultative.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["disponible_jusquau"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_disponible_jusquau(self):
        valeur = self.cleaned_data["disponible_jusquau"]
        if valeur <= timezone.now():
            raise forms.ValidationError("Choisissez une date et une heure futures.")
        return valeur

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return photo
        if photo.size > 8 * 1024 * 1024:
            raise forms.ValidationError("La photo dépasse 8 Mo.")
        type_contenu = getattr(photo, "content_type", "")
        if type_contenu and type_contenu not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Utilisez une image JPEG, PNG ou WebP.")
        return photo


class ReservationSurplusForm(forms.ModelForm):
    class Meta:
        model = ReservationSurplus
        fields = ["heure_collecte", "message"]
        widgets = {
            "heure_collecte": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "Précisez votre disponibilité..."}),
        }

    def __init__(self, *args, annonce=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.annonce = annonce
        self.fields["heure_collecte"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_heure_collecte(self):
        valeur = self.cleaned_data["heure_collecte"]
        if valeur <= timezone.now():
            raise forms.ValidationError("L'heure de collecte doit être future.")
        if self.annonce and valeur > self.annonce.disponible_jusquau:
            raise forms.ValidationError("La collecte doit avoir lieu avant la fin de disponibilité.")
        return valeur


class ProfilBeneficiaireForm(forms.ModelForm):
    attestation = forms.BooleanField(
        label="J'atteste que les informations fournies sont exactes",
        help_text="Une fausse déclaration peut entraîner la suspension de l'accès aux dons.",
    )

    class Meta:
        model = ProfilBeneficiaire
        fields = ["type_beneficiaire", "organisme", "reference_justificatif"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.statut = ProfilBeneficiaire.Statut.EN_ATTENTE
        instance.motif_refus = ""
        instance.verifie_par = None
        instance.verifie_le = None
        if commit:
            instance.save()
        return instance

