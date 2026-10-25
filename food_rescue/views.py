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

from .forms import AnnonceSurplusForm, ReservationSurplusForm
from .models import AnalyseSurplusIA, AnnonceSurplus, CollecteSurplus, ReservationSurplus
from .services import annonces_recommandees
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
        contexte.update({
            "categories": AnnonceSurplus.Categorie.choices,
            "categorie_active": self.request.GET.get("categorie", ""),
            "recherche": self.request.GET.get("q", ""),
            "recommandations": annonces_recommandees(self.request.user, limite=3),
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
        contexte["ma_reservation"] = deja
        contexte["form_reservation"] = None if deja or self.object.donateur_id == self.request.user.id else ReservationSurplusForm(annonce=self.object)
        contexte["reservations"] = self.object.reservations.all() if self.object.donateur_id == self.request.user.id else []
        contexte["adresse_visible"] = (
            self.object.donateur_id == self.request.user.id
            or self.object.reservations.filter(beneficiaire=self.request.user, statut__in=["ACCEPTEE", "COLLECTEE"]).exists()
        )
        return contexte


@login_required
@require_POST
def reserver(request, pk):
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
    reservation = get_object_or_404(
        ReservationSurplus.objects.select_related("annonce"), pk=pk, statut=ReservationSurplus.Statut.ACCEPTEE
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
    if collecte.est_confirmee:
        collecte.confirmee_le = timezone.now()
        reservation.statut = ReservationSurplus.Statut.COLLECTEE
        reservation.annonce.statut = AnnonceSurplus.Statut.COLLECTEE
        reservation.save(update_fields=["statut"])
        reservation.annonce.save(update_fields=["statut"])
        messages.success(request, "Collecte confirmée par les deux parties. Merci d'avoir évité ce gaspillage !")
    else:
        messages.info(request, "Confirmation enregistrée. En attente de l'autre partie.")
    collecte.save()
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
        "mes_reservations": ReservationSurplus.objects.filter(beneficiaire=request.user).select_related("annonce")[:10],
    })

