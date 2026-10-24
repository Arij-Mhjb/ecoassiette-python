from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "users"

urlpatterns = [
    # Authentification
    path("inscription/", views.inscription, name="inscription"),
    path("inscription/verifiez-vos-emails/", views.verification_envoyee, name="verification_envoyee"),
    path("confirmer/<uidb64>/<token>/", views.confirmer_email, name="confirmer_email"),
    path("confirmer/renvoyer/", views.renvoyer_confirmation, name="renvoyer_confirmation"),
    path("connexion/", views.ConnexionView.as_view(), name="login"),
    path("deconnexion/", views.DeconnexionView.as_view(), name="logout"),
    path("mot-de-passe/", views.ChangementMotDePasseView.as_view(), name="password_change"),
    path("mot-de-passe/oubli/", auth_views.PasswordResetView.as_view(
        template_name="users/form_page.html",
        email_template_name="users/emails/reset.txt",
        html_email_template_name="users/emails/reset.html",
        subject_template_name="users/emails/reset_sujet.txt",
        success_url=reverse_lazy("users:password_reset_done"),
        extra_context={"titre": "Mot de passe oublié",
                       "intro": "Saisissez votre e-mail : vous recevrez un lien de réinitialisation."},
    ), name="password_reset"),
    path("mot-de-passe/oubli/envoye/", auth_views.PasswordResetDoneView.as_view(
        template_name="users/message.html",
        extra_context={"titre": "E-mail envoyé",
                       "texte": "Si un compte correspond à cette adresse, un lien de réinitialisation vient d'être envoyé."},
    ), name="password_reset_done"),
    path("mot-de-passe/reinitialiser/<uidb64>/<token>/", views.ReinitialisationConfirmView.as_view(),
         name="password_reset_confirm"),
    path("mot-de-passe/reinitialise/", auth_views.PasswordResetCompleteView.as_view(
        template_name="users/message.html",
        extra_context={"titre": "Mot de passe modifié", "texte": "Vous pouvez maintenant vous connecter."},
    ), name="password_reset_complete"),

    # Espace citoyen
    path("profil/", views.profil, name="profil"),
    path("profil/infos/", views.modifier_infos, name="modifier_infos"),
    path("profil/habitudes/", views.modifier_profil, name="modifier_profil"),
    path("profil/supprimer/", views.supprimer_compte, name="supprimer_compte"),

    # IA
    path("profil/analyse/", views.analyse_lancer, name="analyse_lancer"),
    path("profil/analyse/<int:pk>/", views.analyse_etat, name="analyse_etat"),
    path("profil/analyse/<int:pk>/appliquer/", views.appliquer_objectif, name="appliquer_objectif"),

    # Nutritionniste
    path("profils/", views.ProfilsPublicsView.as_view(), name="nutri_profils"),
    path("profils/<int:pk>/", views.ProfilPublicDetailView.as_view(), name="nutri_profil_detail"),

    # Administration (CRUD)
    path("gestion/", views.UtilisateurListView.as_view(), name="admin_liste"),
    path("gestion/nouveau/", views.UtilisateurCreateView.as_view(), name="admin_creer"),
    path("gestion/statistiques/", views.StatistiquesView.as_view(), name="admin_stats"),
    path("gestion/<int:pk>/", views.UtilisateurDetailView.as_view(), name="admin_detail"),
    path("gestion/<int:pk>/modifier/", views.UtilisateurUpdateView.as_view(), name="admin_modifier"),
    path("gestion/<int:pk>/supprimer/", views.UtilisateurDeleteView.as_view(), name="admin_supprimer"),
    path("gestion/<int:pk>/basculer/", views.UtilisateurBasculerActifView.as_view(), name="admin_basculer"),
]
