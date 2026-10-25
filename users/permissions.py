from functools import wraps

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


# --------------------------------------------------------------------------- rôle citoyen
# Le suivi des repas, le profil alimentaire et son analyse IA sont des fonctions *citoyennes* :
# un administrateur ou un nutritionniste n'y a pas accès (principe du moindre privilège).
def est_citoyen(user):
    return user.is_authenticated and user.role == user.Role.CITOYEN


class CitoyenRequisMixin:
    """Vue réservée aux citoyens : anonyme -> connexion, autre rôle -> 403."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not est_citoyen(request.user):
            raise PermissionDenied("Cette fonctionnalité est réservée aux citoyens.")
        return super().dispatch(request, *args, **kwargs)


def citoyen_requis(vue):
    @wraps(vue)
    def _vue(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not est_citoyen(request.user):
            raise PermissionDenied("Cette fonctionnalité est réservée aux citoyens.")
        return vue(request, *args, **kwargs)
    return _vue
