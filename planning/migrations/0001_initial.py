from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("repas", "0006_analyse_audio"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlanMenu",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("semaine_du", models.DateField(verbose_name="semaine du")),
                ("objectif_co2", models.DecimalField(decimal_places=2, default=20, max_digits=7, validators=[django.core.validators.MinValueValidator(0.1)], verbose_name="objectif carbone hebdomadaire (kg CO₂e)")),
                ("source", models.CharField(choices=[("GEMINI", "Gemini"), ("LOCAL", "Moteur local")], max_length=8)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("utilisateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plans_menus", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-semaine_du"]},
        ),
        migrations.CreateModel(
            name="MenuPlanifie",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("type_repas", models.CharField(choices=[("DEJEUNER", "Déjeuner"), ("DINER", "Dîner")], max_length=10)),
                ("nom", models.CharField(max_length=160)),
                ("ingredients", models.JSONField(default=list)),
                ("instructions", models.JSONField(default=list)),
                ("co2_estime", models.DecimalField(decimal_places=2, max_digits=7, validators=[django.core.validators.MinValueValidator(0)])),
                ("co2_avant", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("explication", models.CharField(blank=True, max_length=300)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="menus", to="planning.planmenu")),
                ("repas_source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="menus_alternatifs", to="repas.repas")),
            ],
            options={"ordering": ["date", "type_repas"]},
        ),
        migrations.AddConstraint(
            model_name="planmenu",
            constraint=models.UniqueConstraint(fields=("utilisateur", "semaine_du"), name="plan_unique_par_semaine"),
        ),
        migrations.AddConstraint(
            model_name="menuplanifie",
            constraint=models.UniqueConstraint(fields=("plan", "date", "type_repas"), name="menu_unique_par_creneau"),
        ),
    ]
