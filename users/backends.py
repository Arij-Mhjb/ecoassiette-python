from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOuUsernameBackend(ModelBackend):
    """Connexion avec le nom d'utilisateur OU l'adresse e-mail (requête ORM, pas de SQL brut)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        champ = "email__iexact" if "@" in username else "username__iexact"
        try:
            user = User.objects.get(**{champ: username.strip()})
        except User.DoesNotExist:
            User().set_password(password)  # temps constant (anti-énumération)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
