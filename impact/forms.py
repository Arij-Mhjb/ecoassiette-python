from django import forms
from django.forms import formset_factory
from django.utils import timezone

from repas.models import ElementRepas, Repas


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
