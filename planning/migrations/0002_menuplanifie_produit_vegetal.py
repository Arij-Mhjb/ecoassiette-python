from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("impact", "0008_brouillonrecette"),
        ("planning", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="menuplanifie",
            name="produit_vegetal",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="menus_planifies", to="impact.produitrecompense",
                verbose_name="produit végétal recommandé",
            ),
        ),
    ]
