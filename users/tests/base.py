from django.test import TestCase, override_settings

from users.models import Utilisateur

MDP = "UnMotDePasse!Solide42"


@override_settings(IA_SYNCHRONE=True, GEMINI_API_KEY="")
class BaseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.citoyen = cls.creer("citoyen", Utilisateur.Role.CITOYEN)
        cls.autre = cls.creer("autre", Utilisateur.Role.CITOYEN)
        cls.nutri = cls.creer("nutri", Utilisateur.Role.NUTRITIONNISTE)
        cls.admin = cls.creer("admin1", Utilisateur.Role.ADMIN)

    @staticmethod
    def creer(username, role, **kw):
        return Utilisateur.objects.create_user(
            username=username, email=f"{username}@test.tn", password=MDP, role=role,
            first_name=username.title(), last_name="Test", **kw,
        )
