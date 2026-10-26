from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [("impact", "0008_brouillonrecette")]

    operations = [
        migrations.AddField(model_name="produitrecompense", name="calories_100g", field=models.DecimalField(blank=True, decimal_places=1, max_digits=7, null=True, validators=[django.core.validators.MinValueValidator(0)])),
        migrations.AddField(model_name="produitrecompense", name="proteines_100g", field=models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="protéines pour 100 g")),
        migrations.AddField(model_name="produitrecompense", name="glucides_100g", field=models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="glucides pour 100 g")),
        migrations.AddField(model_name="produitrecompense", name="lipides_100g", field=models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="lipides pour 100 g")),
        migrations.AddField(model_name="produitrecompense", name="fibres_100g", field=models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="fibres pour 100 g")),
    ]
