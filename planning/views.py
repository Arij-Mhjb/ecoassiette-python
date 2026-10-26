from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from users.permissions import citoyen_requis
from repas.categories import deviner_categorie
from repas.models import ElementRepas, Repas

from .forms import PlanMenuForm, lundi_de
from .models import MenuPlanifie, PlanMenu
from .services import generer_plan, liste_courses, remplacer_menu


@citoyen_requis
def tableau(request):
    semaine = lundi_de(timezone.localdate())
    if request.GET.get("semaine"):
        try:
            semaine = lundi_de(timezone.datetime.strptime(request.GET["semaine"], "%Y-%m-%d").date())
        except ValueError:
            pass
    plan = PlanMenu.objects.filter(utilisateur=request.user, semaine_du=semaine).prefetch_related("menus").first()
    form = PlanMenuForm(initial={
        "semaine_du": semaine,
        "objectif_co2": plan.objectif_co2 if plan else 20,
    })
    total = plan.total_co2 if plan else 0
    progression = min(100, round(total / float(plan.objectif_co2) * 100)) if plan else 0
    return render(request, "planning/tableau.html", {
        "plan": plan, "form": form, "total_co2": total, "progression": progression,
        "fin_semaine": semaine + timedelta(days=6),
    })


@citoyen_requis
@require_POST
def generer(request):
    form = PlanMenuForm(request.POST)
    if not form.is_valid():
        return render(request, "planning/tableau.html", {"form": form, "plan": None}, status=400)
    plan, cree = PlanMenu.objects.get_or_create(
        utilisateur=request.user,
        semaine_du=form.cleaned_data["semaine_du"],
        defaults={
            "objectif_co2": form.cleaned_data["objectif_co2"],
            "source": "LOCAL", "numero_generation": 1,
        },
    )
    if not cree:
        plan.objectif_co2 = form.cleaned_data["objectif_co2"]
        plan.numero_generation += 1
        plan.save(update_fields=["objectif_co2", "numero_generation", "modifie_le"])
    generer_plan(plan)
    messages.success(request, "Planning écologique généré avec sa liste de courses.")
    return redirect(f"/planning/?semaine={plan.semaine_du:%Y-%m-%d}")


@citoyen_requis
@require_POST
def remplacer(request, menu_id):
    menu = get_object_or_404(
        MenuPlanifie.objects.select_related("plan"), pk=menu_id, plan__utilisateur=request.user
    )
    if menu.repas_realise_id:
        messages.info(request, "Ce menu a déjà été ajouté à vos repas et ne peut plus être remplacé.")
        return redirect(f"/planning/?semaine={menu.plan.semaine_du:%Y-%m-%d}")
    remplacer_menu(menu)
    messages.success(request, "Le repas a été remplacé par une option végétale plus sobre.")
    return redirect(f"/planning/?semaine={menu.plan.semaine_du:%Y-%m-%d}")


@citoyen_requis
@require_POST
def ajouter_comme_repas(request, menu_id):
    """Transforme une proposition du planning en repas réel, une seule fois."""
    with transaction.atomic():
        menu = get_object_or_404(
            MenuPlanifie.objects.select_for_update().select_related("plan", "repas_realise"),
            pk=menu_id, plan__utilisateur=request.user,
        )
        if menu.repas_realise_id:
            repas = menu.repas_realise
            messages.info(request, "Ce menu est déjà présent dans vos repas.")
        else:
            repas = Repas.objects.create(
                utilisateur=request.user,
                type_repas=menu.type_repas,
                date=menu.date,
                note=menu.nom,
            )
            categories_valides = set(ElementRepas.Categorie.values)
            elements = []
            for ingredient in menu.ingredients:
                nom = str(ingredient.get("nom", "")).strip()[:100]
                if not nom:
                    continue
                try:
                    quantite = max(1, min(3000, int(ingredient.get("quantite_g", 100))))
                except (TypeError, ValueError):
                    quantite = 100
                categorie = ingredient.get("categorie")
                if categorie not in categories_valides:
                    categorie = deviner_categorie(nom) or ElementRepas.Categorie.FRUIT_LEGUME
                elements.append(ElementRepas(
                    repas=repas, aliment=nom.casefold(), categorie=categorie, quantite_g=quantite,
                ))
            if not elements:
                transaction.set_rollback(True)
                messages.error(request, "Ce menu ne contient aucun ingrédient valide.")
                return redirect(f"/planning/?semaine={menu.plan.semaine_du:%Y-%m-%d}")
            ElementRepas.objects.bulk_create(elements)
            menu.repas_realise = repas
            menu.save(update_fields=["repas_realise"])
            messages.success(
                request,
                "Menu ajouté à vos repas. Envoyez maintenant une photo ou une vidéo pour gagner des points après validation.",
            )
    return redirect(f"{reverse('impact:soumettre_preuve')}?repas={repas.pk}")


@citoyen_requis
def courses(request, plan_id):
    plan = get_object_or_404(
        PlanMenu.objects.prefetch_related("menus"), pk=plan_id, utilisateur=request.user
    )
    return render(request, "planning/courses.html", {
        "plan": plan, "courses": liste_courses(plan),
        "fin_semaine": plan.semaine_du + timedelta(days=6),
    })
