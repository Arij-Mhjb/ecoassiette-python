from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def charger_referentiel(apps, schema_editor):
    Facteur = apps.get_model("impact", "FacteurImpact")
    Alternative = apps.get_model("impact", "AlternativeVegetale")
    source = "Moyennes de catégories inspirées de Poore & Nemecek (2018), à remplacer par le référentiel validé du projet"
    donnees = [
        ("VIANDE_ROUGE", "35.000", "14500.00", "160.000", "ELEVE"),
        ("VOLAILLE", "9.900", "4300.00", "12.000", "MOYEN"),
        ("POISSON", "6.100", "3500.00", "8.000", "MOYEN"),
        ("LAITIER", "10.000", "5000.00", "14.000", "MOYEN"),
        ("LEGUMINEUSE", "0.900", "1250.00", "3.500", "FAIBLE"),
        ("FECULENT", "1.200", "1600.00", "2.800", "FAIBLE"),
        ("FRUIT_LEGUME", "0.500", "500.00", "1.000", "FAIBLE"),
    ]
    facteurs = {}
    for categorie, co2, eau, terres, risque in donnees:
        facteurs[categorie] = Facteur.objects.create(
            categorie=categorie, co2_kg_par_kg=co2, eau_litres_par_kg=eau,
            terres_m2_par_kg=terres, risque_deforestation=risque, source=source,
        )
    alternatives = [
        ("VIANDE_ROUGE", "bœuf", "lentilles", "Préparez-les avec les mêmes épices et une sauce tomate."),
        ("VIANDE_ROUGE", "boeuf", "lentilles", "Préparez-les avec les mêmes épices et une sauce tomate."),
        ("VIANDE_ROUGE", "agneau", "pois chiches", "Une alternative adaptée au couscous et aux ragoûts."),
        ("VIANDE_ROUGE", "", "lentilles", "Utilisez des lentilles, des haricots ou du seitan selon la recette."),
        ("VOLAILLE", "", "tofu mariné", "Faites mariner le tofu avec les épices du plat avant de le griller."),
        ("POISSON", "", "pois chiches aux algues", "Les algues apportent une note marine au plat."),
        ("LAITIER", "lait", "lait d'avoine", "Choisissez une version sans sucre pour les plats salés."),
        ("LAITIER", "fromage", "crème de cajou", "Mixez des noix de cajou réhydratées avec du citron."),
        ("LAITIER", "œuf", "tofu soyeux", "Le tofu soyeux convient aux préparations crémeuses."),
        ("LAITIER", "oeuf", "tofu soyeux", "Le tofu soyeux convient aux préparations crémeuses."),
        ("LAITIER", "", "alternative végétale", "Choisissez une alternative végétale adaptée à la recette."),
    ]
    for categorie, aliment, remplacement, idee in alternatives:
        Alternative.objects.create(
            categorie_source=categorie, aliment_source=aliment, remplacement=remplacement,
            idee=idee, facteur_remplacement=facteurs["LEGUMINEUSE"],
        )


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="FacteurImpact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("categorie", models.CharField(max_length=15, unique=True, verbose_name="catégorie")),
                ("co2_kg_par_kg", models.DecimalField(decimal_places=3, max_digits=9, validators=[django.core.validators.MinValueValidator(0)], verbose_name="kg CO₂e par kg")),
                ("eau_litres_par_kg", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="litres d'eau par kg")),
                ("terres_m2_par_kg", models.DecimalField(decimal_places=3, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name="m² de terres par kg")),
                ("risque_deforestation", models.CharField(choices=[("FAIBLE", "Faible"), ("MOYEN", "Moyen"), ("ELEVE", "Élevé")], default="FAIBLE", max_length=8)),
                ("source", models.CharField(max_length=250)),
            ],
            options={"verbose_name": "facteur d'impact", "verbose_name_plural": "facteurs d'impact", "ordering": ["categorie"]},
        ),
        migrations.CreateModel(
            name="AlternativeVegetale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("aliment_source", models.CharField(blank=True, help_text="Mot à détecter dans l'aliment, par exemple bœuf. Laisser vide pour toute la catégorie.", max_length=100)),
                ("categorie_source", models.CharField(max_length=15, verbose_name="catégorie d'origine")),
                ("remplacement", models.CharField(max_length=100)),
                ("idee", models.CharField(blank=True, max_length=250, verbose_name="conseil de préparation")),
                ("actif", models.BooleanField(default=True)),
                ("facteur_remplacement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="alternatives", to="impact.facteurimpact")),
            ],
            options={"verbose_name": "alternative végétale", "verbose_name_plural": "alternatives végétales", "ordering": ["categorie_source", "aliment_source", "remplacement"]},
        ),
        migrations.RunPython(charger_referentiel, migrations.RunPython.noop),
    ]
