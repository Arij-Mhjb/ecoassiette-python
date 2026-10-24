from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import ProfilAlimentaire

User = get_user_model()


class ProfilAlimentaireSerializer(serializers.ModelSerializer):
    emission_estimee_hebdo = serializers.DecimalField(max_digits=5, decimal_places=1, read_only=True)

    class Meta:
        model = ProfilAlimentaire
        fields = [
            "regime", "aliments_aimes", "aliments_evites", "taille_foyer", "niveau_activite",
            "temps_cuisine", "ville", "objectif_co2_hebdo", "profil_public",
            "emission_estimee_hebdo", "mis_a_jour",
        ]
        read_only_fields = ["mis_a_jour"]

    def validate(self, attrs):
        # réutilise les règles métier du modèle (aliment aimé ET évité, objectif > empreinte)
        instance = self.instance or ProfilAlimentaire()
        for k, v in attrs.items():
            setattr(instance, k, v)
        from django.core.exceptions import ValidationError as DjangoVE
        try:
            instance.clean()
        except DjangoVE as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs


class UtilisateurSerializer(serializers.ModelSerializer):
    profil = ProfilAlimentaireSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role", "is_active", "date_joined", "profil"]
        read_only_fields = ["id", "username", "role", "is_active", "date_joined"]
