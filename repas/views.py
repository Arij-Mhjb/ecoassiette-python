import json
import logging

from django.conf import settings

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from users.ai import ErreurIA

from . import ia
from .bilan import bilan_semaine  # noqa: F401  (réexporté : utilisé par les tests)
from .categories import donnees_js, remplacement_pour
from .forms import ElementRepasFormSet, RepasForm
from .models import FACTEURS_CO2, ElementRepas, Remplacement, Repas

logger = logging.getLogger(__name__)


class MesRepasMixin(LoginRequiredMixin):
    """Chaque utilisateur ne voit QUE ses propres repas."""

    def get_queryset(self):
        return Repas.objects.filter(utilisateur=self.request.user).prefetch_related("elements")


# ------------------------------------------------------------------ READ
class RepasListView(MesRepasMixin, ListView):
    template_name = "repas/liste.html"
    context_object_name = "repas_list"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            nb_aliments=Count("elements"),
            total_g=Sum("elements__quantite_g"),
        ).order_by("-date", "-cree_le")
        type_choisi = self.request.GET.get("type")
        if type_choisi in Repas.TypeRepas.values:
            qs = qs.filter(type_repas=type_choisi)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["types"] = Repas.TypeRepas.choices
        ctx["type_actif"] = self.request.GET.get("type", "")
        ctx["bilan"] = bilan_semaine(self.request.user)
        return ctx


class RepasDetailView(MesRepasMixin, DetailView):
    template_name = "repas/detail.html"
    context_object_name = "repas"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lignes"] = [(e, suggestion_pour(e)) for e in self.object.elements.all()]
        ctx["a_suggestions"] = any(s for _, s in ctx["lignes"])
        return ctx


def suggestion_pour(element):
    """Simulateur « Et si… » : alternative végétale et CO2 évité pour un élément du repas."""
    alt = remplacement_pour(element.aliment, element.categorie)
    if not alt:
        return None
    nom, categorie, idee = alt
    apres = round(element.quantite_g / 1000 * FACTEURS_CO2[categorie], 2)
    gain = round(element.co2_kg - apres, 2)
    if gain < 0.2:
        return None
    return {"nom": nom, "categorie": categorie, "idee": idee, "apres": apres, "gain": gain,
            # si ce remplacement est fait une fois par semaine
            "gain_mois": round(gain * 52 / 12, 1), "gain_an": round(gain * 52)}


@login_required
@require_POST
def remplacer(request, pk, element_pk):
    element = get_object_or_404(ElementRepas, pk=element_pk, repas__pk=pk, repas__utilisateur=request.user)
    s = suggestion_pour(element)
    if not s:
        messages.info(request, "Cet aliment est déjà peu émetteur 🌿")
        return redirect("repas:detail", pk=pk)
    ancien = element.aliment
    with transaction.atomic():
        element.aliment, element.categorie = s["nom"], s["categorie"]
        element.save(update_fields=["aliment", "categorie"])
        Remplacement.objects.create(utilisateur=request.user, repas=element.repas, ancien_aliment=ancien,
                                    nouvel_aliment=s["nom"], gain_kg=s["gain"])
    nb = Remplacement.objects.filter(utilisateur=request.user).count()
    extra = " Badge débloqué : 🌱 Premier pas !" if nb == 1 else (" Badge débloqué : 🥗 Éco-cuisinier !" if nb == 5 else "")
    messages.success(request, f"« {ancien} » → « {s['nom']} » : −{s['gain']} kg CO₂e 🌍{extra}")
    return redirect("repas:detail", pk=pk)


# ------------------------------------------------------- IA : photo et texte / voix
TYPES_IMAGES = {"image/jpeg", "image/png", "image/webp"}
TAILLE_MAX_PHOTO = 8 * 1024 * 1024


@login_required
@require_POST
def ia_photo(request):
    photo = request.FILES.get("photo")
    if not photo:
        return JsonResponse({"erreur": "Aucune photo reçue."}, status=400)
    if photo.content_type not in TYPES_IMAGES:
        return JsonResponse({"erreur": "Format non supporté : utilisez une photo JPEG, PNG ou WebP."}, status=400)
    if photo.size > TAILLE_MAX_PHOTO:
        return JsonResponse({"erreur": "Photo trop lourde (8 Mo maximum)."}, status=400)
    try:
        return JsonResponse(ia.depuis_photo(photo.read(), photo.content_type))
    except ErreurIA as e:
        logger.warning("Analyse photo impossible : %s", e)
        message = ("L'analyse de la photo est indisponible pour le moment. "
                   "Décrivez votre repas avec le texte ou la voix, ou saisissez-le à la main.")
        if settings.DEBUG:  # en développement seulement : la cause technique aide à corriger
            message += f" [Détail : {e}]"
        return JsonResponse({"erreur": message}, status=503)


@login_required
@require_POST
def ia_texte(request):
    try:
        texte = str(json.loads(request.body or b"{}").get("texte", "")).strip()
    except (ValueError, AttributeError):
        texte = ""
    if not texte:
        return JsonResponse({"erreur": "Décrivez votre repas (ex. « couscous à l'agneau et salade »)."}, status=400)
    if len(texte) > 500:
        return JsonResponse({"erreur": "Description trop longue (500 caractères maximum)."}, status=400)
    try:
        return JsonResponse(ia.depuis_texte(texte))
    except ErreurIA:
        return JsonResponse({"erreur": "Aucun aliment reconnu. Essayez par exemple : « kosksi b l3allouch w slata »."},
                            status=422)


# ---------------------------------------------------- CREATE + UPDATE
class RepasFormMixin:
    """Gère le formulaire Repas + le formset des aliments ensemble."""
    form_class = RepasForm
    template_name = "repas/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "formset" not in kwargs:
            ctx["formset"] = ElementRepasFormSet(instance=self.object)
        ctx["aide_categories"] = donnees_js()
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if self.est_modification else None
        form = self.get_form()
        formset = ElementRepasFormSet(request.POST, instance=form.instance)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                if not self.est_modification:
                    form.instance.utilisateur = request.user
                self.object = form.save()
                formset.instance = self.object
                formset.save()
            messages.success(request, self.message_succes)
            return redirect("repas:detail", pk=self.object.pk)
        messages.error(request, "Le formulaire contient des erreurs.")
        return self.render_to_response(self.get_context_data(form=form, formset=formset))


class RepasCreateView(LoginRequiredMixin, RepasFormMixin, CreateView):
    est_modification = False
    message_succes = "Repas ajouté."
    extra_context = {"titre": "Ajouter un repas"}


class RepasUpdateView(MesRepasMixin, RepasFormMixin, UpdateView):
    est_modification = True
    message_succes = "Repas modifié."
    extra_context = {"titre": "Modifier le repas"}


# ---------------------------------------------------------------- DELETE
class RepasDeleteView(MesRepasMixin, DeleteView):
    template_name = "repas/supprimer.html"
    context_object_name = "repas"
    success_url = reverse_lazy("repas:liste")

    def form_valid(self, form):
        messages.success(self.request, "Repas supprimé.")
        return super().form_valid(form)