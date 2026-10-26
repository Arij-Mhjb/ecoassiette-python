import io
import secrets
import threading
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.signing import BadSignature, SignatureExpired, dumps, loads

SIGNING_SALT = "community.image-ia"
DOSSIER_IA = "community/ai"
TAILLE_MAX = 8 * 1024 * 1024
_VERROU_GENERATION = threading.Lock()


class ErreurGenerationImage(Exception):
    pass


@lru_cache(maxsize=1)
def charger_modele_local():
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except ImportError as exc:
        raise ErreurGenerationImage(
            "Le moteur IA local n'est pas installé. Exécutez : pip install -r requirements-ai-local.txt"
        ) from exc

    appareil = settings.LOCAL_IMAGE_DEVICE.lower()
    if appareil == "auto":
        appareil = "cuda" if torch.cuda.is_available() else "cpu"
    if appareil == "cuda" and not torch.cuda.is_available():
        raise ErreurGenerationImage("CUDA est demandé, mais aucun GPU NVIDIA compatible n'est disponible.")

    dtype = torch.float16 if appareil == "cuda" else torch.float32
    try:
        pipeline = AutoPipelineForText2Image.from_pretrained(
            settings.LOCAL_IMAGE_MODEL,
            torch_dtype=dtype,
            use_safetensors=True,
            local_files_only=settings.LOCAL_IMAGE_OFFLINE,
        )
        pipeline.enable_attention_slicing()
        if appareil == "cuda" and torch.cuda.get_device_properties(0).total_memory < 6 * 1024**3:
            pipeline.enable_model_cpu_offload()
            appareil_generation = "cuda"
        else:
            pipeline.to(appareil)
            appareil_generation = appareil
    except Exception as exc:
        mode = "hors ligne" if settings.LOCAL_IMAGE_OFFLINE else "local"
        raise ErreurGenerationImage(
            f"Impossible de charger le modèle IA {mode}. Lancez d'abord : python manage.py prepare_image_model"
        ) from exc
    return pipeline, torch, appareil_generation


def _generer_avec_modele(prompt):
    pipeline, torch, appareil = charger_modele_local()
    seed = secrets.randbelow(2_147_483_647)
    generateur = torch.Generator(device="cpu").manual_seed(seed)
    try:
        with _VERROU_GENERATION, torch.inference_mode():
            image = pipeline(
                prompt=prompt,
                num_inference_steps=settings.LOCAL_IMAGE_STEPS,
                guidance_scale=0.0,
                width=settings.LOCAL_IMAGE_SIZE,
                height=settings.LOCAL_IMAGE_SIZE,
                generator=generateur,
            ).images[0]
    except Exception as exc:
        raise ErreurGenerationImage("La génération locale a échoué. Vérifiez la mémoire disponible.") from exc
    return image, settings.LOCAL_IMAGE_MODEL


def generer_image(texte, utilisateur, ancien_token=""):
    description = " ".join((texte or "").split())[:800]
    if len(description) < 8:
        raise ErreurGenerationImage("Décrivez davantage votre publication avant de générer une image.")
    prompt = (
        "Professional square social media photograph about sustainable food and community, "
        "natural light, realistic, appetizing, inclusive, ecological, no text, no logo. "
        f"Post context: {description}"
    )
    image, modele = _generer_avec_modele(prompt)
    sortie = io.BytesIO()
    image.convert("RGB").save(sortie, format="JPEG", quality=90, optimize=True)
    contenu = sortie.getvalue()
    if not contenu or len(contenu) > TAILLE_MAX:
        raise ErreurGenerationImage("L'image générée est vide ou dépasse 8 Mo.")

    supprimer_image_temporaire(ancien_token, utilisateur.pk)
    nom = f"{DOSSIER_IA}/u{utilisateur.pk}-{secrets.token_hex(12)}.jpg"
    chemin = default_storage.save(nom, ContentFile(contenu))
    token = dumps({"uid": utilisateur.pk, "path": chemin}, salt=SIGNING_SALT, compress=True)
    return {"token": token, "url": default_storage.url(chemin), "modele": modele}


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
