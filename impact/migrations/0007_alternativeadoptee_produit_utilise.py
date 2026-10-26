from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("impact", "0006_produitrecompense_mots_cles_recommandation"),
    ]

    operations = [
        migrations.AddField(
            model_name="alternativeadoptee",
            name="produit_utilise",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="utilisations_recettes",
                to="impact.produitrecompense",
                verbose_name="produit végétal utilisé",
            ),
        ),
    ]
