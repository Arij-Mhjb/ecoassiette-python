"""
python manage.py tester_gemini [--modele NOM]
Diagnostic de l'API Gemini en 2 étapes (la clé n'est jamais affichée) :
  1. GET /models   : la clé est-elle valide ? quels modèles sont disponibles ?
  2. generateContent sur le modèle choisi : temps de réponse.
"""
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

BASE = "https://generativelanguage.googleapis.com/v1beta"


class Command(BaseCommand):
    help = "Teste la clé et le modèle Gemini et mesure le temps de réponse."

    def add_arguments(self, parser):
        parser.add_argument("--modele", help="Modèle à tester (par défaut : GEMINI_MODEL)")

    def handle(self, *args, **opts):
        cle = settings.GEMINI_API_KEY
        modele = opts.get("modele") or settings.GEMINI_MODEL
        if not cle:
            self.stdout.write(self.style.ERROR("GEMINI_API_KEY absente du fichier .env"))
            return
        self.stdout.write(f"Clé : {cle[:4]}… ({len(cle)} caractères)")
        entetes = {"x-goog-api-key": cle, "Content-Type": "application/json"}

        # 1) liste des modèles (réponse rapide attendue)
        self.stdout.write("\n[1] Liste des modèles…")
        t0 = time.perf_counter()
        try:
            r = requests.get(f"{BASE}/models", headers=entetes, timeout=20, params={"pageSize": 200})
            self.stdout.write(f"    HTTP {r.status_code} en {time.perf_counter() - t0:.1f} s")
            if r.ok:
                noms = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                        if "generateContent" in m.get("supportedGenerationMethods", [])]
                flash = [n for n in noms if "flash" in n]
                self.stdout.write(self.style.SUCCESS(f"    Clé valide. Modèles Flash : {', '.join(flash[:12]) or '(aucun)'}"))
            else:
                self.stdout.write(self.style.ERROR(f"    {r.text[:400]}"))
                return
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"    Erreur réseau : {e.__class__.__name__}"))
            return

        # 2) génération
        self.stdout.write(f"\n[2] Génération avec « {modele} » (max 60 s)…")
        t0 = time.perf_counter()
        try:
            r = requests.post(f"{BASE}/models/{modele}:generateContent", headers=entetes, timeout=60,
                              json={"contents": [{"parts": [{"text": "Réponds seulement : OK"}]}]})
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"    Erreur après {time.perf_counter() - t0:.1f} s : {e.__class__.__name__}"))
            return
        self.stdout.write(f"    HTTP {r.status_code} en {time.perf_counter() - t0:.1f} s")
        if r.ok:
            try:
                texte = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError):
                texte = r.text[:200]
            self.stdout.write(self.style.SUCCESS(f"    Réponse : {texte.strip()[:100]}"))
        else:
            self.stdout.write(self.style.ERROR(f"    {r.text[:400]}"))
