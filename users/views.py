import logging

from django.conf import settings

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import (
    AdminUtilisateurCreationForm, AdminUtilisateurForm, ConnexionForm, FiltreUtilisateursForm,
    InfosPersonnellesForm, InscriptionForm, ProfilAlimentaireForm, RenvoyerConfirmationForm,
    SuppressionCompteForm,
)
from .emails import envoyer_confirmation, jeton_confirmation, notifier_changement_mdp
from .models import AnalyseProfilIA, ProfilAlimentaire
from .permissions import PermissionOu403Mixin
from .tasks import lancer_analyse

User = get_user_model()
logger = logging.getLogger(__name__)


# =============================================================== authentification
def inscription(request):
    if request.user.is_authenticated:
        return redirect("users:profil")
    form = InscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if not settings.CONFIRMATION_EMAIL:  # pas de service d'e-mail : activation directe
            user.email_verifie = True
            user.save(update_fields=["email_verifie"])
            login(request, user, backend="users.backends.EmailOuUsernameBackend")
            messages.success(request, f"Bienvenue {user.first_name} ! Complétez votre profil pour une analyse personnalisée.")
            return redirect("users:modifier_profil")
        # sinon : connexion bloquée tant que l'e-mail n'est pas confirmé
        envoye = envoyer_confirmation(request, user)
        request.session["email_a_confirmer"] = user.email
        if not envoye:
            messages.error(request, "Votre compte est créé mais l'e-mail n'a pas pu être envoyé. "
                                    "Réessayez avec « Renvoyer le lien ».")
        return redirect("users:verification_envoyee")
    return render(request, "users/inscription.html", {"form": form})


def verification_envoyee(request):
    return render(request, "users/verification_envoyee.html",
                  {"email": request.session.get("email_a_confirmer", "")})


def confirmer_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is None or not jeton_confirmation.check_token(user, token):
        if user is not None and user.email_verifie:
            messages.info(request, "Votre adresse est déjà confirmée : vous pouvez vous connecter.")
            return redirect("users:login")
        return render(request, "users/lien_invalide.html", status=400)
    user.email_verifie = True
    user.save(update_fields=["email_verifie"])
    request.session.pop("email_a_confirmer", None)
    login(request, user, backend="users.backends.EmailOuUsernameBackend")
    messages.success(request, f"Adresse confirmée, bienvenue {user.first_name or user.username} ! "
                              "Complétez votre profil pour une analyse personnalisée.")
    return redirect("users:modifier_profil")


def renvoyer_confirmation(request):
    form = RenvoyerConfirmationForm(request.POST or None,
                                    initial={"email": request.session.get("email_a_confirmer", "")})
    if request.method == "POST" and form.is_valid():
        user = User.objects.filter(email__iexact=form.cleaned_data["email"], email_verifie=False,
                                   is_active=True).first()
        if user:
            envoyer_confirmation(request, user)
        request.session["email_a_confirmer"] = form.cleaned_data["email"]
        # même réponse que le compte existe ou non (anti-énumération)
        messages.success(request, "Si un compte non confirmé correspond à cette adresse, un nouveau lien vient d'être envoyé.")
        return redirect("users:verification_envoyee")
    return render(request, "users/form_page.html", {
        "form": form, "titre": "Renvoyer le lien de confirmation",
        "intro": "Le lien précédent a expiré ou vous ne l'avez pas reçu ? Recevez-en un nouveau.",
    })


class ConnexionView(auth_views.LoginView):
    template_name = "users/connexion.html"
    authentication_form = ConnexionForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        messages.success(self.request, "Connexion réussie.")
        return super().form_valid(form)


class ReinitialisationConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "users/form_page.html"
    success_url = reverse_lazy("users:password_reset_complete")
    extra_context = {"titre": "Nouveau mot de passe"}

    def form_valid(self, form):
        reponse = super().form_valid(form)
        user = form.user
        if not user.email_verifie:  # cliquer sur le lien prouve aussi la possession de l'e-mail
            user.email_verifie = True
            user.save(update_fields=["email_verifie"])
        notifier_changement_mdp(self.request, user)
        return reponse


class DeconnexionView(auth_views.LogoutView):
    next_page = reverse_lazy("home")


# ======================================================================= citoyen
@login_required
def profil(request):
    p = request.user.profil
    derniere = p.analyses.filter(statut=AnalyseProfilIA.Statut.TERMINE).first()
    return render(request, "users/profil.html", {"profil": p, "analyse": derniere})


@login_required
def modifier_infos(request):
    form = InfosPersonnellesForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Informations personnelles mises à jour.")
            return redirect("users:profil")
        messages.error(request, "Le formulaire contient des erreurs.")
    return render(request, "users/form_page.html", {
        "form": form, "titre": "Mes informations personnelles", "multipart": True,
    })


@login_required
def modifier_profil(request):
    form = ProfilAlimentaireForm(request.POST or None, instance=request.user.profil)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Profil alimentaire enregistré.")
            return redirect("users:profil")
        messages.error(request, "Le formulaire contient des erreurs.")
    return render(request, "users/form_page.html", {
        "form": form, "titre": "Mes habitudes alimentaires",
        "intro": "Ces informations personnalisent le calcul de votre empreinte et les alternatives proposées.",
    })


@login_required
def supprimer_compte(request):
    form = SuppressionCompteForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, "Votre compte et vos données ont été supprimés.")
        return redirect("home")
    return render(request, "users/supprimer_compte.html", {"form": form})


class ChangementMotDePasseView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = "users/form_page.html"
    success_url = reverse_lazy("users:profil")
    extra_context = {"titre": "Changer mon mot de passe"}

    def form_valid(self, form):
        reponse = super().form_valid(form)
        notifier_changement_mdp(self.request, self.request.user)
        messages.success(self.request, "Mot de passe modifié. Un e-mail de confirmation vous a été envoyé.")
        return reponse


# ============================================================ IA (asynchrone)
def _analyse_json(a):
    return {
        "id": a.pk,
        "statut": a.statut,
        "statut_libelle": a.get_statut_display(),
        "termine": a.est_terminee,
        "source": a.source,
        "duree_ms": a.duree_ms,
        "resultat": a.resultat if a.statut == AnalyseProfilIA.Statut.TERMINE else None,
        "erreur": "L'analyse a échoué, veuillez réessayer." if a.statut == AnalyseProfilIA.Statut.ECHEC else "",
        "url_etat": reverse("users:analyse_etat", args=[a.pk]),
    }


@login_required
@require_POST
def analyse_lancer(request):
    p = request.user.profil
    # anti-spam : une analyse en cours de moins de 2 minutes est réutilisée
    en_cours = p.analyses.filter(
        statut__in=[AnalyseProfilIA.Statut.EN_ATTENTE, AnalyseProfilIA.Statut.EN_COURS],
        cree_le__gte=timezone.now() - timezone.timedelta(minutes=2),
    ).first()
    analyse = en_cours or lancer_analyse(p)
    return JsonResponse(_analyse_json(analyse), status=202)


@login_required
@require_GET
def analyse_etat(request, pk):
    analyse = get_object_or_404(AnalyseProfilIA, pk=pk, profil__utilisateur=request.user)
    return JsonResponse(_analyse_json(analyse))


@login_required
@require_POST
def appliquer_objectif(request, pk):
    analyse = get_object_or_404(AnalyseProfilIA, pk=pk, profil__utilisateur=request.user,
                                statut=AnalyseProfilIA.Statut.TERMINE)
    p = request.user.profil
    try:
        p.objectif_co2_hebdo = round(float(analyse.resultat["objectif_recommande_kg"]), 1)
        p.full_clean()
        p.save()
        messages.success(request, f"Objectif fixé à {p.objectif_co2_hebdo} kg CO₂e par semaine.")
    except (KeyError, TypeError, ValueError, ValidationError) as e:
        logger.info("Objectif IA non applicable : %s", e)
        messages.error(request, "Impossible d'appliquer cet objectif à votre profil actuel. Relancez une analyse.")
    return redirect("users:profil")


# ================================================================= nutritionniste
class ProfilsVisiblesMixin(PermissionOu403Mixin):
    """Un nutritionniste ne voit que les profils citoyens partagés (profil_public)."""
    permission_required = "users.view_profilalimentaire"

    def profils_visibles(self):
        qs = ProfilAlimentaire.objects.select_related("utilisateur").filter(
            utilisateur__role=User.Role.CITOYEN, utilisateur__is_active=True
        )
        if not self.request.user.has_perm("users.gerer_utilisateurs"):
            qs = qs.filter(profil_public=True)
        return qs


class ProfilsPublicsView(ProfilsVisiblesMixin, ListView):
    template_name = "users/nutri_profils.html"
    context_object_name = "profils"
    paginate_by = 12

    def get_queryset(self):
        qs = self.profils_visibles()
        regime = self.request.GET.get("regime")
        if regime in ProfilAlimentaire.Regime.values:
            qs = qs.filter(regime=regime)
        return qs.order_by("utilisateur__last_name")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["regimes"] = ProfilAlimentaire.Regime.choices
        ctx["regime_actif"] = self.request.GET.get("regime", "")
        return ctx


class ProfilPublicDetailView(ProfilsVisiblesMixin, DetailView):
    template_name = "users/nutri_profil_detail.html"
    context_object_name = "profil"

    def get_queryset(self):
        return self.profils_visibles()

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["analyse"] = self.object.analyses.filter(statut=AnalyseProfilIA.Statut.TERMINE).first()
        return ctx


# ===================================================== administration : CRUD comptes
class AdminRequisMixin(PermissionOu403Mixin):
    permission_required = "users.gerer_utilisateurs"


class UtilisateurListView(AdminRequisMixin, ListView):
    model = User
    template_name = "users/admin/liste.html"
    context_object_name = "utilisateurs"
    paginate_by = 10

    def get_queryset(self):
        qs = User.objects.select_related("profil").order_by("-date_joined")
        self.filtre = FiltreUtilisateursForm(self.request.GET or None)
        if self.filtre.is_valid():
            q = self.filtre.cleaned_data["q"].strip()
            if q:
                qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q)
                               | Q(first_name__icontains=q) | Q(last_name__icontains=q))
            if self.filtre.cleaned_data["role"]:
                qs = qs.filter(role=self.filtre.cleaned_data["role"])
            if self.filtre.cleaned_data["actif"] in ("0", "1"):
                qs = qs.filter(is_active=self.filtre.cleaned_data["actif"] == "1")
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["filtre"] = self.filtre
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["params"] = params.urlencode()
        return ctx


class UtilisateurDetailView(AdminRequisMixin, DetailView):
    model = User
    template_name = "users/admin/detail.html"
    context_object_name = "cible"


class UtilisateurCreateView(AdminRequisMixin, CreateView):
    model = User
    form_class = AdminUtilisateurCreationForm
    template_name = "users/form_page.html"
    extra_context = {"titre": "Créer un compte"}

    def form_valid(self, form):
        messages.success(self.request, "Compte créé.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("users:admin_detail", args=[self.object.pk])


class UtilisateurUpdateView(AdminRequisMixin, UpdateView):
    model = User
    form_class = AdminUtilisateurForm
    template_name = "users/form_page.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["editeur"] = self.request.user
        return kw

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["titre"] = f"Modifier le compte de {self.object}"
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Compte mis à jour.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("users:admin_detail", args=[self.object.pk])


class UtilisateurDeleteView(AdminRequisMixin, DeleteView):
    model = User
    template_name = "users/admin/supprimer.html"
    context_object_name = "cible"
    success_url = reverse_lazy("users:admin_liste")

    def form_valid(self, form):
        if self.get_object().pk == self.request.user.pk:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte depuis l'administration.")
            return redirect("users:admin_detail", pk=self.request.user.pk)
        messages.success(self.request, "Compte supprimé.")
        return super().form_valid(form)


class UtilisateurBasculerActifView(AdminRequisMixin, DetailView):
    model = User
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        cible = self.get_object()
        if cible.pk == request.user.pk:
            messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
        else:
            cible.is_active = not cible.is_active
            cible.save(update_fields=["is_active"])
            messages.success(request, f"Compte {'activé' if cible.is_active else 'désactivé'} : {cible}.")
        return redirect(request.POST.get("next") or "users:admin_liste")


class StatistiquesView(PermissionOu403Mixin, TemplateView):
    permission_required = "users.voir_statistiques"
    template_name = "users/admin/statistiques.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        total = User.objects.count()
        par_role = {r: 0 for r, _ in User.Role.choices}
        par_role.update({x["role"]: x["n"] for x in User.objects.values("role").annotate(n=Count("id"))})
        libelles = dict(ProfilAlimentaire.Regime.choices)
        regimes = [
            {"libelle": libelles[x["regime"]], "n": x["n"], "pct": round(100 * x["n"] / max(total, 1))}
            for x in ProfilAlimentaire.objects.values("regime").annotate(n=Count("id")).order_by("-n")
        ]
        analyses = AnalyseProfilIA.objects.all()
        fin = analyses.filter(statut=AnalyseProfilIA.Statut.TERMINE)
        durees = sorted(fin.exclude(duree_ms=None).values_list("duree_ms", flat=True))
        p95 = durees[min(len(durees) - 1, int(0.95 * len(durees)))] if durees else None
        ctx.update({
            "total": total,
            "actifs": User.objects.filter(is_active=True).count(),
            "par_role": [(lib, par_role[r]) for r, lib in User.Role.choices],
            "regimes": regimes,
            "avec_objectif": ProfilAlimentaire.objects.exclude(objectif_co2_hebdo=None).count(),
            "ia_total": analyses.count(),
            "ia_succes": fin.count(),
            "ia_gemini": fin.filter(source="GEMINI").count(),
            "ia_local": fin.filter(source="LOCAL").count(),
            "ia_echecs": analyses.filter(statut=AnalyseProfilIA.Statut.ECHEC).count(),
            "ia_moyenne_ms": int(fin.aggregate(m=Avg("duree_ms"))["m"] or 0),
            "ia_p95_ms": p95,
            "inscrits_7j": User.objects.filter(date_joined__gte=timezone.now() - timezone.timedelta(days=7)).count(),
        })
        return ctx


# ========================================================= pages d'erreur
def erreur_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def erreur_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def erreur_500(request):
    return render(request, "errors/500.html", status=500)
