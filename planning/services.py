from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from impact.models import FacteurImpact, ProduitRecompense
from impact.services import analyser_repas
from impact.nutrition import calculer_nutrition, normaliser_nom
from repas.models import Repas
from users.ai import ErreurIA, appeler_gemini


MENUS_LOCAUX = [
    ("Bowl de lentilles méditerranéen", [("lentilles", 160, "LEGUMINEUSE"), ("tomates", 120, "FRUIT_LEGUME"), ("riz", 80, "FECULENT")]),
    ("Couscous végétal aux pois chiches", [("pois chiches", 160, "LEGUMINEUSE"), ("semoule", 100, "FECULENT"), ("courgette", 150, "FRUIT_LEGUME")]),
    ("Burger veggie aux haricots", [("haricots rouges", 160, "LEGUMINEUSE"), ("pain burger", 80, "FECULENT"), ("tomate", 100, "FRUIT_LEGUME")]),
    ("Tofu grillé et légumes", [("tofu", 150, "LEGUMINEUSE"), ("riz", 90, "FECULENT"), ("poivron", 120, "FRUIT_LEGUME")]),
    ("Pâtes bolognaise aux lentilles", [("lentilles", 140, "LEGUMINEUSE"), ("pâtes", 100, "FECULENT"), ("tomates", 140, "FRUIT_LEGUME")]),
    ("Tajine végétal aux pois chiches", [("pois chiches", 160, "LEGUMINEUSE"), ("pommes de terre", 130, "FECULENT"), ("carottes", 100, "FRUIT_LEGUME")]),
    ("Salade de quinoa et tofu", [("tofu", 140, "LEGUMINEUSE"), ("quinoa", 90, "FECULENT"), ("concombre", 120, "FRUIT_LEGUME")]),
    ("Curry de pois chiches aux épinards", [("pois chiches", 160, "LEGUMINEUSE"), ("riz", 80, "FECULENT"), ("épinards", 140, "FRUIT_LEGUME")]),
    ("Chili sin carne aux haricots rouges", [("haricots rouges", 170, "LEGUMINEUSE"), ("riz", 80, "FECULENT"), ("poivrons et tomates", 150, "FRUIT_LEGUME")]),
    ("Galettes de lentilles et quinoa", [("lentilles", 150, "LEGUMINEUSE"), ("quinoa", 70, "FECULENT"), ("salade", 140, "FRUIT_LEGUME")]),
    ("Wok de tofu aux nouilles", [("tofu", 150, "LEGUMINEUSE"), ("pâtes", 90, "FECULENT"), ("légumes croquants", 160, "FRUIT_LEGUME")]),
    ("Tempeh sauté au riz et brocoli", [("tempeh", 140, "LEGUMINEUSE"), ("riz", 85, "FECULENT"), ("brocoli", 160, "FRUIT_LEGUME")]),
    ("Soupe de lentilles et tartine complète", [("lentilles", 160, "LEGUMINEUSE"), ("pain complet", 70, "FECULENT"), ("carottes et céleri", 150, "FRUIT_LEGUME")]),
    ("Falafels et semoule aux légumes", [("pois chiches", 160, "LEGUMINEUSE"), ("semoule", 90, "FECULENT"), ("tomates et concombre", 150, "FRUIT_LEGUME")]),
    ("Dahl de lentilles corail au riz", [("lentilles corail", 160, "LEGUMINEUSE"), ("riz", 80, "FECULENT"), ("tomates et épinards", 150, "FRUIT_LEGUME")]),
    ("Wrap de tofu aux crudités", [("tofu", 150, "LEGUMINEUSE"), ("pain wrap", 80, "FECULENT"), ("crudités", 150, "FRUIT_LEGUME")]),
    ("Keftas végétales aux haricots", [("haricots rouges", 160, "LEGUMINEUSE"), ("semoule", 90, "FECULENT"), ("légumes grillés", 150, "FRUIT_LEGUME")]),
    ("Gratin de pois chiches et légumes", [("pois chiches", 160, "LEGUMINEUSE"), ("pommes de terre", 120, "FECULENT"), ("courgettes", 150, "FRUIT_LEGUME")]),
    ("Nouilles au tempeh sauce cacahuète", [("tempeh", 140, "LEGUMINEUSE"), ("pâtes", 90, "FECULENT"), ("carottes et chou", 160, "FRUIT_LEGUME")]),
    ("Taboulé de quinoa aux pois chiches", [("pois chiches", 140, "LEGUMINEUSE"), ("quinoa", 90, "FECULENT"), ("tomates et persil", 160, "FRUIT_LEGUME")]),
    ("Parmentier végétal aux lentilles", [("lentilles", 160, "LEGUMINEUSE"), ("pommes de terre", 140, "FECULENT"), ("carottes et oignon", 130, "FRUIT_LEGUME")]),
]


def _co2(ingredients):
    facteurs = {f.categorie: f.co2_kg_par_kg for f in FacteurImpact.objects.all()}
    total = sum(
        Decimal(str(i[1])) / Decimal("1000") * facteurs.get(i[2], Decimal("0"))
        for i in ingredients
    )
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _menu_dict(nom, ingredients, produit=None):
    ingredients_structures = [
        {"nom": n, "quantite_g": q, "categorie": c} for n, q, c in ingredients
    ]
    produits = {}
    if produit:
        produits[normaliser_nom(produit.nom)] = produit
    return {
        "nom": nom,
        "ingredients": ingredients_structures,
        "instructions": [
            "Préparez les ingrédients selon les quantités indiquées.",
            "Assemblez, assaisonnez avec des épices et servez chaud ou froid selon la recette.",
        ],
        "co2_estime": _co2(ingredients),
        "produit": produit,
        "nutrition": calculer_nutrition(ingredients_structures, produits),
    }


def _menus_produits_vegetaux():
    """Transforme les produits partenaires disponibles en vrais menus végétaux."""
    menus = []
    formes_utilisees = set()
    produits = ProduitRecompense.objects.filter(
        statut=ProduitRecompense.Statut.PUBLIE,
        produit_vegetal=True,
        stock__gt=0,
        sponsor__actif=True,
    ).select_related("sponsor")
    for produit in produits:
        nom_produit = produit.nom.casefold()
        texte_complet = f"{produit.nom} {produit.description} {produit.mots_cles_recommandation}".casefold()
        # Le nom commercial décrit mieux la forme réelle du produit que ses
        # mots-clés de recommandation (qui peuvent contenir burger + steak + haché).
        if any(mot in nom_produit for mot in ("burger", "hamburger")):
            format_menu = "BURGER"
        elif any(mot in nom_produit for mot in ("haché", "hache", "mincé", "mince")):
            format_menu = "HACHE"
        elif "steak" in nom_produit:
            format_menu = "STEAK"
        elif any(mot in nom_produit for mot in ("poulet", "chicken", "volaille")):
            format_menu = "POULET"
        elif any(mot in nom_produit for mot in ("saucisse", "merguez", "sausage")):
            format_menu = "SAUCISSE"
        elif any(mot in texte_complet for mot in ("burger", "hamburger")):
            format_menu = "BURGER"
        elif any(mot in texte_complet for mot in ("haché", "hache", "viande hach")):
            format_menu = "HACHE"
        elif "steak" in texte_complet:
            format_menu = "STEAK"
        else:
            format_menu = "GENERIC"

        if format_menu == "BURGER":
            variantes = [
                ("HAMBURGER", f"Hamburger veggie avec {produit.nom}", "pain burger", "tomate et salade",
                 [f"Faites cuire {produit.nom}.", "Toastez le pain et préparez les crudités.", "Assemblez le hamburger."]),
                ("BURGER_ASSIETTE", f"Burger veggie en assiette avec {produit.nom}", "pommes de terre", "légumes grillés",
                 [f"Faites griller {produit.nom}.", "Préparez les pommes de terre et les légumes.", "Servez le burger sans pain avec son accompagnement."]),
                ("BURGER_WRAP", f"Wrap burger veggie avec {produit.nom}", "pain wrap", "crudités",
                 [f"Découpez puis faites dorer {produit.nom}.", "Garnissez le wrap de crudités.", "Roulez puis servez chaud."]),
            ]
        elif format_menu == "HACHE":
            variantes = [
                ("BOLOGNAISE", f"Bolognaise veggie avec {produit.nom}", "pâtes", "tomates et oignon",
                 ["Faites revenir l'oignon et la tomate.", f"Émiettez {produit.nom} dans la sauce.", "Servez avec les pâtes."]),
                ("TACOS_HACHE", f"Tacos veggie avec {produit.nom}", "pain wrap", "tomate, salade et maïs",
                 [f"Faites revenir {produit.nom} avec des épices.", "Garnissez les wraps de légumes.", "Pliez et faites légèrement griller."]),
                ("KEFTA_HACHE", f"Keftas veggie avec {produit.nom}", "semoule", "courgette et tomate",
                 [f"Façonnez {produit.nom} en petites keftas épicées.", "Faites-les dorer et préparez la semoule.", "Servez avec les légumes."]),
            ]
        elif format_menu == "STEAK":
            variantes = [
                ("STEAK_ASSIETTE", f"Steak veggie et légumes avec {produit.nom}", "pommes de terre", "légumes grillés",
                 [f"Faites griller {produit.nom}.", "Cuisez les pommes de terre et les légumes.", "Dressez l'assiette."]),
                ("STEAK_SANDWICH", f"Sandwich au steak veggie {produit.nom}", "pain complet", "tomate et salade",
                 [f"Faites cuire {produit.nom}.", "Toastez le pain et préparez les crudités.", "Assemblez le sandwich."]),
                ("STEAK_EMINCE", f"Émincé de steak veggie au riz avec {produit.nom}", "riz", "poivrons et oignon",
                 [f"Découpez et faites dorer {produit.nom}.", "Sautez les légumes et cuisez le riz.", "Assemblez l'assiette."]),
            ]
        elif format_menu == "POULET":
            variantes = [
                ("POULET_BOWL", f"Bowl végétal avec {produit.nom}", "riz", "légumes de saison",
                 [f"Faites dorer {produit.nom}.", "Cuisez le riz et les légumes.", "Assemblez le bowl."]),
                ("POULET_WRAP", f"Wrap au poulet végétal {produit.nom}", "pain wrap", "crudités",
                 [f"Faites cuire {produit.nom}.", "Garnissez le wrap de crudités.", "Roulez et servez."]),
                ("POULET_CURRY", f"Curry de poulet végétal {produit.nom}", "riz", "tomates et épinards",
                 [f"Faites revenir {produit.nom} avec du curry.", "Ajoutez les légumes et laissez mijoter.", "Servez avec le riz."]),
            ]
        elif format_menu == "SAUCISSE":
            variantes = [
                ("SAUCISSE_ASSIETTE", f"Assiette de saucisses végétales {produit.nom}", "pommes de terre", "légumes grillés",
                 [f"Faites cuire {produit.nom}.", "Préparez les accompagnements.", "Servez avec une sauce légère."]),
                ("SAUCISSE_COUSCOUS", f"Couscous aux saucisses végétales {produit.nom}", "semoule", "courgette et carotte",
                 [f"Faites dorer {produit.nom}.", "Préparez les légumes et la semoule.", "Assemblez le couscous."]),
            ]
        else:
            variantes = [
                ("GENERIC_ASSIETTE", f"Assiette végétale avec {produit.nom}", "quinoa", "crudités",
                 [f"Préparez {produit.nom}.", "Cuisez le quinoa et préparez les crudités.", "Assemblez et assaisonnez."]),
                ("GENERIC_BOWL", f"Bowl complet avec {produit.nom}", "riz", "légumes de saison",
                 [f"Préparez {produit.nom}.", "Cuisez le riz et les légumes.", "Assemblez le bowl."]),
            ]

        # Jusqu'à deux plats différents par produit. Une forme déjà utilisée
        # par un autre produit est ignorée afin d'éviter les doublons sémantiques.
        ajoutes = 0
        for forme, nom, feculent, legumes, instructions in variantes:
            if forme in formes_utilisees:
                continue
            formes_utilisees.add(forme)
            ingredients = [
                (produit.nom, 150, "LEGUMINEUSE"),
                (feculent, 90, "FECULENT"),
                (legumes, 150, "FRUIT_LEGUME"),
            ]
            menu = _menu_dict(nom, ingredients, produit=produit)
            menu["instructions"] = instructions
            menus.append(menu)
            ajoutes += 1
            if ajoutes == 2 or len(menus) == 8:
                break
        if len(menus) == 8:
            break
    return menus


def _menus_ia(profil, anciens_noms=None):
    prompt = (
        "Propose 7 repas végétaux variés pour une personne, à répéter en déjeuner/dîner sur une semaine. "
        "Réponds uniquement en JSON : "
        '{"menus":[{"nom":"...","ingredients":[{"nom":"...","quantite_g":150,"categorie":"LEGUMINEUSE"}],"instructions":["..."]}]}. '
        "Catégories autorisées : LEGUMINEUSE, FECULENT, FRUIT_LEGUME. "
        f"Aliments évités : {getattr(profil, 'aliments_evites', '')}. "
        f"Ne répète aucun de ces anciens menus : {', '.join(anciens_noms or [])}."
    )
    brut = appeler_gemini(prompt)
    propres = []
    for menu in brut.get("menus", [])[:7] if isinstance(brut, dict) else []:
        ingredients = []
        for item in menu.get("ingredients", [])[:8]:
            try:
                categorie = str(item["categorie"])
                quantite = int(item["quantite_g"])
                nom = str(item["nom"])[:100]
            except (KeyError, TypeError, ValueError):
                continue
            if categorie in {"LEGUMINEUSE", "FECULENT", "FRUIT_LEGUME"} and 1 <= quantite <= 1000:
                ingredients.append((nom, quantite, categorie))
        if ingredients and menu.get("nom"):
            resultat = _menu_dict(str(menu["nom"])[:160], ingredients)
            resultat["instructions"] = [str(x)[:250] for x in menu.get("instructions", [])[:6]] or resultat["instructions"]
            propres.append(resultat)
    if len(propres) < 5:
        raise ErreurIA("Menus IA incomplets")
    return propres


def generer_plan(plan):
    anciens_noms = list(plan.menus.values_list("nom", flat=True))
    menus_locaux = [_menu_dict(nom, ingredients) for nom, ingredients in MENUS_LOCAUX]
    try:
        menus_ia = _menus_ia(getattr(plan.utilisateur, "profil", None), anciens_noms)
        plan.source = "GEMINI"
    except ErreurIA:
        menus_ia = []
        plan.source = "LOCAL"
    # Les produits réels et les résultats IA sont complétés par un catalogue
    # suffisamment large pour proposer 14 plats distincts à chaque génération.
    catalog_brut = _menus_produits_vegetaux() + menus_ia + menus_locaux
    catalog, noms_vus = [], set()
    for menu in catalog_brut:
        cle = menu["nom"].strip().casefold()
        if cle not in noms_vus:
            noms_vus.add(cle)
            catalog.append(menu)
    decalage = ((plan.numero_generation - 1) * 7) % len(catalog)
    catalog = catalog[decalage:] + catalog[:decalage]
    plan.save(update_fields=["source", "modifie_le"])
    existants = Repas.objects.filter(
        utilisateur=plan.utilisateur,
        date__range=(plan.semaine_du, plan.semaine_du + timedelta(days=6)),
        type_repas__in=("DEJEUNER", "DINER"),
    ).prefetch_related("elements")
    par_creneau = {(r.date, r.type_repas): r for r in existants}
    plan.menus.all().delete()
    for jour in range(7):
        date = plan.semaine_du + timedelta(days=jour)
        for index_type, type_repas in enumerate(("DEJEUNER", "DINER")):
            menu = catalog[(jour * 2 + index_type) % len(catalog)]
            repas_source = par_creneau.get((date, type_repas))
            co2_avant = None
            explication = "Menu végétal équilibré pour réduire l'empreinte de la semaine."
            if repas_source:
                co2_avant = analyser_repas(repas_source, plan.utilisateur)["totaux"]["co2"]
                if co2_avant > menu["co2_estime"]:
                    explication = f"Remplacement conseillé pour « {repas_source.note or repas_source} » trop émetteur."
            plan.menus.create(
                date=date, type_repas=type_repas, nom=menu["nom"],
                ingredients=menu["ingredients"], instructions=menu["instructions"],
                nutrition=menu["nutrition"], co2_estime=menu["co2_estime"], repas_source=repas_source,
                produit_vegetal=menu.get("produit"), co2_avant=co2_avant, explication=explication,
            )
    return plan


def remplacer_menu(menu):
    catalog = _menus_produits_vegetaux() + [
        _menu_dict(nom, ingredients) for nom, ingredients in MENUS_LOCAUX
    ]
    actuel = next((i for i, m in enumerate(catalog) if m["nom"] == menu.nom), -1)
    candidats = catalog[actuel + 1:] + catalog[:actuel + 1]
    nouveau = min(candidats, key=lambda m: m["co2_estime"])
    menu.nom = nouveau["nom"]
    menu.ingredients = nouveau["ingredients"]
    menu.instructions = nouveau["instructions"]
    menu.nutrition = nouveau["nutrition"]
    menu.co2_estime = nouveau["co2_estime"]
    menu.produit_vegetal = nouveau.get("produit")
    menu.explication = "Alternative végétale plus sobre sélectionnée intelligemment."
    menu.save()
    return menu


def liste_courses(plan):
    totaux = defaultdict(int)
    for menu in plan.menus.all():
        for ingredient in menu.ingredients:
            totaux[ingredient["nom"].strip().casefold()] += int(ingredient["quantite_g"])
    return [{"nom": nom, "quantite_g": quantite} for nom, quantite in sorted(totaux.items())]
