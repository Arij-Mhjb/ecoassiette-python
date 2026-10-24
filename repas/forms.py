from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import ElementRepas, Repas


class RepasForm(forms.ModelForm):
    class Meta:
        model = Repas
        fields = ["type_repas", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.TextInput(attrs={"placeholder": "ex. repas en famille"}),
        }

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > timezone.localdate():
            raise forms.ValidationError("La date ne peut pas être dans le futur.")
        return date


class ElementRepasForm(forms.ModelForm):
    class Meta:
        model = ElementRepas
        fields = ["aliment", "categorie", "quantite_g"]
        widgets = {
            "aliment": forms.TextInput(attrs={"placeholder": "ex. couscous"}),
            "quantite_g": forms.NumberInput(attrs={"min": 1, "max": 3000}),
        }

    def clean_aliment(self):
        aliment = self.cleaned_data["aliment"].strip()
        if aliment.isdigit():
            raise forms.ValidationError("Le nom de l'aliment ne peut pas être un nombre.")
        return aliment.lower()


ElementRepasFormSet = inlineformset_factory(
    Repas,
    ElementRepas,
    form=ElementRepasForm,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
