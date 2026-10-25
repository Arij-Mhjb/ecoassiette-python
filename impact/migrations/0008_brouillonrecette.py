from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("impact", "0007_alternativeadoptee_produit_utilise"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BrouillonRecette",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type_repas", models.CharField(max_length=10)),
                ("date", models.DateField()),
                ("note", models.CharField(blank=True, max_length=200)),
                ("texte_original", models.TextField(max_length=5000)),
                ("source", models.CharField(choices=[("GEMINI", "Gemini"), ("LOCAL", "Moteur local")], max_length=8)),
                ("ingredients", models.JSONField(default=list)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("utilisateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="brouillons_recettes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "brouillon de recette",
                "verbose_name_plural": "brouillons de recettes",
                "ordering": ["-modifie_le"],
            },
        ),
    ]
