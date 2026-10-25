import json
import logging

from django.conf import settings

from django.contrib import messages
from users.models import JournalAudit
from users.permissions import CitoyenRequisMixin, PermissionOu403Mixin, citoyen_requis
from users.securite import journaliser
from django.db import transaction
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView


from . import tasks as taches
from .bilan import bilan_semaine  # noqa: F401  (réexporté : utilisé par les tests)
from .categories import donnees_js, remplacement_pour
from .forms import ElementRepasFormSet, RepasForm
from .models import FACTEURS_CO2, AnalyseRepasIA, ElementRepas, EvaluationIA, Remplacement, Repas

logger = logging.getLogger(__name__)


class MesRepasMixin(CitoyenRequisMixin):
    """Chaque utilisateur ne voit QUE ses propres repas."""

    def get_queryset(self):
        return Repas.objects.filter(utilisateur=self.request.user).prefetch_related("elements")


# ------------------------------------------------------------------ READ
class RepasListView(MesRepasMixin, ListView):
    template_name = "repas/liste.html"
    context_object_name = "repas_list"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            nb_aliments=Count("elements"),
            total_g=Sum("elements__quantite_g"),
        ).order_by("-date", "-cree_le")
        type_choisi = self.request.GET.get("type")
        if type_choisi in Repas.TypeRepas.values:
            qs = qs.filter(type_repas=type_choisi)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["types"] = Repas.TypeRepas.choices
        ctx["type_actif"] = self.request.GET.get("type", "")
        ctx["bilan"] = bilan_semaine(self.request.user)
        return ctx


class RepasDetailView(MesRepasMixin, DetailView):
    template_name = "repas/detail.html"
    context_object_name = "repas"

    def get_context_data(self, **kwargs):
        from impact.services import analyser_repas

        ctx = super().get_context_data(**kwargs)
        ctx["lignes"] = [(e, suggestion_pour(e)) for e in self.object.elements.all()]
        ctx["a_suggestions"] = any(s for _, s in ctx["lignes"])
        ctx["analyse_impact"] = analyser_repas(self.object, self.request.user)
        ctx["analyse_impact"]["adoptees"] = set(
            self.object.alternatives_adoptees.filter(utilisateur=self.request.user)
            .values_list("alternative_id", flat=True)
        )
        return ctx


def suggestion_pour(element):
    """Simulateur « Et si… » : alternative végétale et CO2 évité pour un élément du repas."""
    alt = remplacement_pour(element.aliment, element.categorie)
    if not alt:
        return None
    nom, categorie, idee = alt
    apres = round(element.quantite_g / 1000 * FACTEURS_CO2[categorie], 2)
    gain = round(element.co2_kg - apres, 2)
    if gain < 0.2:
        return None
    return {"nom": nom, "categorie": categorie, "idee": idee, "apres": apres, "gain": gain,
            # si ce remplacement est fait une fois par semaine
            "gain_mois": round(gain * 52 / 12, 1), "gain_an": round(gain * 52)}


@citoyen_requis
@require_POST
def remplacer(request, pk, element_pk):
    element = get_object_or_404(ElementRepas, pk=element_pk, repas__pk=pk, repas__utilisateur=request.user)
    s = suggestion_pour(element)
    if not s:
        messages.info(request, "Cet aliment est déjà peu émetteur.")
        return redirect("repas:detail", pk=pk)
    ancien = element.aliment
    with transaction.atomic():
        element.aliment, element.categorie = s["nom"], s["categorie"]
        element.save(update_fields=["aliment", "categorie"])
        Remplacement.objects.create(utilisateur=request.user, repas=element.repas, ancien_aliment=ancien,
                                    nouvel_aliment=s["nom"], gain_kg=s["gain"])
    journaliser(request, JournalAudit.Action.ALIMENT_REMPLACE, cible=f"repas n° {pk}",
                details=f"{ancien} → {s['nom']} (−{s['gain']} kg CO₂e)")
    nb = Remplacement.objects.filter(utilisateur=request.user).count()
    extra = " Badge débloqué : Premier pas !" if nb == 1 else (" Badge débloqué : Éco-cuisinier !" if nb == 5 else "")
    messages.success(request, f"« {ancien} » → « {s['nom']} » : −{s['gain']} kg CO₂e.{extra}")
    return redirect("repas:detail", pk=pk)


# ------------------------------------------------------- IA : photo et texte / voix
TYPES_IMAGES = {"image/jpeg", "image/png", "image/webp"}
TAILLE_MAX_PHOTO = 8 * 1024 * 1024
TYPES_AUDIO = {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4"}
TAILLE_MAX_AUDIO = 5 * 1024 * 1024


def _etat(a):
    """JSON renvoyé au navigateur pour une analyse (en cours ou terminée)."""
    if not a.est_terminee:
        return {"id": a.pk, "termine": False, "statut": a.statut,
                "url_etat": reverse("repas:ia_etat", args=[a.pk])}
    if a.statut == a.Statut.ECHEC:
        return {"id": a.pk, "termine": True, "statut": a.statut, "erreur": a.message}
    return {"id": a.pk, "termine": True, "statut": a.statut, **a.resultat}


def _reponse(a):
    """202 si l'analyse tourne en arrière-plan ; sinon le résultat final (mode synchrone)."""
    if not a.est_terminee:
        return JsonResponse(_etat(a), status=202)
    if a.statut == a.Statut.ECHEC:
        return JsonResponse(_etat(a), status=422 if a.mode == a.Mode.TEXTE else 503)
    return JsonResponse(_etat(a))


@citoyen_requis
@require_POST
def ia_photo(request):
    photo = request.FILES.get("photo")
    if not photo:
        return JsonResponse({"erreur": "Aucune photo reçue."}, status=400)
    if photo.content_type not in TYPES_IMAGES:
        return JsonResponse({"erreur": "Format non supporté : utilisez une photo JPEG, PNG ou WebP."}, status=400)
    if photo.size > TAILLE_MAX_PHOTO:
        return JsonResponse({"erreur": "Photo trop lourde (8 Mo maximum)."}, status=400)
    return _reponse(taches.lancer(request.user, AnalyseRepasIA.Mode.PHOTO, donnees=photo.read(), mime=photo.content_type))


@citoyen_requis
@require_POST
def ia_audio(request):
    """Dictée : l'enregistrement est analysé par Gemini (transcription + aliments)."""
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"erreur": "Aucun enregistrement reçu."}, status=400)
    mime = (audio.content_type or "").split(";")[0].strip()
    if mime not in TYPES_AUDIO:
        return JsonResponse({"erreur": "Format audio non supporté."}, status=400)
    if audio.size > TAILLE_MAX_AUDIO:
        return JsonResponse({"erreur": "Enregistrement trop long (30 secondes maximum)."}, status=400)
    langue = request.POST.get("langue", "") if request.POST.get("langue") in ("ar-TN", "fr-FR") else ""
    return _reponse(taches.lancer(request.user, AnalyseRepasIA.Mode.AUDIO, texte=langue, donnees=audio.read(),
                                  mime="audio/wav" if mime in ("audio/x-wav", "audio/wave") else mime))


@citoyen_requis
@require_POST
def ia_texte(request):
    try:
        texte = str(json.loads(request.body or b"{}").get("texte", "")).strip()
    except (ValueError, AttributeError):
        texte = ""
    if not texte:
        return JsonResponse({"erreur": "Décrivez votre repas (ex. « couscous à l'agneau et salade »)."}, status=400)
    if len(texte) > 500:
        return JsonResponse({"erreur": "Description trop longue (500 caractères maximum)."}, status=400)
    return _reponse(taches.lancer(request.user, AnalyseRepasIA.Mode.TEXTE, texte=texte))


@citoyen_requis
def ia_etat(request, pk):
    """Suivi d'une analyse (polling) : uniquement ses propres analyses."""
    return JsonResponse(_etat(get_object_or_404(AnalyseRepasIA, pk=pk, utilisateur=request.user)))


# ---------------------------------------------------- CREATE + UPDATE
class RepasFormMixin:
    """Gère le formulaire Repas + le formset des aliments ensemble."""
    form_class = RepasForm
    template_name = "repas/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "formset" not in kwargs:
            ctx["formset"] = ElementRepasFormSet(instance=self.object)
        ctx["aide_categories"] = donnees_js()
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if self.est_modification else None
        form = self.get_form()
        formset = ElementRepasFormSet(request.POST, instance=form.instance)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                if not self.est_modification:
                    form.instance.utilisateur = request.user
                self.object = form.save()
                formset.instance = self.object
                formset.save()
            journaliser(request, JournalAudit.Action.REPAS_MODIFIE if self.est_modification else JournalAudit.Action.REPAS_AJOUTE,
                        cible=f"repas n° {self.object.pk}",
                        details=f"{self.object} · {self.object.elements.count()} aliment(s)")
            messages.success(request, self.message_succes)
            return redirect("repas:detail", pk=self.object.pk)
        messages.error(request, "Le formulaire contient des erreurs.")
        return self.render_to_response(self.get_context_data(form=form, formset=formset))


class RepasCreateView(CitoyenRequisMixin, RepasFormMixin, CreateView):
    est_modification = False
    message_succes = "Repas ajouté."
    extra_context = {"titre": "Ajouter un repas"}


class RepasUpdateView(MesRepasMixin, RepasFormMixin, UpdateView):
    est_modification = True
    message_succes = "Repas modifié."
    extra_context = {"titre": "Modifier le repas"}


# ---------------------------------------------------------------- DELETE
class RepasDeleteView(MesRepasMixin, DeleteView):
    template_name = "repas/supprimer.html"
    context_object_name = "repas"
    success_url = reverse_lazy("repas:liste")

    def form_valid(self, form):
        journaliser(self.request, JournalAudit.Action.REPAS_SUPPRIME, cible=f"repas n° {self.object.pk}",
                    details=str(self.object))
        messages.success(self.request, "Repas supprimé.")
        return super().form_valid(form)


# ================================================================ laboratoire IA (administration)
def _duree(ms):
    if ms is None:
        return "—"
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s".replace(".", ",")


def _vue_moteur(ev):
    """Prépare l'affichage d'une évaluation : matrice de confusion colorée, barres par catégorie."""
    m = ev.metriques
    noms = dict(ElementRepas.Categorie.choices)
    conf = m["categories"]["confusion"]
    maxi = max([max(l.values()) for l in conf.values()] + [1])
    lignes = [{"label": noms.get(a, a), "cellules": [
        {"n": conf[a][p], "intensite": round(conf[a][p] / maxi, 2), "diag": a == p, "label": noms.get(p, p)}
        for p in conf]} for a in conf if sum(conf[a].values())]
    par_cat = [{"label": noms.get(c, c), **v, "pct": round(v["f1"] * 100)}
               for c, v in m["categories"]["par_categorie"].items() if v["support"]]
    courts = {"VIANDE_ROUGE": "Viande", "VOLAILLE": "Volaille", "POISSON": "Poisson", "LAITIER": "Laitiers",
              "LEGUMINEUSE": "Légum.", "FECULENT": "Féculents", "FRUIT_LEGUME": "Fruits/lég."}
    colonnes = [{"court": courts.get(c, c), "label": noms.get(c, c)} for c in conf]
    return {"ev": ev, "m": m, "colonnes": colonnes, "lignes": lignes, "par_cat": par_cat,
            "p50": _duree(m["latence_ms"]["p50"]), "p95": _duree(m["latence_ms"]["p95"])}


def _usage_reel():
    """Statistiques des vraies demandes « Remplir avec l'IA » des citoyens."""
    from repas.evaluation.metriques import centile
    qs = AnalyseRepasIA.objects.all()
    total = qs.count()
    if not total:
        return None
    ok = qs.filter(statut=AnalyseRepasIA.Statut.TERMINE)
    modes = []
    for code, label in AnalyseRepasIA.Mode.choices:
        durees = list(qs.filter(mode=code, duree_ms__isnull=False).values_list("duree_ms", flat=True))
        n = qs.filter(mode=code).count()
        if n:
            modes.append({"label": label, "n": n, "succes": round(100 * qs.filter(mode=code, statut="TERMINE").count() / n),
                          "p50": _duree(centile(durees, 50)), "p95": _duree(centile(durees, 95))})
    nb_ok = ok.count()
    return {"total": total, "succes": round(100 * nb_ok / total), "modes": modes,
            "part_gemini": round(100 * ok.filter(source="GEMINI").count() / nb_ok) if nb_ok else 0,
            "part_local": round(100 * ok.filter(source="LOCAL").count() / nb_ok) if nb_ok else 0}


class LaboIAView(PermissionOu403Mixin, TemplateView):
    """Évaluation chiffrée de l'IA du module repas : précision, rappel, F1, matrice de confusion, latences."""
    permission_required = "users.voir_statistiques"
    template_name = "repas/labo.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        # une évaluation interrompue (redémarrage du serveur) ne reste pas « en cours » indéfiniment
        EvaluationIA.objects.filter(statut=EvaluationIA.Statut.EN_COURS,
                                    cree_le__lt=timezone.now() - timezone.timedelta(minutes=30)) \
            .update(statut=EvaluationIA.Statut.ECHEC, erreur="Interrompue (serveur redémarré ?)")
        vues = {}
        for code, _ in EvaluationIA.Moteur.choices:
            ev = EvaluationIA.objects.filter(moteur=code, statut=EvaluationIA.Statut.TERMINE).first()
            if ev:
                vues[code] = _vue_moteur(ev)
        comparaison = None
        if "LOCAL" in vues and "GEMINI" in vues:
            l, g = vues["LOCAL"]["m"], vues["GEMINI"]["m"]
            comparaison = {
                "delta_rappel": round((g["detection"]["rappel"] - l["detection"]["rappel"]) * 100),
                "delta_f1": round((g["bout_en_bout"]["f1"] - l["bout_en_bout"]["f1"]) * 100),
                "facteur_temps": round((g["latence_ms"]["p50"] or 0) / max(l["latence_ms"]["p50"] or 1, 1)),
            }
        from repas.evaluation.metriques import charger_jeu
        from users.ai import modeles_gemini
        ctx["diagnostic"] = {     # la clé elle-même n'est jamais affichée
            "cle": bool(settings.GEMINI_API_KEY), "longueur_cle": len(settings.GEMINI_API_KEY or ""),
            "modeles": modeles_gemini(),
            "erreurs": AnalyseRepasIA.objects.exclude(erreur="").order_by("-cree_le")[:5],
        }
        ctx.update(
            vues=vues, local=vues.get("LOCAL"), gemini=vues.get("GEMINI"), comparaison=comparaison,
            en_cours=EvaluationIA.objects.filter(statut=EvaluationIA.Statut.EN_COURS).first(),
            historique=EvaluationIA.objects.select_related("lance_par")[:8],
            usage=_usage_reel(), nb_phrases_jeu=len(charger_jeu()),
            cle_gemini=bool(settings.GEMINI_API_KEY), limite_gemini=settings.LABO_LIMITE_GEMINI,
        )
        return ctx

    def post(self, request, *args, **kwargs):
        moteur = request.POST.get("moteur")
        if moteur not in EvaluationIA.Moteur.values:
            return redirect("repas:labo")
        if EvaluationIA.objects.filter(statut=EvaluationIA.Statut.EN_COURS).exists():
            messages.info(request, "Une évaluation est déjà en cours : attendez qu'elle se termine.")
        elif moteur == EvaluationIA.Moteur.GEMINI and not settings.GEMINI_API_KEY:
            messages.error(request, "Clé GEMINI_API_KEY absente : impossible d'évaluer Gemini.")
        else:
            limite = settings.LABO_LIMITE_GEMINI if moteur == EvaluationIA.Moteur.GEMINI else None
            ev = taches.lancer_evaluation(moteur, request.user, limite)
            messages.success(request, "Évaluation terminée." if ev.statut != EvaluationIA.Statut.EN_COURS
                             else "Évaluation de Gemini lancée en arrière-plan : la page se met à jour toute seule.")
        return redirect("repas:labo")
