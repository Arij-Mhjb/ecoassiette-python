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
            "La génération IA n'est pas configurée. Ajoutez POLLINATIONS_API_KEY dans le fichier .env."
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
        response = requests.get(
            url,
            params={
                "model": settings.POLLINATIONS_IMAGE_MODEL,
                "width": 1024,
                "height": 1024,
                "safe": "true",
                "seed": secrets.randbelow(2_147_483_647),
            },
            headers={"Authorization": f"Bearer {cle}"},
            timeout=(10, settings.POLLINATIONS_TIMEOUT),
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise ErreurGenerationImage(
            "Le modèle IA met trop de temps à répondre. Réessayez dans un instant."
        ) from exc
    except requests.RequestException as exc:
        raise ErreurGenerationImage("Le service d'images IA est temporairement indisponible.") from exc

    content = response.content
    if not content or len(content) > TAILLE_MAX:
        raise ErreurGenerationImage("L'image générée est vide ou dépasse 8 Mo.")

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = (image.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise ErreurGenerationImage("Le service IA n'a pas renvoyé une image valide.") from exc

    extensions = {"jpeg": "jpg", "png": "png", "webp": "webp"}
    if image_format not in extensions:
        raise ErreurGenerationImage("Le format d'image généré n'est pas accepté.")

    supprimer_image_temporaire(ancien_token, utilisateur.pk)
    filename = f"{DOSSIER_IA}/u{utilisateur.pk}-{secrets.token_hex(12)}.{extensions[image_format]}"
    path = default_storage.save(filename, ContentFile(content))
    token = dumps({"uid": utilisateur.pk, "path": path}, salt=SIGNING_SALT, compress=True)
    return {
        "token": token,
        "url": default_storage.url(path),
        "modele": settings.POLLINATIONS_IMAGE_MODEL,
    }


def decoder_token_image(token, utilisateur_id, max_age=1800):
    try:
        data = loads(token, salt=SIGNING_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired) as exc:
        raise ErreurGenerationImage("L'image IA a expiré. Générez-la à nouveau.") from exc
    path = str(data.get("path", ""))
    if data.get("uid") != utilisateur_id or not path.startswith(f"{DOSSIER_IA}/"):
        raise ErreurGenerationImage("Cette image IA n'est pas valide pour votre compte.")
    if not default_storage.exists(path):
        raise ErreurGenerationImage("L'image IA n'est plus disponible. Générez-la à nouveau.")
    return path


def supprimer_image_temporaire(token, utilisateur_id):
    if not token:
        return
    try:
        path = decoder_token_image(token, utilisateur_id)
    except ErreurGenerationImage:
        return
    if Path(path).as_posix().startswith(f"{DOSSIER_IA}/"):
        default_storage.delete(path)
