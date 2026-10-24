"""
API REST du module (DRF). Utilisée par les autres modules de l'équipe
(suivi des repas, impact carbone…) pour lire le profil de l'utilisateur connecté.
"""
from django.contrib.auth import get_user_model
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from .serializers import ProfilAlimentaireSerializer, UtilisateurSerializer

User = get_user_model()


class PeutGererUtilisateurs(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_perm("users.gerer_utilisateurs")


@api_view(["GET", "PATCH"])
def moi(request):
    """GET : mon compte + profil. PATCH : modifier prénom/nom/e-mail."""
    if request.method == "PATCH":
        s = UtilisateurSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
    return Response(UtilisateurSerializer(request.user).data)


@api_view(["GET", "PUT", "PATCH"])
def mon_profil(request):
    p = request.user.profil
    if request.method == "GET":
        return Response(ProfilAlimentaireSerializer(p).data)
    s = ProfilAlimentaireSerializer(p, data=request.data, partial=request.method == "PATCH")
    if s.is_valid():
        s.save()
        return Response(s.data)
    return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


class UtilisateurListAPI(ListAPIView):
    """Liste des comptes — réservée aux administrateurs."""
    serializer_class = UtilisateurSerializer
    permission_classes = [PeutGererUtilisateurs]

    def get_queryset(self):
        qs = User.objects.select_related("profil").order_by("id")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return qs


@api_view(["GET"])
@permission_classes([PeutGererUtilisateurs])
def utilisateur_detail(request, pk):
    try:
        u = User.objects.select_related("profil").get(pk=pk)
    except User.DoesNotExist:
        return Response({"detail": "Utilisateur introuvable."}, status=status.HTTP_404_NOT_FOUND)
    return Response(UtilisateurSerializer(u).data)
