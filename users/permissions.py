from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


class PermissionOu403Mixin(PermissionRequiredMixin):
    """
    - visiteur anonyme      -> redirection vers la page de connexion
    - connecté sans droits  -> 403 (page personnalisée)
    Empêche tout contournement par URL directe.
    """

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect_to_login(self.request.get_full_path(), self.get_login_url(), self.get_redirect_field_name())
        raise PermissionDenied("Vous n'avez pas les droits nécessaires pour accéder à cette page.")
