"""Import contrôlé d'un produit végétal à partir de sa page officielle."""
import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from users.ai import ErreurIA, appeler_gemini


class ErreurImportProduit(Exception):
    pass


class _PageProduitParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.titre = ""
        self.textes = []
        self.json_ld = []
        self._dans_titre = False
        self._ignore = 0
        self._json = False
        self._tampon_json = []

    def handle_starttag(self, tag, attrs):
        attributs = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._ignore += 1
        if tag == "title":
            self._dans_titre = True
        if tag == "script" and attributs.get("type", "").casefold() == "application/ld+json":
            self._json = True
            self._tampon_json = []
        if tag == "meta":
            cle = attributs.get("property") or attributs.get("name")
            contenu = attributs.get("content")
            if cle and contenu:
                self.meta[cle.casefold()] = contenu.strip()

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_titre = False
        if tag == "script" and self._json:
            self._json = False
            try:
                self.json_ld.append(json.loads("".join(self._tampon_json)))
            except (TypeError, ValueError):
                pass
        if tag in {"script", "style", "noscript"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data):
        texte = " ".join(data.split())
        if self._json:
            self._tampon_json.append(data)
        elif self._dans_titre and texte:
            self.titre += texte
        elif not self._ignore and texte:
            self.textes.append(texte)


def _verifier_url_publique(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ErreurImportProduit("Utilisez une URL officielle commençant par http:// ou https://.")
    try:
        adresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ErreurImportProduit("Le domaine du produit est introuvable.") from exc
    for adresse in adresses:
        ip = ipaddress.ip_address(adresse)
        if not ip.is_global:
            raise ErreurImportProduit("Cette adresse réseau privée n'est pas autorisée.")


def telecharger_page_produit(url):
    url_courante = url
    for _ in range(4):
        _verifier_url_publique(url_courante)
        try:
            reponse = requests.get(
                url_courante,
                headers={"User-Agent": "EcoAssiette-ProductImporter/1.0"},
                timeout=15,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ErreurImportProduit("Impossible de lire la page du produit.") from exc
        if reponse.status_code in {301, 302, 303, 307, 308}:
            destination = reponse.headers.get("Location")
            if not destination:
                raise ErreurImportProduit("Redirection invalide sur la page du produit.")
            url_courante = urljoin(url_courante, destination)
            continue
        try:
            reponse.raise_for_status()
        except requests.HTTPError as exc:
            raise ErreurImportProduit(f"La page produit répond avec l'erreur HTTP {reponse.status_code}.") from exc
        type_contenu = reponse.headers.get("Content-Type", "")
        if "text/html" not in type_contenu:
            raise ErreurImportProduit("L'URL doit pointer vers une page web HTML.")
        contenu = b""
        for bloc in reponse.iter_content(65536):
            contenu += bloc
            if len(contenu) > 1_500_000:
                raise ErreurImportProduit("La page produit est trop volumineuse.")
        return contenu.decode(reponse.encoding or "utf-8", errors="replace"), url_courante
    raise ErreurImportProduit("La page effectue trop de redirections.")


def _trouver_product_json(objet):
    if isinstance(objet, list):
        for item in objet:
            trouve = _trouver_product_json(item)
            if trouve:
                return trouve
    if isinstance(objet, dict):
        type_objet = objet.get("@type", "")
        est_produit = type_objet == "Product" or (
            isinstance(type_objet, list) and "Product" in type_objet
        )
        if est_produit:
            return objet
        if "@graph" in objet:
            return _trouver_product_json(objet["@graph"])
    return None


def _prix_json(produit):
    offres = produit.get("offers", {}) if produit else {}
    if isinstance(offres, list):
        offres = offres[0] if offres else {}
    try:
        return float(offres.get("price") or offres.get("lowPrice") or 0)
    except (TypeError, ValueError):
        return 0


def _mots_cles_locaux(texte):
    texte = texte.casefold()
    correspondances = (
        (("ground beef", "minced beef", "viande hach", "haché", "hache"), "viande hachée"),
        (("beef", "bœuf", "boeuf"), "bœuf"),
        (("steak",), "steak"),
        (("burger",), "burger"),
        (("chicken", "poulet"), "poulet"),
        (("sausage", "saucisse"), "saucisse"),
        (("fish", "poisson"), "poisson"),
        (("cheese", "fromage"), "fromage"),
        (("milk", "lait"), "lait"),
    )
    mots = [libelle for variantes, libelle in correspondances if any(v in texte for v in variantes)]
    if "viande hachée" in mots:
        for suggestion in ("steak", "burger"):
            if suggestion not in mots:
                mots.append(suggestion)
    return mots[:8]


def analyser_url_produit(url):
    html, url_finale = telecharger_page_produit(url)
    parser = _PageProduitParser()
    parser.feed(html)
    produit_json = next((p for bloc in parser.json_ld if (p := _trouver_product_json(bloc))), None)
    titre = (produit_json or {}).get("name") or parser.meta.get("og:title") or parser.titre
    description = (
        (produit_json or {}).get("description") or parser.meta.get("og:description")
        or parser.meta.get("description") or ""
    )
    marque = (produit_json or {}).get("brand", "") or parser.meta.get("og:site_name", "")
    if isinstance(marque, dict):
        marque = marque.get("name", "")
    donnees_page = {
        "url": url_finale,
        "titre": str(titre)[:300],
        "description": str(description)[:2000],
        "marque": str(marque)[:150],
        "prix_detecte": _prix_json(produit_json),
        "texte_page": " ".join(parser.textes)[:12000],
    }
    prompt = (
        "Tu extrais un produit alimentaire végétal à partir du contenu réel d'une page officielle. "
        "N'invente aucune information absente. Réponds uniquement en JSON avec : "
        '"nom", "description" (maximum 700 caractères), "sponsor_nom", '
        '"prix_public" (nombre, 0 si absent), "produit_vegetal" (booléen), '
        '"mots_cles" (liste de 3 à 8 ingrédients animaux que ce produit peut remplacer). '
        f"Données extraites : {json.dumps(donnees_page, ensure_ascii=False)}"
    )
    try:
        resultat = appeler_gemini(prompt)
        source = "GEMINI"
    except ErreurIA:
        resultat = {}
        source = "PAGE"
    if not isinstance(resultat, dict):
        resultat = {}
    morceaux_titre = [m.strip() for m in str(donnees_page["titre"]).split("|") if m.strip()]
    nom_page = morceaux_titre[0] if morceaux_titre else donnees_page["titre"]
    marque_page = morceaux_titre[-1] if len(morceaux_titre) > 1 else ""
    nom = str(resultat.get("nom") or nom_page).strip()[:160]
    if not nom:
        raise ErreurImportProduit("Aucun nom de produit n'a pu être extrait de cette page.")
    description_finale = str(resultat.get("description") or description).strip()[:800]
    sponsor = str(
        resultat.get("sponsor_nom") or marque or marque_page or urlparse(url_finale).hostname
    ).strip()[:120]
    try:
        prix = max(0, float(resultat.get("prix_public") or donnees_page["prix_detecte"] or 0))
    except (TypeError, ValueError):
        prix = 0
    mots = resultat.get("mots_cles", [])
    if not isinstance(mots, list):
        mots = []
    if not mots:
        mots = _mots_cles_locaux(
            f"{donnees_page['titre']} {donnees_page['description']} {donnees_page['texte_page']}"
        )
    return {
        "nom": nom,
        "description": description_finale or "Description à vérifier.",
        "sponsor_nom": sponsor,
        "prix_public": prix,
        "produit_vegetal": bool(resultat.get("produit_vegetal", True)),
        "mots_cles_recommandation": ", ".join(str(m).strip() for m in mots if str(m).strip())[:300],
        "url_source": url_finale,
        "source": source,
    }
