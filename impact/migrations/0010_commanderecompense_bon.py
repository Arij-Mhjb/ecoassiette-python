from django.db import migrations, models
import impact.models
import secrets


def remplir_codes(apps, schema_editor):
    Commande = apps.get_model("impact", "CommandeRecompense")
    for commande in Commande.objects.filter(code_bon__isnull=True):
        while True:
            code = "ECO-" + secrets.token_hex(6).upper()
            if not Commande.objects.filter(code_bon=code).exists():
                commande.code_bon = code
                commande.save(update_fields=["code_bon"])
                break


class Migration(migrations.Migration):

    dependencies = [("impact", "0009_produitrecompense_nutrition")]

    operations = [
        migrations.AddField(
            model_name="commanderecompense", name="code_bon",
            field=models.CharField(blank=True, editable=False, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="commanderecompense", name="utilise_le",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="commanderecompense", name="statut",
            field=models.CharField(choices=[("CONFIRMEE", "Confirmée"), ("LIVREE", "Livrée"), ("ANNULEE", "Annulée"), ("UTILISEE", "Utilisée chez le sponsor")], default="CONFIRMEE", max_length=10),
        ),
        migrations.RunPython(remplir_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="commanderecompense", name="code_bon",
            field=models.CharField(default=impact.models.generer_code_bon, editable=False, max_length=20, unique=True),
        ),
    ]
