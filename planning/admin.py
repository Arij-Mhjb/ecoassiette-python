from django.contrib import admin

from .models import MenuPlanifie, PlanMenu


class MenuPlanifieInline(admin.TabularInline):
    model = MenuPlanifie
    extra = 0
    readonly_fields = ("date", "type_repas", "nom", "co2_estime", "repas_source", "produit_vegetal", "co2_avant")


@admin.register(PlanMenu)
class PlanMenuAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "semaine_du", "objectif_co2", "source", "modifie_le")
    list_filter = ("source", "semaine_du")
    search_fields = ("utilisateur__username", "utilisateur__email")
    inlines = (MenuPlanifieInline,)


@admin.register(MenuPlanifie)
class MenuPlanifieAdmin(admin.ModelAdmin):
    list_display = ("nom", "date", "type_repas", "co2_estime", "plan")
    list_filter = ("type_repas", "date")
    search_fields = ("nom", "plan__utilisateur__username")
