"""python manage.py tester_gemini — diagnostic de la connexion à l'API Gemini (sans afficher la clé)."""
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from users.ai import GEMINI_URL


class Command(BaseCommand):
    help = "Teste la clé et le modèle Gemini configurés et mesure le temps de réponse."

    def handle(self, *args, **opts):
        cle = settings.GEMINI_API_KEY
        self.stdout.write(f"Modèle : {settings.GEMINI_MODEL} | timeout : {settings.GEMINI_TIMEOUT} s")
        if not cle:
            self.stdout.write(self.style.ERROR("GEMINI_API_KEY absente du fichier .env"))
            return
        self.stdout.write(f"Clé : {cle[:4]}… ({len(cle)} caractères)")
        t0 = time.perf_counter()
        try:
            r = requests.post(
                GEMINI_URL.format(model=settings.GEMINI_MODEL),
                headers={"x-goog-api-key": cle, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": "Réponds seulement : OK"}]}]},
                timeout=90,
            )
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Erreur réseau après {time.perf_counter() - t0:.1f} s : {e.__class__.__name__}: {e}"))
            return
        duree = time.perf_counter() - t0
        self.stdout.write(f"HTTP {r.status_code} en {duree:.1f} s")
        if r.ok:
            try:
                texte = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError):
                texte = r.text[:200]
            self.stdout.write(self.style.SUCCESS(f"Réponse : {texte.strip()[:100]}"))
        else:
            self.stdout.write(self.style.ERROR(r.text[:500]))
