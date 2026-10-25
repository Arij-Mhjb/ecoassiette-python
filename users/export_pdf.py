"""
Export RGPD (articles 15 et 20) au format PDF : un document lisible qui reprend toutes les données
personnelles de l'utilisateur (compte, profil, repas, conseils, connexions…).
"""
from datetime import date, datetime
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

VERT = colors.HexColor("#146c43")
VERT_FONCE = colors.HexColor("#0b3b2c")
VERT_CLAIR = colors.HexColor("#e8f3ec")
GRIS = colors.HexColor("#5b6b62")
LIGNE = colors.HexColor("#d5e0d9")

# Helvetica (police standard des PDF) ne connaît pas certains symboles : on les remplace.
_REMPLACEMENTS = {"₂": "2", "→": "->", "−": "-", "…": "...", "≈": "~", "✓": "oui", "✗": "non"}


def _t(valeur):
    if valeur is None or valeur == "":
        return "—"
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    if isinstance(valeur, (list, tuple)):
        return ", ".join(str(v) for v in valeur) or "—"
    if isinstance(valeur, datetime):
        return (timezone.localtime(valeur) if timezone.is_aware(valeur) else valeur).strftime("%d/%m/%Y %H:%M")
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    texte = str(valeur)
    for a, b in _REMPLACEMENTS.items():
        texte = texte.replace(a, b)
    return texte


def _styles():
    base = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle("titre", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20,
                                textColor=VERT_FONCE, alignment=TA_LEFT, spaceAfter=4),
        "sous": ParagraphStyle("sous", parent=base["Normal"], fontSize=9.5, textColor=GRIS, leading=13),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13,
                             textColor=VERT, spaceBefore=14, spaceAfter=6),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "cellb": ParagraphStyle("cellb", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11),
        "vide": ParagraphStyle("vide", parent=base["Normal"], fontSize=9, textColor=GRIS, fontName="Helvetica-Oblique"),
    }


def _p(texte, style):
    return Paragraph(escape(_t(texte)).replace("\n", "<br/>"), style)


def _table_cles(lignes, st):
    """Tableau à deux colonnes : libellé / valeur."""
    t = Table([[_p(k, st["cellb"]), _p(v, st["cell"])] for k, v in lignes], colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), VERT_CLAIR),
        ("GRID", (0, 0), (-1, -1), 0.4, LIGNE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _table_liste(entetes, lignes, largeurs, st):
    data = [[_p(h, st["cellb"]) for h in entetes]] + [[_p(c, st["cell"]) for c in l] for l in lignes]
    t = Table(data, colWidths=[w * cm for w in largeurs], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VERT_CLAIR),
        ("GRID", (0, 0), (-1, -1), 0.4, LIGNE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faf8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _section(titre, contenu, st, vide="Aucune donnée."):
    bloc = [Paragraph(escape(titre), st["h2"])]
    bloc.append(contenu if contenu is not None else Paragraph(vide, st["vide"]))
    return KeepTogether(bloc) if not isinstance(contenu, Table) or len(contenu._cellvalues) < 15 else bloc


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(2 * cm, 1.2 * cm, "EcoAssiette — Export de données personnelles (RGPD, articles 15 et 20). Document confidentiel.")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(VERT)
    canvas.setLineWidth(2)
    canvas.line(2 * cm, A4[1] - 1.3 * cm, A4[0] - 2 * cm, A4[1] - 1.3 * cm)
    canvas.restoreState()


def generer_pdf(u):
    """Renvoie le PDF (bytes) de toutes les données personnelles de l'utilisateur `u`."""
    st = _styles()
    p = u.profil
    h = []
    h.append(Paragraph("Mes données personnelles", st["titre"]))
    h.append(Paragraph(escape(f"{u.get_full_name() or u.username} (@{u.username}) · généré le "
                              f"{timezone.localtime():%d/%m/%Y à %H:%M}"), st["sous"]))
    h.append(Paragraph("Ce document contient toutes les données qu'EcoAssiette conserve à votre sujet "
                       "(droit d'accès, article 15 du RGPD). Les adresses IP sont volontairement tronquées.", st["sous"]))
    h.append(Spacer(1, 6))

    h.append(_section("Compte", _table_cles([
        ("Nom d'utilisateur", u.username), ("Prénom", u.first_name), ("Nom", u.last_name),
        ("E-mail", u.email), ("E-mail confirmé", u.email_verifie), ("Téléphone", u.telephone),
        ("Rôle", u.get_role_display()), ("Inscrit le", u.date_joined), ("Dernière connexion", u.last_login),
    ], st), st))

    h.append(_section("Profil alimentaire", _table_cles([
        ("Régime", p.get_regime_display()), ("Aliments aimés", p.liste_aimes), ("Aliments évités", p.liste_evites),
        ("Taille du foyer", p.taille_foyer), ("Niveau d'activité", p.get_niveau_activite_display()),
        ("Temps de cuisine", p.get_temps_cuisine_display()), ("Ville", p.ville),
        ("Objectif CO2 / semaine", f"{p.objectif_co2_hebdo} kg" if p.objectif_co2_hebdo else None),
        ("Empreinte estimée / semaine", f"{p.emission_estimee_hebdo} kg CO2e"),
        ("Partagé avec les nutritionnistes", p.profil_public),
    ], st), st))

    repas = list(u.repas.prefetch_related("elements").order_by("-date"))
    lignes = [(r.date, r.get_type_repas_display(),
               "\n".join(f"{e.aliment} ({e.quantite_g} g)" for e in r.elements.all()),
               f"{r.co2_kg} kg", r.note) for r in repas]
    h.append(_section(f"Repas ({len(repas)})",
                      _table_liste(["Date", "Type", "Aliments", "CO2", "Note"], lignes, [2.2, 2.3, 6.5, 2, 4], st)
                      if lignes else None, st, "Aucun repas enregistré."))

    lignes = [(r.cree_le, r.ancien_aliment, r.nouvel_aliment, f"{r.gain_kg} kg") for r in u.remplacements.all()]
    h.append(_section("Alternatives adoptées", _table_liste(["Date", "Avant", "Après", "CO2 évité"], lignes,
                                                            [3.2, 5, 5, 3.8], st) if lignes else None, st))

    lignes = [(a.cree_le, a.get_statut_display(), a.get_source_display()) for a in p.analyses.all()]
    h.append(_section("Analyses IA du profil", _table_liste(["Date", "Statut", "Moteur"], lignes, [4, 6.5, 6.5], st)
                      if lignes else None, st))

    lignes = [(r.cree_le, str(r.auteur) if r.auteur else None, r.get_theme_display(), f"{r.titre}\n{r.contenu}",
               r.get_avis_display() if r.avis else None) for r in u.recommandations_recues.select_related("auteur")]
    h.append(_section("Conseils reçus", _table_liste(["Date", "De", "Thème", "Conseil", "Avis"], lignes,
                                                     [2.6, 2.8, 2.4, 7, 2.2], st) if lignes else None, st))

    lignes = [(d.cree_le, d.numero_ordre, d.etablissement, d.get_statut_display()) for d in u.demandes_nutritionniste.all()]
    if lignes:
        h.append(_section("Demandes nutritionniste", _table_liste(["Date", "N° d'ordre", "Établissement", "Statut"],
                                                                  lignes, [3.2, 3.5, 6.5, 3.8], st), st))

    lignes = [(c.cree_le, "Réussie" if c.succes else "Échouée", c.navigateur, c.ip) for c in u.connexions.all()[:100]]
    h.append(_section("Historique des connexions (100 dernières)",
                      _table_liste(["Date", "Résultat", "Appareil", "IP (tronquée)"], lignes, [3.6, 3, 6, 4.4], st)
                      if lignes else None, st))

    tampon = BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title="Mes données — EcoAssiette", author="EcoAssiette")
    doc.build([x for bloc in h for x in (bloc if isinstance(bloc, list) else [bloc])],
              onFirstPage=_pied, onLaterPages=_pied)
    return tampon.getvalue()
