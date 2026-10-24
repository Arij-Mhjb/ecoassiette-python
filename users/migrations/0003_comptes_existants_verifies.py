from django.db import migrations


def marquer_verifies(apps, schema_editor):
    # Les comptes créés avant l'ajout de la confirmation e-mail restent utilisables.
    apps.get_model("users", "Utilisateur").objects.update(email_verifie=True)


class Migration(migrations.Migration):
    dependencies = [("users", "0002_email_verifie")]
    operations = [migrations.RunPython(marquer_verifies, migrations.RunPython.noop)]
