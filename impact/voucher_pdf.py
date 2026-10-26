from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


VERT = HexColor("#176B4D")
VERT_FONCE = HexColor("#0B3B2C")
VERT_CLAIR = HexColor("#E8F5ED")
GRIS = HexColor("#52625C")


def generer_bon_pdf(commande, url_verification):
    """Retourne le PDF statique d'un bon sponsor sous forme d'octets."""
    tampon = BytesIO()
    largeur, hauteur = A4
    pdf = canvas.Canvas(tampon, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"Bon EcoAssiette {commande.code_bon}")
    pdf.setAuthor("EcoAssiette")

    pdf.setFillColor(VERT_FONCE)
    pdf.rect(0, hauteur - 135, largeur, 135, fill=1, stroke=0)
    pdf.setFillColor(white)
    pdf.setFont("Helvetica-Bold", 25)
    pdf.drawString(48, hauteur - 68, "EcoAssiette")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(48, hauteur - 94, "Bon de reduction partenaire")

    pdf.setFillColor(VERT_CLAIR)
    pdf.roundRect(42, hauteur - 360, largeur - 84, 185, 14, fill=1, stroke=0)
    pdf.setFillColor(VERT_FONCE)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(62, hauteur - 212, commande.produit.nom[:52])
    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(GRIS)
    pdf.drawString(62, hauteur - 238, f"Sponsor : {commande.produit.sponsor.nom}"[:75])
    pdf.drawString(62, hauteur - 260, f"Remise : {commande.produit.remise_pourcent} %")
    pdf.drawString(62, hauteur - 282, f"Prix avec remise : {commande.prix_remise:.2f} EUR")
    pdf.drawString(62, hauteur - 304, f"Points utilises : {commande.points_utilises}")
    pdf.setFillColor(VERT)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(62, hauteur - 335, commande.code_bon)

    qr = QrCodeWidget(url_verification)
    limites = qr.getBounds()
    taille = 128
    dessin = Drawing(taille, taille, transform=[
        taille / (limites[2] - limites[0]), 0, 0,
        taille / (limites[3] - limites[1]), 0, 0,
    ])
    dessin.add(qr)
    renderPDF.draw(dessin, pdf, largeur - 190, hauteur - 350)

    pdf.setFillColor(VERT_FONCE)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(48, hauteur - 410, "Comment utiliser ce bon")
    pdf.setFillColor(GRIS)
    pdf.setFont("Helvetica", 10.5)
    lignes = [
        "1. Presentez ce PDF ou le QR code au sponsor.",
        "2. Le sponsor verifie le code et applique la remise indiquee.",
        "3. Le bon est personnel et utilisable une seule fois.",
        "4. Une piece d'identite peut etre demandee par le partenaire.",
    ]
    y = hauteur - 438
    for ligne in lignes:
        pdf.drawString(55, y, ligne)
        y -= 22

    pdf.setStrokeColor(HexColor("#D7E5DC"))
    pdf.line(48, 145, largeur - 48, 145)
    pdf.setFillColor(GRIS)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(48, 124, f"Bon emis le {commande.creee_le:%d/%m/%Y} - Commande #{commande.pk}")
    pdf.drawString(48, 108, "Verification en ligne : " + url_verification[:82])
    pdf.drawRightString(largeur - 48, 62, "EcoAssiette - alimentation durable")
    pdf.showPage()
    pdf.save()
    return tampon.getvalue()
