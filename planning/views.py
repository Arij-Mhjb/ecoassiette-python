from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from users.permissions import citoyen_requis

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
    remplacer_menu(menu)
    messages.success(request, "Le repas a été remplacé par une option végétale plus sobre.")
    return redirect(f"/planning/?semaine={menu.plan.semaine_du:%Y-%m-%d}")


@citoyen_requis
def courses(request, plan_id):
    plan = get_object_or_404(
        PlanMenu.objects.prefetch_related("menus"), pk=plan_id, utilisateur=request.user
    )
    return render(request, "planning/courses.html", {
        "plan": plan, "courses": liste_courses(plan),
        "fin_semaine": plan.semaine_du + timedelta(days=6),
    })
