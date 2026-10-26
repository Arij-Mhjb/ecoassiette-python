from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("planning", "0003_menuplanifie_nutrition")]

    operations = [
        migrations.AddField(
            model_name="planmenu", name="numero_generation",
            field=models.PositiveIntegerField(default=1, editable=False),
        ),
    ]
