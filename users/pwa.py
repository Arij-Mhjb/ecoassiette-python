"""Application installable (PWA) : service worker servi à la racine du site et page « hors ligne »."""
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

SW = Path(settings.BASE_DIR) / "static" / "js" / "sw.js"


@require_GET
@cache_control(no_cache=True, max_age=0)
def service_worker(request):
    # servi depuis « /sw.js » (et non /static/) pour contrôler tout le site (portée « / »)
    reponse = HttpResponse(SW.read_text(encoding="utf-8"), content_type="application/javascript")
    reponse["Service-Worker-Allowed"] = "/"
    return reponse


@require_GET
def hors_ligne(request):
    return render(request, "hors_ligne.html")
