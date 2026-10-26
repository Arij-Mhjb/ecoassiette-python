from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("impact", "0009_produitrecompense_nutrition"),
        ("planning", "0002_menuplanifie_produit_vegetal"),
    ]

    operations = [
        migrations.AddField(
            model_name="menuplanifie", name="nutrition",
            field=models.JSONField(default=dict),
        ),
    ]
