from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import ElementRepasFormSet, RepasForm
from .models import Repas


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
        return ctx


class RepasDetailView(MesRepasMixin, DetailView):
    template_name = "repas/detail.html"
    context_object_name = "repas"


# ---------------------------------------------------- CREATE + UPDATE
class RepasFormMixin:
    """Gère le formulaire Repas + le formset des aliments ensemble."""
    form_class = RepasForm
    template_name = "repas/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "formset" not in kwargs:
            ctx["formset"] = ElementRepasFormSet(instance=self.object)
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