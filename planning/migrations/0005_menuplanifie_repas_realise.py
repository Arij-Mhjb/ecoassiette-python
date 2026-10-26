from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("planning", "0004_planmenu_numero_generation"),
        ("repas", "0006_analyse_audio"),
    ]

    operations = [
        migrations.AddField(
            model_name="menuplanifie",
            name="repas_realise",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="menu_planifie",
                to="repas.repas",
                verbose_name="repas ajouté",
            ),
        ),
    ]
