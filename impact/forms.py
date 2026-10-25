from django import forms
from django.forms import formset_factory
from django.utils import timezone

from repas.models import ElementRepas, Repas

from .models import PreuveRepas


class RecetteAssistantForm(forms.Form):
    type_repas = forms.ChoiceField(label="Type de repas", choices=Repas.TypeRepas.choices)
    date = forms.DateField(
        label="Date", initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    note = forms.CharField(label="Nom du plat", max_length=200, required=False)
    texte = forms.CharField(
        label="Recette ou liste d'ingrédients",
        widget=forms.Textarea(attrs={
            "rows": 8,
            "placeholder": "Ex. Couscous pour 2 personnes : 300 g d'agneau, 200 g de pois chiches, 2 tomates, 150 g de semoule...",
        }),
        help_text="Indiquez autant que possible les quantités. Vous pourrez corriger le résultat avant validation.",
    )

    def clean_date(self):
        valeur = self.cleaned_data["date"]
        if valeur > timezone.localdate():
            raise forms.ValidationError("La date ne peut pas être dans le futur.")
        return valeur


class IngredientExtraitForm(forms.Form):
    aliment = forms.CharField(label="Ingrédient", max_length=100)
    categorie = forms.ChoiceField(label="Catégorie", choices=ElementRepas.Categorie.choices)
    quantite_g = forms.IntegerField(
        label="Quantité (g)", min_value=1, max_value=3000,
        widget=forms.NumberInput(attrs={"min": 1, "max": 3000}),
    )
    utiliser_alternative = forms.BooleanField(
        label="Utiliser l'alternative végétale", required=False
    )


IngredientExtraitFormSet = formset_factory(
    IngredientExtraitForm, extra=0, min_num=1, validate_min=True, can_delete=True
)


class GardeMangerForm(forms.Form):
    ingredients_maison = forms.CharField(
        label="Ingrédients disponibles à la maison",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Ex. tomates, courgettes, riz, pois chiches, citron"}),
        help_text="Séparez les ingrédients par des virgules. L'IA privilégiera ces produits.",
    )


class RepasPreuveChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, repas):
        aliments = ", ".join(repas.elements.values_list("aliment", flat=True)[:3])
        nom = repas.note.strip() or aliments or "Repas sans nom"
        return f"{nom} — {repas.get_type_repas_display()} — {repas.date:%d/%m/%Y}"


class PreuveRepasForm(forms.ModelForm):
    repas = RepasPreuveChoiceField(queryset=Repas.objects.none(), label="Repas réalisé")

    class Meta:
        model = PreuveRepas
        fields = ["repas", "media"]
        labels = {"repas": "Repas végétalisé", "media": "Photo ou vidéo de la réalisation"}
        help_texts = {"media": "JPG, PNG, WebP, MP4, WebM ou MOV — 25 Mo maximum."}

    def __init__(self, *args, utilisateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repas"].queryset = Repas.objects.none()
        if utilisateur:
            self.fields["repas"].queryset = Repas.objects.filter(
                utilisateur=utilisateur, preuve_ecologique__isnull=True,
            ).prefetch_related("elements").distinct()

    def clean_media(self):
        media = self.cleaned_data["media"]
        if media.size > 25 * 1024 * 1024:
            raise forms.ValidationError("Le fichier dépasse 25 Mo.")
        content_type = getattr(media, "content_type", "")
        autorises = {"image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm", "video/quicktime"}
        if content_type not in autorises:
            raise forms.ValidationError("Format de photo ou vidéo non autorisé.")
        self.type_media = "IMAGE" if content_type.startswith("image/") else "VIDEO"
        return media
