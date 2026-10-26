from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("impact", "0005_produitrecompense_sponsor_preuverepas_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="produitrecompense",
            name="mots_cles_recommandation",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Ingrédients à remplacer, séparés par des virgules. "
                    "Exemple : viande hachée, steak, burger."
                ),
                max_length=300,
                verbose_name="mots-clés de recommandation",
            ),
        ),
    ]
