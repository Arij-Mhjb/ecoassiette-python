from datetime import timedelta

from django import forms
from django.utils import timezone


def lundi_de(date):
    return date - timedelta(days=date.weekday())


class PlanMenuForm(forms.Form):
    semaine_du = forms.DateField(
        label="Semaine à planifier",
        initial=lambda: lundi_de(timezone.localdate()),
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="La date sera automatiquement ramenée au lundi de la semaine.",
    )
    objectif_co2 = forms.DecimalField(
        label="Objectif carbone de la semaine (kg CO₂e)", min_value=0.1, max_value=200,
        initial=20, decimal_places=2,
    )

    def clean_semaine_du(self):
        return lundi_de(self.cleaned_data["semaine_du"])
