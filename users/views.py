import logging

from django.conf import settings

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import (
    RecommandationForm,
    AccepterInvitationForm, AdminUtilisateurCreationForm, AdminUtilisateurForm, ConnexionForm,
    DemandeNutritionnisteForm, FiltreUtilisateursForm, InfosPersonnellesForm, InscriptionForm, InvitationForm,
    ProfilAlimentaireForm, RefusDemandeForm, RenvoyerConfirmationForm, SuppressionCompteForm,
)
from .emails import (
    notifier_recommandation,
    envoyer_confirmation, envoyer_invitation, jeton_confirmation, lien_invitation, notifier_admins_demande,
    notifier_changement_mdp, notifier_demande_traitee,
)
from .models import AnalyseProfilIA, DemandeNutritionniste, Invitation, JournalAudit, ProfilAlimentaire, Recommandation
from .export_pdf import generer_pdf
from .securite import deconnecter_autres_appareils, journaliser
from .permissions import PermissionOu403Mixin, citoyen_requis
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
        journaliser(request, JournalAudit.Action.INSCRIPTION, cible=user.username,
                    details=f"rôle demandé : {'nutritionniste' if form.est_nutritionniste else 'citoyen'}", acteur=user)
        if form.est_nutritionniste:
            notifier_admins_demande(request, form.demande)
            messages.info(request, "Votre demande de statut nutritionniste a été transmise : un administrateur va "
                                   "vérifier votre numéro d'ordre. Vous recevrez un e-mail dès qu'elle sera traitée.")
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
    journaliser(request, JournalAudit.Action.EMAIL_CONFIRME, cible=user.email, acteur=user)
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
        journaliser(self.request, JournalAudit.Action.MDP_REINITIALISE, cible=user.username,
                    details="via le lien « mot de passe oublié »", acteur=user)
        notifier_changement_mdp(self.request, user)
        return reponse


class DeconnexionView(auth_views.LogoutView):
    next_page = reverse_lazy("home")


# ======================================================================= citoyen
@login_required
def profil(request):
    p = request.user.profil
    derniere = p.analyses.filter(statut=AnalyseProfilIA.Statut.TERMINE).first()
    user = request.user
    ctx = {"profil": p, "analyse": derniere, "demande": user.demandes_nutritionniste.first()}
    if user.role == User.Role.NUTRITIONNISTE:      # profil professionnel
        partages = ProfilAlimentaire.objects.filter(utilisateur__role=User.Role.CITOYEN, utilisateur__is_active=True,
                                                    profil_public=True)
        ctx.update(
            demande_acceptee=user.demandes_nutritionniste.filter(statut=DemandeNutritionniste.Statut.ACCEPTEE).first(),
            invitation=Invitation.objects.filter(utilisateur=user).select_related("invite_par").first(),
            nb_profils_partages=partages.count(),
            nb_analyses=AnalyseProfilIA.objects.filter(profil__in=partages, statut=AnalyseProfilIA.Statut.TERMINE).count(),
        )
    elif user.role == User.Role.ADMIN:
        ctx.update(nb_comptes=User.objects.count(), nb_traitees=user.demandes_traitees.count(),
                   nb_invitations=user.invitations_envoyees.count())
    return render(request, "users/profil.html", ctx)


@login_required
def demande_nutritionniste(request):
    """Un citoyen déjà inscrit demande le statut de nutritionniste (validation par un administrateur)."""
    user = request.user
    if user.role != User.Role.CITOYEN:
        messages.info(request, "Votre compte a déjà un rôle professionnel.")
        return redirect("users:profil")
    if user.demandes_nutritionniste.filter(statut=DemandeNutritionniste.Statut.EN_ATTENTE).exists():
        messages.info(request, "Vous avez déjà une demande en cours d'examen.")
        return redirect("users:profil")
    form = DemandeNutritionnisteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        demande = form.save(commit=False)
        demande.utilisateur = user
        demande.save()
        journaliser(request, JournalAudit.Action.DEMANDE_ENVOYEE, cible=user.username, details=f"n° {demande.numero_ordre}")
        notifier_admins_demande(request, demande)
        messages.success(request, "Demande envoyée : vous recevrez un e-mail dès qu'un administrateur l'aura examinée.")
        return redirect("users:profil")
    return render(request, "users/form_page.html", {
        "form": form, "titre": "Devenir nutritionniste",
        "intro": "Votre compte restera citoyen jusqu'à la vérification de votre numéro d'ordre par un administrateur.",
    })


@login_required
def modifier_infos(request):
    ancien_avatar = request.user.avatar.name if request.user.avatar else ""
    form = InfosPersonnellesForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            utilisateur = form.save()
            if "avatar" in form.changed_data and ancien_avatar and ancien_avatar != utilisateur.avatar.name:
                utilisateur.avatar.storage.delete(ancien_avatar)
            if form.changed_data:
                journaliser(request, JournalAudit.Action.INFOS_MODIFIEES, cible=request.user.username,
                            details="champs : " + ", ".join(str(form.fields[c].label or c) for c in form.changed_data))
            messages.success(request, "Informations personnelles mises à jour.")
            return redirect("users:profil")
        messages.error(request, "Le formulaire contient des erreurs.")
    return render(request, "users/form_page.html", {
        "form": form, "titre": "Mes informations personnelles", "multipart": True,
    })


@citoyen_requis
def modifier_profil(request):
    form = ProfilAlimentaireForm(request.POST or None, instance=request.user.profil)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            if form.changed_data:
                journaliser(request, JournalAudit.Action.PROFIL_MODIFIE, cible=request.user.username,
                            details="champs : " + ", ".join(str(form.fields[c].label or c) for c in form.changed_data))
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
        journaliser(request, JournalAudit.Action.SUPPRESSION_PAR_UTILISATEUR, cible=user.username)
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
        journaliser(self.request, JournalAudit.Action.MDP_MODIFIE, cible=self.request.user.username)
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


@citoyen_requis
@require_POST
def analyse_lancer(request):
    p = request.user.profil
    # anti-spam : une analyse en cours de moins de 2 minutes est réutilisée
    en_cours = p.analyses.filter(
        statut__in=[AnalyseProfilIA.Statut.EN_ATTENTE, AnalyseProfilIA.Statut.EN_COURS],
        cree_le__gte=timezone.now() - timezone.timedelta(minutes=2),
    ).first()
    analyse = en_cours or lancer_analyse(p)
    if not en_cours:
        journaliser(request, JournalAudit.Action.ANALYSE_IA, cible=request.user.username)
    return JsonResponse(_analyse_json(analyse), status=202)


@citoyen_requis
@require_GET
def analyse_etat(request, pk):
    analyse = get_object_or_404(AnalyseProfilIA, pk=pk, profil__utilisateur=request.user)
    return JsonResponse(_analyse_json(analyse))


@citoyen_requis
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
        ctx["recommandations"] = self.object.utilisateur.recommandations_recues.select_related("auteur")[:20]
        if self.request.user.role == User.Role.NUTRITIONNISTE:
            ctx.setdefault("form_reco", RecommandationForm())
        return ctx

    def post(self, request, *args, **kwargs):
        """La nutritionniste écrit une recommandation au citoyen (profil partagé uniquement)."""
        self.object = self.get_object()
        if request.user.role != User.Role.NUTRITIONNISTE or not request.user.has_perm("users.add_recommandation"):
            raise PermissionDenied("Seul un nutritionniste peut écrire une recommandation.")
        form = RecommandationForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_reco=form))
        reco = form.save(commit=False)
        reco.auteur, reco.citoyen = request.user, self.object.utilisateur
        reco.save()
        journaliser(request, JournalAudit.Action.RECOMMANDATION, cible=reco.citoyen.username, details=reco.titre)
        if notifier_recommandation(request, reco):
            messages.success(request, f"Recommandation envoyée à {reco.citoyen} (notification + e-mail).")
        else:
            messages.warning(request, "Recommandation enregistrée, mais l'e-mail n'a pas pu être envoyé.")
        return redirect("users:nutri_profil_detail", pk=self.object.pk)


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


class CibleGerableMixin:
    """Modifier / désactiver / supprimer un compte administrateur : réservé au super-administrateur (403 sinon)."""

    def get_object(self, queryset=None):
        cible = super().get_object(queryset)
        if not self.request.user.peut_gerer(cible):
            raise PermissionDenied("Seul un super-administrateur peut modifier ou supprimer un compte administrateur.")
        return cible


class UtilisateurDetailView(AdminRequisMixin, DetailView):
    model = User
    template_name = "users/admin/detail.html"
    context_object_name = "cible"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        if self.request.user.has_perm("users.voir_journal"):
            ctx["activite"] = filtre_utilisateur(JournalAudit.objects.all(), self.object)[:10]
        return ctx


class UtilisateurCreateView(AdminRequisMixin, CreateView):
    model = User
    form_class = AdminUtilisateurCreationForm
    template_name = "users/form_page.html"
    extra_context = {"titre": "Créer un compte"}

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["editeur"] = self.request.user
        return kw

    def form_valid(self, form):
        reponse = super().form_valid(form)
        journaliser(self.request, JournalAudit.Action.COMPTE_CREE, cible=self.object.username, details=f"rôle {self.object.get_role_display()}")
        messages.success(self.request, "Compte créé.")
        return reponse

    def get_success_url(self):
        return reverse("users:admin_detail", args=[self.object.pk])


class UtilisateurUpdateView(AdminRequisMixin, CibleGerableMixin, UpdateView):
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
        champs = ", ".join(form.changed_data) or "aucun changement"
        reponse = super().form_valid(form)
        journaliser(self.request, JournalAudit.Action.COMPTE_MODIFIE, cible=self.object.username, details=f"champs : {champs}")
        messages.success(self.request, "Compte mis à jour.")
        return reponse

    def get_success_url(self):
        return reverse("users:admin_detail", args=[self.object.pk])


class UtilisateurDeleteView(AdminRequisMixin, CibleGerableMixin, DeleteView):
    model = User
    template_name = "users/admin/supprimer.html"
    context_object_name = "cible"
    success_url = reverse_lazy("users:admin_liste")

    def form_valid(self, form):
        if self.get_object().pk == self.request.user.pk:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte depuis l'administration.")
            return redirect("users:admin_detail", pk=self.request.user.pk)
        journaliser(self.request, JournalAudit.Action.COMPTE_SUPPRIME, cible=self.object.username, details=self.object.get_role_display())
        messages.success(self.request, "Compte supprimé.")
        return super().form_valid(form)


class UtilisateurBasculerActifView(AdminRequisMixin, CibleGerableMixin, DetailView):
    model = User
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        cible = self.get_object()
        if cible.pk == request.user.pk:
            messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
        else:
            cible.is_active = not cible.is_active
            cible.save(update_fields=["is_active"])
            journaliser(request, JournalAudit.Action.COMPTE_ACTIVE if cible.is_active else JournalAudit.Action.COMPTE_DESACTIVE, cible=cible.username)
            messages.success(request, f"Compte {'activé' if cible.is_active else 'désactivé'} : {cible}.")
        return redirect(request.POST.get("next") or "users:admin_liste")


# ============================================ administration : rôle nutritionniste
class DemandesView(AdminRequisMixin, TemplateView):
    template_name = "users/admin/demandes.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        qs = DemandeNutritionniste.objects.select_related("utilisateur", "traitee_par")
        ctx["en_attente"] = qs.filter(statut=DemandeNutritionniste.Statut.EN_ATTENTE).order_by("cree_le")
        ctx["traitees"] = qs.exclude(statut=DemandeNutritionniste.Statut.EN_ATTENTE).order_by("-traitee_le")[:20]
        ctx["form_refus"] = RefusDemandeForm()
        return ctx


class TraiterDemandeView(AdminRequisMixin, DetailView):
    """POST uniquement : accepter (rôle -> nutritionniste) ou refuser (avec motif), puis e-mail au demandeur."""
    model = DemandeNutritionniste
    http_method_names = ["post"]
    action = None

    def post(self, request, *args, **kwargs):
        demande = self.get_object()
        if demande.statut != DemandeNutritionniste.Statut.EN_ATTENTE:
            messages.error(request, "Cette demande a déjà été traitée.")
            return redirect("users:admin_demandes")
        if self.action == "accepter":
            demande.accepter(request.user)
            journaliser(request, JournalAudit.Action.DEMANDE_ACCEPTEE, cible=demande.utilisateur.username, details=f"n° {demande.numero_ordre}")
            messages.success(request, f"{demande.utilisateur} est maintenant nutritionniste.")
        else:
            form = RefusDemandeForm(request.POST)
            if not form.is_valid():
                messages.error(request, "Indiquez un motif de refus : il sera communiqué au demandeur.")
                return redirect("users:admin_demandes")
            demande.refuser(request.user, form.cleaned_data["motif"])
            journaliser(request, JournalAudit.Action.DEMANDE_REFUSEE, cible=demande.utilisateur.username, details=demande.motif_refus)
            messages.success(request, f"Demande de {demande.utilisateur} refusée.")
        if not notifier_demande_traitee(request, demande):
            messages.warning(request, "L'e-mail de notification n'a pas pu être envoyé.")
        return redirect("users:admin_demandes")


class InvitationsView(AdminRequisMixin, TemplateView):
    template_name = "users/admin/invitations.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.setdefault("form", InvitationForm())
        ctx["invitations"] = Invitation.objects.select_related("invite_par", "utilisateur")[:30]
        # lien affiché UNE fois (on ne garde que son empreinte en base) : utile si l'e-mail n'arrive pas
        ctx["dernier_lien"] = self.request.session.pop("dernier_lien_invitation", None)
        return ctx

    def post(self, request, *args, **kwargs):
        form = InvitationForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        Invitation.objects.filter(email=form.cleaned_data["email"], statut=Invitation.Statut.EN_ATTENTE) \
            .update(statut=Invitation.Statut.ANNULEE)          # une seule invitation valable par adresse
        inv = form.save(commit=False)
        inv.invite_par = request.user
        jeton = inv.nouveau_jeton()
        inv.save()
        journaliser(request, JournalAudit.Action.INVITATION_ENVOYEE, cible=inv.email)
        _envoyer_invitation(request, inv, jeton)
        return redirect("users:admin_invitations")


def _envoyer_invitation(request, inv, jeton):
    request.session["dernier_lien_invitation"] = {"email": inv.email, "lien": lien_invitation(request, jeton)}
    if envoyer_invitation(request, inv, jeton):
        messages.success(request, f"Invitation envoyée à {inv.email}.")
    else:
        messages.warning(request, f"L'e-mail n'a pas pu être envoyé à {inv.email} : copiez le lien ci-dessous et transmettez-le.")


class InvitationActionView(AdminRequisMixin, DetailView):
    model = Invitation
    http_method_names = ["post"]
    action = None

    def post(self, request, *args, **kwargs):
        inv = self.get_object()
        if inv.statut != Invitation.Statut.EN_ATTENTE:
            messages.error(request, "Cette invitation n'est plus en attente.")
        elif self.action == "annuler":
            inv.statut = Invitation.Statut.ANNULEE
            inv.save(update_fields=["statut"])
            journaliser(request, JournalAudit.Action.INVITATION_ANNULEE, cible=inv.email)
            messages.success(request, f"Invitation de {inv.email} annulée : le lien ne fonctionne plus.")
        else:  # renvoyer : nouveau lien (l'ancien devient invalide) et nouvelle échéance
            jeton = inv.nouveau_jeton()
            inv.save(update_fields=["jeton_hash", "expire_le"])
            journaliser(request, JournalAudit.Action.INVITATION_RENVOYEE, cible=inv.email)
            _envoyer_invitation(request, inv, jeton)
        return redirect("users:admin_invitations")


def invitation_accepter(request, jeton):
    inv = Invitation.depuis_jeton(jeton)
    if inv is None or not inv.est_utilisable:
        motif = ("Ce lien a expiré : demandez à l'administrateur de vous renvoyer une invitation." if inv and inv.est_expiree
                 else "Cette invitation a déjà été utilisée." if inv and inv.statut == Invitation.Statut.ACCEPTEE
                 else "Ce lien d'invitation n'est pas valide ou a été annulé.")
        return render(request, "users/invitation_invalide.html", {"motif": motif}, status=400)
    if request.user.is_authenticated:
        return render(request, "users/invitation_invalide.html", {
            "motif": f"Vous êtes connecté(e) en tant que {request.user.username}. Déconnectez-vous puis rouvrez le lien "
                     "pour créer le compte nutritionniste.", "deconnexion": True}, status=400)
    form = AccepterInvitationForm(request.POST or None, invitation=inv)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            inv = Invitation.objects.select_for_update().get(pk=inv.pk)
            if not inv.est_utilisable:          # double clic / deux onglets : usage unique garanti
                return redirect("users:invitation_accepter", jeton=jeton)
            user = form.save()
            inv.statut, inv.utilisateur, inv.acceptee_le = Invitation.Statut.ACCEPTEE, user, timezone.now()
            inv.save(update_fields=["statut", "utilisateur", "acceptee_le"])
        journaliser(request, JournalAudit.Action.INVITATION_ACCEPTEE, cible=inv.email, details=f"compte @{user.username}", acteur=user)
        login(request, user, backend="users.backends.EmailOuUsernameBackend")
        messages.success(request, f"Bienvenue {user.first_name} ! Votre compte nutritionniste est prêt.")
        return redirect("users:nutri_profils")
    return render(request, "users/invitation_accepter.html", {"form": form, "inv": inv})


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


# ================================================= recommandations reçues (citoyen)
@citoyen_requis
def mes_recommandations(request):
    recos = list(request.user.recommandations_recues.select_related("auteur"))
    non_lues = [r.pk for r in recos if not r.lue_le]
    if non_lues:                                     # affichées -> marquées comme lues
        Recommandation.objects.filter(pk__in=non_lues).update(lue_le=timezone.now())
    return render(request, "users/recommandations.html", {"recommandations": recos, "nouvelles": set(non_lues)})


@citoyen_requis
@require_POST
def avis_recommandation(request, pk):
    reco = get_object_or_404(Recommandation, pk=pk, citoyen=request.user)
    avis = request.POST.get("avis")
    if avis in Recommandation.Avis.values:
        reco.avis = avis
        reco.save(update_fields=["avis"])
        messages.success(request, "Merci pour votre avis : il aide votre nutritionniste à mieux vous conseiller.")
    return redirect("users:mes_recommandations")


# ======================================================= sécurité & données personnelles
@login_required
def securite(request):
    return render(request, "users/securite.html", {
        "connexions": request.user.connexions.all()[:15],
        "echecs_recents": request.user.connexions.filter(succes=False, cree_le__gte=timezone.now() - timezone.timedelta(days=7)).count(),
    })


@login_required
@require_POST
def deconnexion_globale(request):
    n = deconnecter_autres_appareils(request)
    journaliser(request, JournalAudit.Action.DECONNEXION_GLOBALE, cible=request.user.username, details=f"{n} session(s) fermée(s)")
    messages.success(request, f"{n} autre(s) session(s) fermée(s). Vous restez connecté(e) sur cet appareil." if n
                     else "Aucune autre session ouverte : vous n'êtes connecté(e) que sur cet appareil.")
    return redirect("users:securite")


def _date(d):
    return d.isoformat() if d else None


@login_required
def export_donnees(request):
    """RGPD (art. 15 et 20) : toutes les données personnelles. PDF lisible par défaut, JSON avec ?format=json."""
    u = request.user
    p = u.profil
    donnees = {
        "export": {"genere_le": _date(timezone.now()), "application": "EcoAssiette",
                   "format": "JSON — droit d'accès et à la portabilité (RGPD, articles 15 et 20)"},
        "compte": {"nom_utilisateur": u.username, "prenom": u.first_name, "nom": u.last_name, "email": u.email,
                   "email_confirme": u.email_verifie, "telephone": u.telephone, "role": u.get_role_display(),
                   "inscrit_le": _date(u.date_joined), "derniere_connexion": _date(u.last_login)},
        "profil_alimentaire": {"regime": p.get_regime_display(), "aliments_aimes": p.liste_aimes,
                               "aliments_evites": p.liste_evites, "taille_foyer": p.taille_foyer,
                               "niveau_activite": p.get_niveau_activite_display(),
                               "temps_cuisine": p.get_temps_cuisine_display(), "ville": p.ville,
                               "objectif_co2_hebdo_kg": float(p.objectif_co2_hebdo) if p.objectif_co2_hebdo else None,
                               "empreinte_estimee_hebdo_kg": float(p.emission_estimee_hebdo),
                               "partage_avec_nutritionnistes": p.profil_public},
        "analyses_ia": [{"date": _date(a.cree_le), "statut": a.get_statut_display(), "source": a.get_source_display(),
                         "resultat": a.resultat} for a in p.analyses.all()],
        "repas": [{"date": _date(r.date), "type": r.get_type_repas_display(), "note": r.note, "co2_kg": r.co2_kg,
                   "aliments": [{"aliment": e.aliment, "categorie": e.get_categorie_display(), "quantite_g": e.quantite_g,
                                 "co2_kg": e.co2_kg} for e in r.elements.all()]}
                  for r in u.repas.prefetch_related("elements").order_by("-date")],
        "remplacements": [{"date": _date(r.cree_le), "avant": r.ancien_aliment, "apres": r.nouvel_aliment,
                           "co2_evite_kg": r.gain_kg} for r in u.remplacements.all()],
        "recommandations_recues": [{"date": _date(r.cree_le), "de": str(r.auteur) if r.auteur else None,
                                    "theme": r.get_theme_display(), "titre": r.titre, "contenu": r.contenu,
                                    "avis": r.get_avis_display() if r.avis else None}
                                   for r in u.recommandations_recues.select_related("auteur")],
        "demandes_nutritionniste": [{"date": _date(d.cree_le), "numero_ordre": d.numero_ordre,
                                     "etablissement": d.etablissement, "statut": d.get_statut_display()}
                                    for d in u.demandes_nutritionniste.all()],
        "historique_connexions": [{"date": _date(c.cree_le), "reussie": c.succes, "ip_masquee": c.ip,
                                   "navigateur": c.navigateur} for c in u.connexions.all()[:100]],
    }
    nom = f"ecoassiette-mes-donnees-{u.username}-{timezone.localdate():%Y%m%d}"
    if request.GET.get("format") != "json":       # par défaut : document PDF lisible
        journaliser(request, JournalAudit.Action.EXPORT_DONNEES, cible=u.username, details="format PDF")
        reponse = HttpResponse(generer_pdf(u), content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="{nom}.pdf"'
        return reponse
    journaliser(request, JournalAudit.Action.EXPORT_DONNEES, cible=u.username, details="format JSON")
    reponse = JsonResponse(donnees, json_dumps_params={"ensure_ascii": False, "indent": 2})
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.json"'
    return reponse


# ============================================================== journal d'audit (admin)
def filtre_utilisateur(qs, u):
    """Entrées où l'utilisateur est l'auteur OU la cible (y compris les connexions échouées par e-mail)."""
    cibles = [u.username, u.email.lower()] if u.email else [u.username]
    return qs.filter(Q(acteur=u) | Q(cible__in=cibles) | Q(cible__iexact=u.username))


class JournalView(PermissionOu403Mixin, ListView):
    """Journal d'audit de TOUS les comptes : connexions, activité des citoyens et nutritionnistes, administration."""
    permission_required = "users.voir_journal"
    template_name = "users/admin/journal.html"
    context_object_name = "entrees"
    paginate_by = 25

    def get_queryset(self):
        qs = JournalAudit.objects.select_related("acteur")
        g = self.request.GET
        self.categorie = g.get("type", "")
        if self.categorie in JournalAudit.CATEGORIES:
            qs = qs.filter(action__in=JournalAudit.CATEGORIES[self.categorie][1])
        action = g.get("action")
        if action in JournalAudit.Action.values:
            qs = qs.filter(action=action)
        self.cible_utilisateur = None
        if g.get("u"):
            self.cible_utilisateur = User.objects.filter(username=g["u"]).first()
            qs = filtre_utilisateur(qs, self.cible_utilisateur) if self.cible_utilisateur else qs.none()
        role = g.get("role")
        if role in User.Role.values:
            qs = qs.filter(acteur__role=role)
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(acteur_nom__icontains=q) | Q(cible__icontains=q) | Q(details__icontains=q))
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        params = self.request.GET.copy()
        params.pop("page", None)
        depuis = timezone.now() - timezone.timedelta(hours=24)
        recent = JournalAudit.objects.filter(cree_le__gte=depuis)
        ctx.update(
            actions=JournalAudit.Action.choices, action_active=self.request.GET.get("action", ""),
            categories=[(k, v[0]) for k, v in JournalAudit.CATEGORIES.items()], categorie_active=self.categorie,
            roles=User.Role.choices, role_active=self.request.GET.get("role", ""),
            cible_utilisateur=self.cible_utilisateur, u=self.request.GET.get("u", ""),
            q=self.request.GET.get("q", ""), params=params.urlencode(),
            kpi_actions=recent.count(),
            kpi_actifs=recent.exclude(acteur=None).values("acteur").distinct().count(),
            kpi_connexions=recent.filter(action=JournalAudit.Action.CONNEXION).count(),
            kpi_echecs=recent.filter(action=JournalAudit.Action.CONNEXION_ECHOUEE).count(),
        )
        return ctx
