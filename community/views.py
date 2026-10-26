from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import CommentaireForm, PublicationForm
from .models import Commentaire, Jaime, NotificationCommunaute, Publication

User = get_user_model()


def _notifier_mentions(*, acteur, publication, utilisateurs, commentaire=None):
    type_notification = (
        NotificationCommunaute.Type.COMMENTAIRE if commentaire
        else NotificationCommunaute.Type.PUBLICATION
    )
    for destinataire in utilisateurs:
        if destinataire.pk != acteur.pk:
            NotificationCommunaute.objects.get_or_create(
                destinataire=destinataire,
                acteur=acteur,
                type=type_notification,
                publication=publication,
                commentaire=commentaire,
            )


def _publications_pour(utilisateur):
    commentaires = Commentaire.objects.select_related("auteur").prefetch_related("mentions").order_by("cree_le")
    visibles = Publication.objects.all() if utilisateur.est_admin else Publication.objects.filter(est_masquee=False)
    return (
        visibles
        .select_related("auteur", "publication_originale__auteur")
        .prefetch_related("mentions", Prefetch("commentaires", queryset=commentaires))
        .annotate(
            nb_jaimes=Count("jaimes", distinct=True),
            nb_commentaires=Count("commentaires", distinct=True),
            nb_partages=Count("republications", distinct=True),
            aime_par_moi=Exists(Jaime.objects.filter(publication=OuterRef("pk"), utilisateur=utilisateur)),
        )
        .order_by("-creee_le", "-pk")
    )


def _retour(request, publication=None):
    cible = request.POST.get("next", "")
    if cible and url_has_allowed_host_and_scheme(cible, allowed_hosts={request.get_host()}):
        return redirect(cible)
    return redirect(publication.get_absolute_url() if publication else reverse("community:fil"))


@login_required
def fil(request):
    qs = _publications_pour(request.user)
    recherche = request.GET.get("q", "").strip()
    if recherche:
        qs = qs.filter(
            Q(texte__icontains=recherche) | Q(auteur__username__icontains=recherche)
            | Q(auteur__first_name__icontains=recherche) | Q(auteur__last_name__icontains=recherche)
        ).distinct()
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "community/fil.html", {
        "page_obj": page, "publications": page.object_list, "recherche": recherche,
        "form_commentaire": CommentaireForm(),
    })


@login_required
def publier(request):
    form = PublicationForm(request.POST or None, request.FILES or None, utilisateur=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            publication = form.save(commit=False)
            publication.auteur = request.user
            publication.full_clean()
            publication.save()
            nouveaux = form.enregistrer_mentions(publication)
            _notifier_mentions(acteur=request.user, publication=publication, utilisateurs=nouveaux)
        messages.success(request, "Votre publication est en ligne.")
        return redirect(publication)
    return render(request, "community/form.html", {"form": form, "titre": "Nouvelle publication"})


@login_required
def detail(request, pk):
    publication = get_object_or_404(_publications_pour(request.user), pk=pk)
    return render(request, "community/detail.html", {
        "publication": publication, "form_commentaire": CommentaireForm(),
    })


@login_required
def modifier(request, pk):
    publication = get_object_or_404(Publication, pk=pk, auteur=request.user, publication_originale=None)
    ancien_fichier = publication.image.name if publication.image else ""
    form = PublicationForm(request.POST or None, request.FILES or None, instance=publication, utilisateur=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            publication = form.save()
            nouveaux = form.enregistrer_mentions(publication)
            _notifier_mentions(acteur=request.user, publication=publication, utilisateurs=nouveaux)
        if ancien_fichier and publication.image.name != ancien_fichier:
            publication.image.storage.delete(ancien_fichier)
        messages.success(request, "Publication mise à jour.")
        return redirect(publication)
    return render(request, "community/form.html", {"form": form, "titre": "Modifier la publication"})


@login_required
@require_POST
def supprimer(request, pk):
    publication = get_object_or_404(Publication, pk=pk)
    if publication.auteur_id != request.user.id and not request.user.has_perm("users.gerer_utilisateurs"):
        raise PermissionDenied
    fichier = publication.image.name if publication.image else ""
    stockage = publication.image.storage if publication.image else None
    publication.delete()
    if fichier and stockage:
        stockage.delete(fichier)
    messages.success(request, "Publication supprimée.")
    return _retour(request)


@login_required
@require_POST
def aimer(request, pk):
    publication = get_object_or_404(Publication, pk=pk, est_masquee=False)
    reaction, creee = Jaime.objects.get_or_create(publication=publication, utilisateur=request.user)
    if not creee:
        reaction.delete()
    return _retour(request, publication)


@login_required
@require_POST
def commenter(request, pk):
    publication = get_object_or_404(Publication, pk=pk, est_masquee=False)
    form = CommentaireForm(request.POST)
    if form.is_valid():
        commentaire = form.save(commit=False)
        commentaire.publication = publication
        commentaire.auteur = request.user
        commentaire.save()
        mentionnes = form.enregistrer_mentions(commentaire)
        _notifier_mentions(
            acteur=request.user, publication=publication,
            commentaire=commentaire, utilisateurs=mentionnes,
        )
        messages.success(request, "Commentaire ajouté.")
    else:
        messages.error(request, "Le commentaire est vide ou trop long.")
    return _retour(request, publication)


@login_required
@require_POST
def supprimer_commentaire(request, pk):
    commentaire = get_object_or_404(Commentaire.objects.select_related("publication"), pk=pk)
    if commentaire.auteur_id != request.user.id and not request.user.has_perm("users.gerer_utilisateurs"):
        raise PermissionDenied
    publication = commentaire.publication
    commentaire.delete()
    messages.success(request, "Commentaire supprimé.")
    return _retour(request, publication)


@login_required
@require_POST
def partager(request, pk):
    publication = get_object_or_404(Publication, pk=pk, est_masquee=False)
    originale = publication.publication_originale or publication
    if originale.auteur_id == request.user.id:
        messages.info(request, "Cette publication vous appartient déjà.")
        return _retour(request, originale)
    repartage, cree = Publication.objects.get_or_create(
        auteur=request.user, publication_originale=originale,
        defaults={"texte": request.POST.get("texte", "").strip()[:2200]},
    )
    messages.success(request, "Publication repartagée dans la communauté." if cree else "Vous avez déjà repartagé cette publication.")
    return _retour(request, repartage)


@login_required
def profil_membre(request, username):
    membre = get_object_or_404(User, username=username, is_active=True)
    qs = _publications_pour(request.user).filter(auteur=membre)
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(request, "community/profil.html", {
        "membre": membre, "page_obj": page, "publications": page.object_list,
        "form_commentaire": CommentaireForm(),
    })


@login_required
@require_GET
def rechercher_utilisateurs(request):
    terme = request.GET.get("q", "").strip().lstrip("@")[:50]
    utilisateurs = User.objects.filter(is_active=True).exclude(pk=request.user.pk)
    if terme:
        utilisateurs = utilisateurs.filter(
            Q(username__icontains=terme) | Q(first_name__icontains=terme) | Q(last_name__icontains=terme)
        )
    utilisateurs = utilisateurs.order_by("username")[:8]
    return JsonResponse({"resultats": [
        {
            "id": u.pk, "username": u.username,
            "nom": u.get_full_name() or u.username,
            "avatar": u.avatar.url if u.avatar else "",
        } for u in utilisateurs
    ]})


@login_required
def notifications(request):
    liste = NotificationCommunaute.objects.filter(destinataire=request.user).select_related(
        "acteur", "publication", "commentaire"
    )[:50]
    return render(request, "community/notifications.html", {"notifications": liste})


@login_required
@require_POST
def lire_notification(request, pk):
    notification = get_object_or_404(NotificationCommunaute, pk=pk, destinataire=request.user)
    if not notification.lue_le:
        notification.lue_le = timezone.now()
        notification.save(update_fields=["lue_le"])
    cible = f"{notification.publication.get_absolute_url()}#commentaire-{notification.commentaire_id}" if notification.commentaire_id else notification.publication.get_absolute_url()
    return redirect(cible)


@login_required
@require_POST
def tout_lire(request):
    NotificationCommunaute.objects.filter(destinataire=request.user, lue_le__isnull=True).update(lue_le=timezone.now())
    return redirect("community:notifications")


@login_required
@permission_required("users.gerer_utilisateurs", raise_exception=True)
def administration(request):
    recherche = request.GET.get("q", "").strip()
    publications = Publication.objects.select_related("auteur", "publication_originale").annotate(
        nb_jaimes=Count("jaimes", distinct=True), nb_commentaires=Count("commentaires", distinct=True)
    )
    commentaires = Commentaire.objects.select_related("auteur", "publication__auteur")
    if recherche:
        publications = publications.filter(Q(texte__icontains=recherche) | Q(auteur__username__icontains=recherche))
        commentaires = commentaires.filter(Q(contenu__icontains=recherche) | Q(auteur__username__icontains=recherche))
    return render(request, "community/administration.html", {
        "publications": publications.order_by("-creee_le")[:50],
        "commentaires_admin": commentaires.order_by("-cree_le")[:50],
        "recherche": recherche,
        "nb_publications": Publication.objects.count(),
        "nb_commentaires_total": Commentaire.objects.count(),
        "nb_masquees": Publication.objects.filter(est_masquee=True).count(),
    })


@login_required
@permission_required("users.gerer_utilisateurs", raise_exception=True)
@require_POST
def moderer_publication(request, pk):
    publication = get_object_or_404(Publication, pk=pk)
    publication.est_masquee = not publication.est_masquee
    publication.save(update_fields=["est_masquee"])
    messages.success(request, "Publication rendue visible." if not publication.est_masquee else "Publication masquée du fil.")
    return redirect("community:administration")
