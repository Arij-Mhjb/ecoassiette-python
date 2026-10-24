from django.contrib import admin

from .models import ElementRepas, Repas


class ElementRepasInline(admin.TabularInline):
    model = ElementRepas
    extra = 1


@admin.register(Repas)
class RepasAdmin(admin.ModelAdmin):
    list_display = ("__str__", "utilisateur", "type_repas", "date", "nb_elements")
    list_filter = ("type_repas", "date")
    search_fields = ("utilisateur__username", "note", "elements__aliment")
    date_hierarchy = "date"
    inlines = [ElementRepasInline]

    @admin.display(description="Nb d'aliments")
    def nb_elements(self, obj):
        return obj.elements.count()


@admin.register(ElementRepas)
class ElementRepasAdmin(admin.ModelAdmin):
    list_display = ("aliment", "categorie", "quantite_g", "repas")
    list_filter = ("categorie",)
    search_fields = ("aliment",)