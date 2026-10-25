"""
Backend e-mail via l'API HTTPS de Brevo (https://developers.brevo.com).

Render (offre gratuite) bloque les ports SMTP 25/465/587 : on envoie donc les
e-mails par HTTPS. L'adresse de DEFAULT_FROM_EMAIL doit être un expéditeur
vérifié dans Brevo.
"""
import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        envoyes = 0
        for msg in email_messages:
            nom, adresse = parseaddr(msg.from_email or settings.DEFAULT_FROM_EMAIL)
            payload = {
                "sender": {"email": adresse, "name": nom or "EcoAssiette"},
                "to": [{"email": parseaddr(d)[1]} for d in msg.to],
                "subject": msg.subject,
                "textContent": msg.body,
            }
            for contenu, mime in getattr(msg, "alternatives", []):
                if mime == "text/html":
                    payload["htmlContent"] = contenu
            try:
                r = requests.post(
                    BREVO_URL, json=payload, timeout=15,
                    headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
                )
                if r.status_code >= 400:
                    # Brevo explique la cause dans le corps de la réponse (clé invalide, IP non autorisée,
                    # expéditeur non vérifié, compte non activé…) : on la journalise pour les logs Render.
                    raise requests.HTTPError(f"{r.status_code} — {r.text[:300]}", response=r)
                envoyes += 1
            except requests.RequestException as e:
                logger.error("Échec d'envoi Brevo (expéditeur %s) : %s", adresse, e)
                if not self.fail_silently:
                    raise
        return envoyes
