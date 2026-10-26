from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from impact.services import solde_points

from .forms import AnnonceSurplusForm, ProfilBeneficiaireForm, ReservationSurplusForm
from .models import AnalyseSurplusIA, AnnonceSurplus, CollecteSurplus, ProfilBeneficiaire, ReservationSurplus
from .services import annonces_recommandees, crediter_donateur
from .intelligence import doublons_probables, recettes_pour_annonce, repondre_assistant, risque_non_collecte, statistiques_intelligentes
from .tasks import lancer


class AnnonceListView(LoginRequiredMixin, ListView):
    model = AnnonceSurplus
    template_name = "food_rescue/liste.html"
    context_object_name = "annonces"
    paginate_by = 12

    def get_queryset(self):
        AnnonceSurplus.objects.filter(
            statut=AnnonceSurplus.Statut.DISPONIBLE, disponible_jusquau__lte=timezone.now()
        ).update(statut=AnnonceSurplus.Statut.EXPIREE)
        qs = AnnonceSurplus.objects.filter(
            statut=AnnonceSurplus.Statut.DISPONIBLE, disponible_jusquau__gt=timezone.now()
        ).select_related("donateur")
        recherche = self.request.GET.get("q", "").strip()
        if recherche:
            qs = qs.filter(Q(titre__icontains=recherche) | Q(description__icontains=recherche) | Q(ville__icontains=recherche))
        categorie = self.request.GET.get("categorie", "")
        if categorie in AnnonceSurplus.Categorie.values:
            qs = qs.filter(categorie=categorie)
        return qs

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        eligibilite = ProfilBeneficiaire.objects.filter(utilisateur=self.request.user).first()
        contexte.update({
            "categories": AnnonceSurplus.Categorie.choices,
            "categorie_active": self.request.GET.get("categorie", ""),
            "recherche": self.request.GET.get("q", ""),
            "recommandations": annonces_recommandees(self.request.user, limite=3),
            "eligibilite": eligibilite,
        })
        return contexte


class MesAnnoncesView(LoginRequiredMixin, ListView):
    template_name = "food_rescue/mes_annonces.html"
    context_object_name = "annonces"

    def get_queryset(self):
        return AnnonceSurplus.objects.filter(donateur=self.request.user).prefetch_related("reservations__beneficiaire")


class ProprietaireMixin(LoginRequiredMixin):
    def get_queryset(self):
        return AnnonceSurplus.objects.filter(donateur=self.request.user)


class AnnonceCreateView(LoginRequiredMixin, CreateView):
    model = AnnonceSurplus
    form_class = AnnonceSurplusForm
    template_name = "food_rescue/form.html"

    def form_valid(self, form):
        form.instance.donateur = self.request.user
        form.instance.statut = AnnonceSurplus.Statut.DISPONIBLE
        reponse = super().form_valid(form)
        lancer(self.object)
        messages.success(self.request, "Surplus publié. L'analyse IA est lancée en arrière-plan.")
        return reponse


class AnnonceUpdateView(ProprietaireMixin, UpdateView):
    model = AnnonceSurplus
    form_class = AnnonceSurplusForm
    template_name = "food_rescue/form.html"

    def dispatch(self, request, *args, **kwargs):
        objet = self.get_object()
        if objet.statut not in (AnnonceSurplus.Statut.BROUILLON, AnnonceSurplus.Statut.DISPONIBLE):
            raise PermissionDenied("Une annonce réservée ou collectée ne peut plus être modifiée.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        reponse = super().form_valid(form)
        lancer(self.object)
        messages.success(self.request, "Annonce modifiée et réanalysée.")
        return reponse


class AnnonceDeleteView(ProprietaireMixin, DeleteView):
    model = AnnonceSurplus
    template_name = "food_rescue/supprimer.html"
    success_url = reverse_lazy("food_rescue:mes_annonces")

    def form_valid(self, form):
        if self.object.statut not in (AnnonceSurplus.Statut.BROUILLON, AnnonceSurplus.Statut.DISPONIBLE, AnnonceSurplus.Statut.ANNULEE):
            raise PermissionDenied("Cette annonce possède une réservation active.")
        messages.success(self.request, "Annonce supprimée.")
        return super().form_valid(form)


class AnnonceDetailView(LoginRequiredMixin, DetailView):
    model = AnnonceSurplus
    template_name = "food_rescue/detail.html"
    context_object_name = "annonce"

    def get_queryset(self):
        return AnnonceSurplus.objects.select_related("donateur").prefetch_related("reservations__beneficiaire")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        deja = self.object.reservations.filter(beneficiaire=self.request.user).first()
        eligibilite = ProfilBeneficiaire.objects.filter(utilisateur=self.request.user).first()
        peut_reserver = bool(eligibilite and eligibilite.est_valide)
        contexte["ma_reservation"] = deja
        contexte["eligibilite"] = eligibilite
        contexte["peut_reserver"] = peut_reserver
        contexte["form_reservation"] = (
            None if deja or self.object.donateur_id == self.request.user.id or not peut_reserver
            else ReservationSurplusForm(annonce=self.object)
        )
        reservations = list(self.object.reservations.all()) if self.object.donateur_id == self.request.user.id else []
        for reservation in reservations:
            reservation.risque_ia = risque_non_collecte(reservation.beneficiaire)
        contexte["reservations"] = reservations
        contexte["adresse_visible"] = (
            self.object.donateur_id == self.request.user.id
            or self.object.reservations.filter(beneficiaire=self.request.user, statut__in=["ACCEPTEE", "COLLECTEE"]).exists()
        )
        contexte["doublons"] = doublons_probables(self.object) if self.object.donateur_id == self.request.user.id else []
        return contexte


@login_required
@require_POST
def reserver(request, pk):
    if not ProfilBeneficiaire.objects.filter(
        utilisateur=request.user, statut=ProfilBeneficiaire.Statut.VALIDEE
    ).exists():
        messages.error(request, "La réservation est réservée aux étudiants et associations dont le profil est validé.")
        return redirect("food_rescue:eligibilite")
    with transaction.atomic():
        annonce = get_object_or_404(AnnonceSurplus.objects.select_for_update(), pk=pk)
        if annonce.donateur_id == request.user.id:
            raise PermissionDenied("Vous ne pouvez pas réserver votre propre surplus.")
        if not annonce.est_reservable:
            messages.error(request, "Ce surplus n'est plus disponible.")
            return redirect("food_rescue:detail", pk=pk)
        form = ReservationSurplusForm(request.POST, annonce=annonce)
        if form.is_valid():
            reservation = form.save(commit=False)
            reservation.annonce = annonce
            reservation.beneficiaire = request.user
            reservation.full_clean()
            try:
                reservation.save()
            except IntegrityError:
                messages.info(request, "Vous avez déjà demandé ce surplus.")
                return redirect("food_rescue:detail", pk=pk)
            messages.success(request, "Demande envoyée au donateur.")
            return redirect("food_rescue:detail", pk=pk)
    return render(request, "food_rescue/detail.html", {
        "annonce": annonce, "form_reservation": form, "ma_reservation": None,
        "reservations": [], "adresse_visible": False,
    }, status=400)


@login_required
@require_POST
def traiter_reservation(request, pk, action):
    with transaction.atomic():
        reservation = get_object_or_404(
            ReservationSurplus.objects.select_for_update().select_related("annonce"), pk=pk,
            annonce__donateur=request.user, statut=ReservationSurplus.Statut.EN_ATTENTE,
        )
        if action == "accepter":
            if not ProfilBeneficiaire.objects.filter(
                utilisateur=reservation.beneficiaire, statut=ProfilBeneficiaire.Statut.VALIDEE
            ).exists():
                messages.error(request, "Ce bénéficiaire n'est plus éligible. La demande ne peut pas être acceptée.")
                return redirect("food_rescue:detail", pk=reservation.annonce_id)
            reservation.statut = ReservationSurplus.Statut.ACCEPTEE
            reservation.annonce.statut = AnnonceSurplus.Statut.RESERVEE
            reservation.annonce.save(update_fields=["statut"])
            ReservationSurplus.objects.filter(annonce=reservation.annonce, statut="EN_ATTENTE").exclude(pk=pk).update(
                statut=ReservationSurplus.Statut.REFUSEE, traitee_le=timezone.now()
            )
            CollecteSurplus.objects.get_or_create(reservation=reservation)
            message = "Réservation acceptée. Le code de collecte est maintenant disponible."
        elif action == "refuser":
            reservation.statut = ReservationSurplus.Statut.REFUSEE
            message = "Réservation refusée."
        else:
            raise PermissionDenied("Action inconnue.")
        reservation.traitee_le = timezone.now()
        reservation.save(update_fields=["statut", "traitee_le"])
    messages.success(request, message)
    return redirect("food_rescue:detail", pk=reservation.annonce_id)


@login_required
@require_POST
def confirmer_collecte(request, pk):
    with transaction.atomic():
        reservation = get_object_or_404(
            ReservationSurplus.objects.select_for_update().select_related("annonce"),
            pk=pk, statut=ReservationSurplus.Statut.ACCEPTEE,
        )
        collecte, _ = CollecteSurplus.objects.get_or_create(reservation=reservation)
        if request.user.id == reservation.annonce.donateur_id:
            collecte.confirmee_par_donateur = True
        elif request.user.id == reservation.beneficiaire_id:
            if request.POST.get("code", "").strip().upper() != reservation.code_collecte:
                messages.error(request, "Code de collecte incorrect.")
                return redirect("food_rescue:detail", pk=reservation.annonce_id)
            collecte.confirmee_par_beneficiaire = True
        else:
            raise PermissionDenied
        collecte.save()
        if collecte.est_confirmee:
            collecte.confirmee_le = timezone.now()
            collecte.save(update_fields=["confirmee_le"])
            reservation.statut = ReservationSurplus.Statut.COLLECTEE
            reservation.annonce.statut = AnnonceSurplus.Statut.COLLECTEE
            reservation.save(update_fields=["statut"])
            reservation.annonce.save(update_fields=["statut"])
            _, points = crediter_donateur(collecte)
            messages.success(
                request,
                f"Collecte confirmée par les deux parties. Le donateur reçoit {points} points solidaires !",
            )
        else:
            messages.info(request, "Confirmation enregistrée. En attente de l'autre partie.")
    return redirect("food_rescue:detail", pk=reservation.annonce_id)


@login_required
def analyse_etat(request, pk):
    analyse = get_object_or_404(AnalyseSurplusIA, annonce_id=pk, annonce__donateur=request.user)
    return JsonResponse({
        "terminee": analyse.est_terminee,
        "statut": analyse.statut,
        "source": analyse.source,
        "resultat": analyse.resultat if analyse.statut == analyse.Statut.TERMINEE else {},
        "erreur": analyse.erreur if analyse.statut == analyse.Statut.ECHEC else "",
    })


@login_required
def tableau_bord(request):
    dons = AnnonceSurplus.objects.filter(donateur=request.user)
    recus = ReservationSurplus.objects.filter(beneficiaire=request.user, statut=ReservationSurplus.Statut.COLLECTEE)
    impact = dons.filter(statut=AnnonceSurplus.Statut.COLLECTEE).aggregate(total=Sum("co2_evite_estime"))["total"] or 0
    return render(request, "food_rescue/tableau_bord.html", {
        "dons": dons.count(), "collectes": dons.filter(statut="COLLECTEE").count(),
        "recus": recus.count(), "impact": impact,
        "points": solde_points(request.user),
        "eligibilite": ProfilBeneficiaire.objects.filter(utilisateur=request.user).first(),
        "mes_reservations": ReservationSurplus.objects.filter(beneficiaire=request.user).select_related("annonce")[:10],
    })


@login_required
def eligibilite(request):
    profil = ProfilBeneficiaire.objects.filter(utilisateur=request.user).first()
    if request.method == "POST":
        if profil and profil.est_valide:
            messages.info(request, "Votre éligibilité est déjà validée.")
            return redirect("food_rescue:eligibilite")
        form = ProfilBeneficiaireForm(request.POST, instance=profil)
        if form.is_valid():
            profil = form.save(commit=False)
            profil.utilisateur = request.user
            profil.save()
            messages.success(request, "Demande envoyée. Un administrateur doit maintenant la valider.")
            return redirect("food_rescue:eligibilite")
    else:
        form = ProfilBeneficiaireForm(instance=profil)
    return render(request, "food_rescue/eligibilite.html", {"form": form, "eligibilite": profil})


@login_required
def assistant(request):
    question = request.POST.get("question", "") if request.method == "POST" else ""
    reponse = repondre_assistant(request.user, question) if question else ""
    return render(request, "food_rescue/assistant.html", {"question": question, "reponse": reponse})


@login_required
def recettes(request, pk):
    annonce = get_object_or_404(AnnonceSurplus, pk=pk)
    autorise = annonce.donateur_id == request.user.id or annonce.reservations.filter(
        beneficiaire=request.user, statut__in=["ACCEPTEE", "COLLECTEE"]
    ).exists()
    if not autorise:
        raise PermissionDenied("Les recettes sont réservées aux participants de la collecte.")
    propositions, source = recettes_pour_annonce(annonce, request.user)
    return render(request, "food_rescue/recettes.html", {
        "annonce": annonce, "recettes": propositions, "source": source,
    })


@login_required
def intelligence_dashboard(request):
    if not request.user.est_admin:
        raise PermissionDenied
    return render(request, "food_rescue/intelligence_dashboard.html", {
        "stats": statistiques_intelligentes(),
    })


@login_required
def administration(request):
    if not request.user.has_perm("users.gerer_utilisateurs"):
        raise PermissionDenied
    profils = ProfilBeneficiaire.objects.select_related("utilisateur", "verifie_par")
    return render(request, "food_rescue/administration.html", {
        "en_attente": profils.filter(statut=ProfilBeneficiaire.Statut.EN_ATTENTE),
        "traites": profils.exclude(statut=ProfilBeneficiaire.Statut.EN_ATTENTE)[:30],
        "annonces": AnnonceSurplus.objects.select_related("donateur")[:20],
    })


@login_required
@require_POST
def traiter_eligibilite(request, pk, action):
    if not request.user.has_perm("users.gerer_utilisateurs"):
        raise PermissionDenied
    if action not in {"valider", "refuser"}:
        raise PermissionDenied("Action inconnue.")
    with transaction.atomic():
        profil = get_object_or_404(ProfilBeneficiaire.objects.select_for_update(), pk=pk)
        if action == "valider":
            profil.statut = ProfilBeneficiaire.Statut.VALIDEE
            profil.motif_refus = ""
            message = f"Éligibilité validée pour {profil.utilisateur}."
        else:
            motif = request.POST.get("motif", "").strip()
            if not motif:
                messages.error(request, "Indiquez un motif de refus.")
                return redirect("food_rescue:administration")
            profil.statut = ProfilBeneficiaire.Statut.REFUSEE
            profil.motif_refus = motif[:300]
            message = f"Éligibilité refusée pour {profil.utilisateur}."
        profil.verifie_par = request.user
        profil.verifie_le = timezone.now()
        profil.save(update_fields=["statut", "motif_refus", "verifie_par", "verifie_le", "modifie_le"])
    messages.success(request, message)
    return redirect("food_rescue:administration")

