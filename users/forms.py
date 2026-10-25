from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import DemandeNutritionniste, Invitation, ProfilAlimentaire

User = get_user_model()


class AccessibleFormMixin:
    """Ajoute aria-describedby / aria-invalid sur les champs (aide + erreurs)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nom, champ in self.fields.items():
            if champ.help_text:
                champ.widget.attrs["aria-describedby"] = f"id_{nom}_aide"
            if champ.required:
                champ.widget.attrs["required"] = True

    def full_clean(self):
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                w = self.fields[nom].widget
                w.attrs["aria-invalid"] = "true"
                ids = [f"id_{nom}_erreurs"]
                if self.fields[nom].help_text:
                    ids.append(f"id_{nom}_aide")
                w.attrs["aria-describedby"] = " ".join(ids)


def _email_libre(email, exclure_pk=None):
    email = (email or "").strip().lower()
    qs = User.objects.filter(email__iexact=email)
    if exclure_pk:
        qs = qs.exclude(pk=exclure_pk)
    if qs.exists():
        raise forms.ValidationError("Un compte existe déjà avec cette adresse e-mail.")
    return email


_DEMANDE = DemandeNutritionniste._meta


class InscriptionForm(AccessibleFormMixin, UserCreationForm):
    type_compte = forms.ChoiceField(
        label="Je suis", widget=forms.RadioSelect, initial="CITOYEN", required=False,   # par défaut : citoyen
        choices=[("CITOYEN", "Citoyen·ne — je veux suivre et réduire l'empreinte de mon alimentation"),
                 ("NUTRITIONNISTE", "Nutritionniste — je veux accompagner des citoyens (validation requise)")],
    )
    email = forms.EmailField(label="Adresse e-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    first_name = forms.CharField(label="Prénom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label="Nom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    numero_ordre = _DEMANDE.get_field("numero_ordre").formfield(required=False)
    etablissement = _DEMANDE.get_field("etablissement").formfield(required=False)
    regime = forms.ChoiceField(label="Votre régime actuel", choices=ProfilAlimentaire.Regime.choices,
                               initial=ProfilAlimentaire.Regime.OMNIVORE)
    consentement = forms.BooleanField(
        label="J'accepte que mes habitudes alimentaires soient utilisées pour calculer mon empreinte carbone.",
    )
    CHAMPS_NUTRI = ("numero_ordre", "etablissement")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ordre = ["type_compte", "numero_ordre", "etablissement"]
        self.order_fields(ordre + [n for n in self.fields if n not in ordre])
        for n in self.CHAMPS_NUTRI:
            self.fields[n].widget.attrs["data-nutri"] = "1"

    @property
    def est_nutritionniste(self):
        return self.cleaned_data.get("type_compte") == "NUTRITIONNISTE"

    def clean_type_compte(self):
        return self.cleaned_data.get("type_compte") or "CITOYEN"

    def clean_email(self):
        return _email_libre(self.cleaned_data.get("email"))

    def clean(self):
        data = super().clean()
        if data.get("type_compte") == "NUTRITIONNISTE":
            for n in self.CHAMPS_NUTRI:
                if not data.get(n) and n not in self.errors:
                    self.add_error(n, "Obligatoire pour une demande de statut nutritionniste.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        # Le rôle n'est JAMAIS choisi librement : un nutritionniste reste citoyen jusqu'à validation par un admin.
        user.role = User.Role.CITOYEN
        if commit:
            user.save()
            user.profil.regime = self.cleaned_data["regime"]
            user.profil.save()
            if self.est_nutritionniste:
                self.demande = DemandeNutritionniste.objects.create(
                    utilisateur=user, numero_ordre=self.cleaned_data["numero_ordre"],
                    etablissement=self.cleaned_data["etablissement"],
                )
        return user


class ConnexionForm(AccessibleFormMixin, AuthenticationForm):
    username = forms.CharField(
        label="Nom d'utilisateur ou e-mail",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    error_messages = {
        "invalid_login": "Identifiants incorrects. Vérifiez votre nom d'utilisateur/e-mail et votre mot de passe.",
        "inactive": "Ce compte est désactivé. Contactez un administrateur.",
        "email_non_verifie": (
            "Votre adresse e-mail n'est pas encore confirmée. Cliquez sur le lien reçu par e-mail "
            "(pensez aux spams) ou demandez un nouveau lien."
        ),
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.email_verifie:
            self.email_non_verifie = True
            raise forms.ValidationError(self.error_messages["email_non_verifie"], code="email_non_verifie")


class RenvoyerConfirmationForm(AccessibleFormMixin, forms.Form):
    email = forms.EmailField(label="Adresse e-mail utilisée à l'inscription",
                             widget=forms.EmailInput(attrs={"autocomplete": "email"}))


class InfosPersonnellesForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "telephone", "avatar")
        widgets = {"avatar": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"})}

    def clean_email(self):
        return _email_libre(self.cleaned_data.get("email"), exclure_pk=self.instance.pk)

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and hasattr(avatar, "size") and avatar.size > 2 * 1024 * 1024:
            raise forms.ValidationError("L'image ne doit pas dépasser 2 Mo.")
        return avatar


class ProfilAlimentaireForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = ProfilAlimentaire
        fields = (
            "regime", "aliments_aimes", "aliments_evites", "taille_foyer",
            "niveau_activite", "temps_cuisine", "ville", "objectif_co2_hebdo", "profil_public",
        )
        widgets = {
            "aliments_aimes": forms.TextInput(attrs={"placeholder": "couscous, pâtes, poulet"}),
            "aliments_evites": forms.TextInput(attrs={"placeholder": "aubergines, champignons"}),
            "objectif_co2_hebdo": forms.NumberInput(attrs={"step": "0.5", "min": "5", "max": "100"}),
            "taille_foyer": forms.NumberInput(attrs={"min": "1", "max": "15"}),
        }


class SuppressionCompteForm(AccessibleFormMixin, forms.Form):
    password = forms.CharField(label="Confirmez avec votre mot de passe",
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        pwd = self.cleaned_data["password"]
        if not self.user.check_password(pwd):
            raise forms.ValidationError("Mot de passe incorrect.")
        return pwd


# ------------------------------------------------------------- administration (CRUD)
class RoleSelonEditeurMixin:
    """Seul un super-administrateur peut attribuer le rôle Administrateur."""

    def __init__(self, *args, editeur=None, **kwargs):
        self.editeur = editeur
        super().__init__(*args, **kwargs)
        if not (editeur and editeur.is_superuser):
            self.fields["role"].choices = [c for c in self.fields["role"].choices if c[0] != User.Role.ADMIN]
            self.fields["role"].help_text = "Le rôle Administrateur ne peut être attribué que par un super-administrateur."


class AdminUtilisateurCreationForm(RoleSelonEditeurMixin, AccessibleFormMixin, forms.ModelForm):
    password1 = forms.CharField(label="Mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirmation", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "telephone", "role", "is_active")

    def clean_email(self):
        return _email_libre(self.cleaned_data.get("email"))

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
        elif p1:
            tmp = User(username=data.get("username"), email=data.get("email"))
            try:
                password_validation.validate_password(p1, tmp)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.email_verifie = True  # compte créé par un administrateur
        if commit:
            user.save()
        return user


class AdminUtilisateurForm(RoleSelonEditeurMixin, AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "telephone", "role", "is_active")

    def clean_email(self):
        return _email_libre(self.cleaned_data.get("email"), exclure_pk=self.instance.pk)

    def clean(self):
        data = super().clean()
        if self.editeur and self.editeur.pk == self.instance.pk:
            if data.get("role") != User.Role.ADMIN or not data.get("is_active"):
                raise forms.ValidationError("Vous ne pouvez pas retirer vos propres droits d'administrateur.")
        return data


class FiltreUtilisateursForm(forms.Form):
    q = forms.CharField(label="Rechercher", required=False,
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Nom, e-mail…"}))
    role = forms.ChoiceField(label="Rôle", required=False, choices=[("", "Tous les rôles")] + list(User.Role.choices))
    actif = forms.ChoiceField(label="Statut", required=False,
                              choices=[("", "Tous"), ("1", "Actifs"), ("0", "Désactivés")])


# ------------------------------------------------------------- rôle nutritionniste
class DemandeNutritionnisteForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = DemandeNutritionniste
        fields = ("numero_ordre", "etablissement", "message")
        widgets = {"message": forms.Textarea(attrs={"rows": 3, "placeholder": "Spécialité, expérience…"})}


class RefusDemandeForm(forms.Form):
    motif = forms.CharField(label="Motif du refus", max_length=300,
                            widget=forms.TextInput(attrs={"placeholder": "ex. numéro introuvable auprès de l'Ordre"}))


class InvitationForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ("email", "first_name", "last_name")
        labels = {"email": "Adresse e-mail de la nutritionniste"}

    def clean_email(self):
        return _email_libre(self.cleaned_data.get("email"))


class AccepterInvitationForm(AccessibleFormMixin, UserCreationForm):
    first_name = forms.CharField(label="Prénom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label="Nom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name")

    def __init__(self, *args, invitation, **kwargs):
        self.invitation = invitation
        kwargs.setdefault("initial", {}).update(first_name=invitation.first_name, last_name=invitation.last_name)
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        _email_libre(self.invitation.email)  # l'adresse a pu être utilisée entre-temps
        return data

    def _post_clean(self):
        self.instance.email = self.invitation.email   # pour la validation « mot de passe trop proche de l'e-mail »
        super()._post_clean()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.invitation.email
        user.role = self.invitation.role
        user.email_verifie = True    # le lien reçu par e-mail prouve la possession de l'adresse
        if commit:
            user.save()
        return user
