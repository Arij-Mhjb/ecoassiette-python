"""
Balises de template pour le tableau de bord admin EcoAssiette.

{% load eco_admin %}
{% eco_stats app_list as stats %}   -> une carte par modèle visible (compteur + icône)
{% eco_icon "repas" %}              -> icône SVG en ligne
Fonctionne automatiquement avec toutes les apps (users, repas, …) : on ne lit que
les modèles que l'utilisateur a le droit de voir (app_list fourni par l'admin).
"""
from django import template
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()

# Icônes (traces type « Lucide », licence ISC) — 24x24, trait
ICONES = {
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
    "sparkles": '<path d="M9.94 14.06 4 20M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2Z"/>',
    "utensils": '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
    "apple": '<path d="M12 20.94c1.5 0 2.75 1.06 4 1.06 3 0 6-8 6-12.22A4.91 4.91 0 0 0 17 5c-2.22 0-4 1.44-5 2-1-.56-2.78-2-5-2a4.9 4.9 0 0 0-5 4.78C2 14 5 22 8 22c1.25 0 2.5-1.06 4-1.06Z"/><path d="M10 2c1 .5 2 2 2 5"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    "box": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
    "plus": '<path d="M5 12h14M12 5v14"/>',
    "arrow": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20M2 12h20"/>',
    "trend": '<path d="M22 7 13.5 15.5 8.5 10.5 2 17"/><path d="M16 7h6v6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
}

# mot-clé dans « app_label.model » -> (icône, teinte)
REGLES = [
    ("analyse", "sparkles", "violet"),
    ("profil", "leaf", "green"),
    ("utilisateur", "users", "blue"),
    ("user", "users", "blue"),
    ("element", "apple", "orange"),
    ("aliment", "apple", "orange"),
    ("repas", "utensils", "amber"),
    ("group", "shield", "slate"),
    ("recette", "leaf", "green"),
    ("carbone", "globe", "teal"),
]


def _style(cle):
    cle = cle.lower()
    for mot, icone, teinte in REGLES:
        if mot in cle:
            return icone, teinte
    return "box", "slate"


@register.simple_tag
def eco_icon(nom, taille=20):
    trace = ICONES.get(nom, ICONES["box"])
    return mark_safe(
        f'<svg aria-hidden="true" width="{taille}" height="{taille}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{trace}</svg>'
    )


@register.simple_tag
def eco_app_icon(app_label):
    return eco_icon(_style(app_label)[0], 18)


@register.simple_tag
def eco_stats(app_list):
    cartes = []
    for app in app_list or []:
        for m in app.get("models", []):
            modele = m.get("model")
            if modele is None:
                continue
            try:
                total = modele._default_manager.count()
            except Exception:  # table absente (migration non appliquée…)
                continue
            icone, teinte = _style(f"{app['app_label']}.{m['object_name']}")
            cartes.append({
                "nom": m["name"], "app": app["name"], "total": total, "url": m.get("admin_url"),
                "add_url": m.get("add_url"), "icone": icone, "teinte": teinte,
            })
    return cartes


@register.simple_tag
def eco_resume():
    """Indicateurs clés en tête du tableau de bord."""
    User = get_user_model()
    maintenant = timezone.now()
    semaine = maintenant - timezone.timedelta(days=7)
    return {
        "inscrits_7j": User.objects.filter(date_joined__gte=semaine).count(),
        "actifs": User.objects.filter(is_active=True).count(),
        "connectes_7j": User.objects.filter(last_login__gte=semaine).count(),
    }
