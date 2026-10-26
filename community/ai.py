import io
import secrets
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, dumps, loads

SIGNING_SALT = "community.image-ia"
DOSSIER_IA = "community/ai"
TAILLE_MAX = 8 * 1024 * 1024


class ErreurGenerationImage(Exception):
    pass


def generer_image(texte, utilisateur, ancien_token=""):
    cle = settings.POLLINATIONS_API_KEY.strip()
    if not cle:
        raise ErreurGenerationImage(
            "La génération IA n'est pas encore configurée. Ajoutez POLLINATIONS_API_KEY dans le fichier .env."
        )
    description = " ".join((texte or "").split())[:800]
    if len(description) < 8:
        raise ErreurGenerationImage("Décrivez davantage votre publication avant de générer une image.")

    prompt = (
        "Professional square social media photograph about sustainable food and community, "
        "natural light, realistic, appetizing, inclusive, ecological, no text, no logo. "
        f"Post context: {description}"
    )
    url = f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}"
    try:
        reponse = requests.get(
            url,
            params={
                "model": settings.POLLINATIONS_IMAGE_MODEL,
                "width": 1024, "height": 1024, "safe": "true",
                "seed": secrets.randbelow(2_147_483_647),
            },
            headers={"Authorization": f"Bearer {cle}"},
            timeout=(10, settings.POLLINATIONS_TIMEOUT),
        )
        reponse.raise_for_status()
    except requests.Timeout as exc:
        raise ErreurGenerationImage("Le modèle IA met trop de temps à répondre. Réessayez dans un instant.") from exc
    except requests.RequestException as exc:
        raise ErreurGenerationImage("Le service d'images IA est temporairement indisponible.") from exc

    contenu = reponse.content
    if not contenu or len(contenu) > TAILLE_MAX:
        raise ErreurGenerationImage("L'image générée est vide ou dépasse 8 Mo.")
    try:
        with Image.open(io.BytesIO(contenu)) as image:
            image.verify()
            format_image = (image.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise ErreurGenerationImage("Le service IA n'a pas renvoyé une image valide.") from exc
    extensions = {"jpeg": "jpg", "png": "png", "webp": "webp"}
    if format_image not in extensions:
        raise ErreurGenerationImage("Le format d'image généré n'est pas accepté.")

    supprimer_image_temporaire(ancien_token, utilisateur.pk)
    nom = f"{DOSSIER_IA}/u{utilisateur.pk}-{secrets.token_hex(12)}.{extensions[format_image]}"
    chemin = default_storage.save(nom, ContentFile(contenu))
    token = dumps({"uid": utilisateur.pk, "path": chemin}, salt=SIGNING_SALT, compress=True)
    return {"token": token, "url": default_storage.url(chemin), "modele": settings.POLLINATIONS_IMAGE_MODEL}


def decoder_token_image(token, utilisateur_id, max_age=1800):
    try:
        donnees = loads(token, salt=SIGNING_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired) as exc:
        raise ErreurGenerationImage("L'image IA a expiré. Générez-la à nouveau.") from exc
    chemin = str(donnees.get("path", ""))
    if donnees.get("uid") != utilisateur_id or not chemin.startswith(f"{DOSSIER_IA}/"):
        raise ErreurGenerationImage("Cette image IA n'est pas valide pour votre compte.")
    if not default_storage.exists(chemin):
        raise ErreurGenerationImage("L'image IA n'est plus disponible. Générez-la à nouveau.")
    return chemin


def supprimer_image_temporaire(token, utilisateur_id):
    if not token:
        return
    try:
        chemin = decoder_token_image(token, utilisateur_id)
    except ErreurGenerationImage:
        return
    if Path(chemin).as_posix().startswith(f"{DOSSIER_IA}/"):
        default_storage.delete(chemin)
