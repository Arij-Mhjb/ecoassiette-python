# EcoAssiette — Module « Utilisateurs & profils »

Plateforme qui aide les citoyens à suivre et réduire l'empreinte carbone de leur alimentation.
Ce dépôt contient le **module Utilisateurs & profils** (app Django `users`) : authentification,
rôles, profil alimentaire, analyse IA du profil, gestion des comptes (CRUD), API REST.

- Django 5.2 · DRF · PostgreSQL (Render) / SQLite (local) · WhiteNoise · Celery (optionnel)
- **117 tests**, couverture **97 %** · **0 violation axe-core** (WCAG 2 A/AA) sur toutes les pages

---

## 1. Installation locale

```bash
python -m venv venv
venv\Scripts\activate            # Windows   |   source venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
copy .env.example .env           # puis mettre DEBUG=True et (optionnel) GEMINI_API_KEY
python manage.py migrate         # crée aussi les groupes Citoyen / Nutritionniste / Administrateur
python manage.py seed_demo       # comptes de démonstration
python manage.py runserver
```

| Compte        | Rôle            | Mot de passe   |
|---------------|-----------------|----------------|
| `admin_eco`   | Administrateur  | `EcoDemo2026!` |
| `nutri_sarra` | Nutritionniste  | `EcoDemo2026!` |
| `amine`, `yasmine`, `karim` | Citoyen | `EcoDemo2026!` |

Connexion possible avec le **nom d'utilisateur ou l'e-mail**.

## 2. Fonctionnalités

| Rôle | Ce qu'il peut faire |
|------|---------------------|
| Visiteur | Accueil, inscription (rôle forcé à *Citoyen*) avec **confirmation par e-mail**, connexion, mot de passe oublié **par e-mail** |
| Citoyen | Voir/modifier son profil alimentaire et ses infos, avatar, changer son mot de passe, **analyse IA**, adopter l'objectif CO₂ proposé, supprimer son compte |
| Nutritionniste | Consulter les profils que les citoyens ont choisi de **partager** (`profil_public`) + leur dernière analyse |
| Administrateur | **CRUD complet des comptes** (liste, recherche, filtres, création, modification, suppression, activation/désactivation), statistiques, dashboard `/admin/` |

### Modèles (`users/models.py`)
- `Utilisateur(AbstractUser)` : e-mail unique (normalisé), `role`, `telephone` (validé par regex), `avatar`.
  Permissions personnalisées : `gerer_utilisateurs`, `voir_statistiques`.
- `ProfilAlimentaire` (OneToOne, créé automatiquement par signal) : régime, aliments aimés/évités,
  foyer, activité, temps de cuisine, ville, objectif CO₂, partage.
  Règles métier dans `clean()` : un aliment ne peut pas être aimé **et** évité ; l'objectif doit être
  < empreinte estimée ; bornes 5–100 kg.
- `AnalyseProfilIA` : statut (EN_ATTENTE → EN_COURS → TERMINE/ECHEC), source (GEMINI/LOCAL),
  résultat JSON, **temps de réponse en ms**.

Empreinte estimée = émissions moyennes du régime × 7 (Scarborough et al., 2014, *Climatic Change*) :
végan 2,89 · végétarien 3,81 · pescétarien 3,91 · flexitarien 4,67 · omnivore 5,63 · gros mangeur de viande 7,19 kg CO₂e/jour.

## 3. E-mails

| Quand | E-mail envoyé |
|---|---|
| Inscription | Lien de **confirmation de l'adresse** (valable 24 h, usage unique). La connexion est **bloquée** tant que l'adresse n'est pas confirmée ; lien « Renvoyer le lien » disponible. |
| Mot de passe oublié | Lien de **réinitialisation** (24 h, usage unique). Même réponse que l'e-mail existe ou non (anti-énumération). |
| Mot de passe changé (depuis le profil ou après réinitialisation) | **Notification de sécurité** avec un lien « Ce n'est pas vous ? ». |

Jetons signés avec `SECRET_KEY` (`PasswordResetTokenGenerator`) : le lien de confirmation devient invalide
dès que l'adresse est confirmée ou modifiée. E-mails en **HTML + texte**. Comptes créés par un admin,
superutilisateurs et comptes démo sont considérés comme confirmés. Si l'envoi échoue, le compte est créé
et l'utilisateur est invité à renvoyer le lien (pas de page d'erreur).

**Configuration** (dans `.env`, le backend est choisi automatiquement) :
- *Rien* → les e-mails s'affichent dans le terminal (pratique pour tester / démo).
- *Gmail (local)* : activer la validation en 2 étapes, créer un **mot de passe d'application**
  (myaccount.google.com/apppasswords), puis `EMAIL_HOST_USER=...@gmail.com` et `EMAIL_HOST_PASSWORD=...`.
- *Render* : l'offre gratuite **bloque les ports SMTP** → utiliser l'API HTTPS **Brevo** (300 e-mails/jour
  gratuits) : `BREVO_API_KEY=...` et `DEFAULT_FROM_EMAIL=EcoAssiette <expediteur.verifie.dans.brevo@...>`.

## 3 bis. Intelligence artificielle

### Assistant de recette et impact environnemental

La page `/impact/assistant-recette/` accepte une recette en texte libre. Gemini extrait les ingrédients,
leurs grammages et leurs catégories ; sans clé ou en cas d'erreur, un extracteur local prend le relais.
L'utilisateur corrige toujours le brouillon avant validation, conserve ses ingrédients et choisit les
substitutions végétales proposées. Seul le repas confirmé rejoint son historique. Son détail affiche le
CO₂, l'eau, les terres et le risque de déforestation estimés. La page `/impact/` cumule l'impact réel des
repas validés et les économies obtenues grâce aux alternatives adoptées.

**Besoin réel couvert :** à l'inscription, l'utilisateur ne sait pas quel objectif se fixer ni par quoi
remplacer les plats qu'il aime. L'IA transforme son profil en : empreinte estimée, **objectif CO₂ réaliste**
(adoptable en un clic), **alternatives végétales basées sur ses plats préférés** (y compris tunisiens :
couscous, ojja, kafteji…), conseils adaptés au temps de cuisine et à la taille du foyer.

**Chaîne de traitement (`users/ai.py`)**
1. Appel **Gemini** (API REST, réponse JSON imposée via `responseMimeType`), clé dans `GEMINI_API_KEY`
   envoyée en en-tête `x-goog-api-key` (jamais dans l'URL, jamais dans le code).
2. **Validation** de la réponse : schéma, objectif borné, suppression de toute alternative contenant un
   aliment évité ou un produit animal.
3. **Repli local** déterministe (table de substitutions + facteurs Poore & Nemecek 2018) si : pas de clé,
   timeout, erreur HTTP/quota, JSON illisible, réponse incomplète. L'utilisateur a toujours un résultat
   et la source est affichée.

**Asynchrone (`users/tasks.py`)** — l'appel IA ne bloque jamais la requête HTTP :
`POST /comptes/profil/analyse/` crée l'analyse et répond **202** ; le navigateur interroge
`GET /comptes/profil/analyse/<id>/` chaque seconde (indicateur de chargement, région `aria-live`,
message d'erreur explicite, délai max 60 s).
- `USE_CELERY=True` → tâche **Celery** (`celery -A config worker -l info`, Redis dans `REDIS_URL`)
- `USE_CELERY=False` → thread d'arrière-plan (démo locale / Render gratuit sans Redis)

**Métriques (`python manage.py evaluer_ia [--local] [--json rapport.json]`)** sur 10 profils de référence :

| Métrique | Définition | Moteur local |
|---|---|---|
| Réponses exploitables | JSON valide et conforme | 100 % |
| Respect des aliments évités | aucune alternative ne contient un aliment évité | 100 % |
| Alternatives 100 % végétales | aucun produit animal en remplacement | 100 % |
| Pertinence goûts | % d'alternatives partant d'un plat aimé | 57 % |
| Cohérence de l'objectif | 5 kg ≤ objectif ≤ empreinte | 100 % |
| Latence moyenne / p95 | temps de réponse | < 1 ms |

Avec une clé Gemini, relancer la commande sans `--local` pour obtenir les chiffres Gemini (latence typique
de quelques secondes → justifie le traitement asynchrone). La page **Statistiques** affiche en continu :
nombre d'analyses, part Gemini/local, échecs, temps moyen et p95.

## 4. Tests

```bash
python manage.py test users              # 117 tests
coverage run manage.py test users && coverage report && coverage html   # rapport dans htmlcov/
```

| Fichier | Contenu |
|---|---|
| `test_models.py` | hachage PBKDF2, e-mail unique, profil auto, groupe ↔ rôle, règles `clean()`, bornes |
| `test_forms.py` | inscription (rôle forcé), e-mail en double, mot de passe faible, attributs ARIA |
| `test_views.py` | statuts HTTP, inscription/connexion/déconnexion, reset par e-mail, IA (202, polling), 404/500 |
| `test_permissions.py` | **accès par URL directe** : anonyme → login, citoyen → 403, nutritionniste limité, CRUD admin |
| `test_api.py` | API DRF : authentification, permissions, validation métier (400) |
| `test_emails.py` | confirmation (envoi, connexion bloquée, lien unique, lien invalide, renvoi), notification de changement, reset complet, backend Brevo |
| `test_ai.py` | Gemini simulé (`mock`) : succès, filtrage, timeout, 429, JSON invalide → repli ; tâche ; commandes |

## 5. Sécurité (bases OWASP)

- CSRF actif sur tous les formulaires et l'appel IA (`X-CSRFToken`) ; déconnexion en **POST**.
- ORM uniquement (aucun SQL brut) ; mots de passe **PBKDF2-SHA256** + validateurs Django.
- Secrets dans `.env` / variables Render (`SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`) — `.env` ignoré par Git.
- `DEBUG=False` en production → cookies `Secure`, HSTS, redirection HTTPS, `X-Frame-Options: DENY`.
- Contrôle d'accès : `@login_required`, `LoginRequiredMixin`, `PermissionRequiredMixin` (mixin
  `PermissionOu403Mixin` : anonyme → login, connecté sans droit → 403) + **groupes/permissions Django**.
- Un nutritionniste ne voit que les profils partagés ; un citoyen ne peut lire que **ses** analyses (404 sinon).
- Un admin ne peut ni se supprimer, ni se désactiver, ni retirer son propre rôle.
- Connexion : message identique pour compte inexistant / mauvais mot de passe (anti-énumération).
- Données IA insérées dans le DOM via `textContent` (pas d'`innerHTML` → pas de XSS).
- Pages d'erreur personnalisées 403 / 404 / 500 ; `try/except` ciblés autour de l'API IA.

## 6. Accessibilité

`lang="fr"`, lien d'évitement, `<header>/<nav>/<main>/<footer>`, un seul `h1` par page,
labels reliés, aide et erreurs reliées par `aria-describedby` + `aria-invalid`, `aria-current` dans le
menu, `aria-live` pour le statut IA, menu mobile avec `aria-expanded` (Échap pour fermer), focus visible
(3 px), cibles ≥ 44 px, contrastes ≥ 4,5:1, tableaux avec `caption`/`scope`, `prefers-reduced-motion`.
Audit : **axe-core 4.10 → 0 violation** sur accueil, connexion, inscription (avec erreurs), profil, gestion,
statistiques, création de compte, profils nutritionniste, 404. À refaire en démo avec Lighthouse (Chrome).

## 7. Intégration avec les autres modules de l'équipe

> **Important :** `AUTH_USER_MODEL = "users.Utilisateur"` doit être en place **avant la première migration**
> du projet commun. Les autres apps référencent l'utilisateur ainsi :
> `models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)`.

- Profil accessible partout : `request.user.profil.regime`, `.liste_aimes`, `.liste_evites`,
  `.objectif_co2_hebdo`, `.emission_estimee_hebdo`.
- Permissions dans les templates : `{% if perms.users.gerer_utilisateurs %}`.
- API (session) : `GET/PATCH /api/moi/`, `GET/PUT/PATCH /api/moi/profil/`, `GET /api/utilisateurs/` (admin).
- Le module *Alternatives végétales* peut réutiliser `users.ai.SUBSTITUTIONS` et `FACTEURS`.

## 8. Déploiement sur Render

Conforme au guide du cours (PostgreSQL + WhiteNoise + `build.sh` + Gunicorn/Uvicorn).

1. Pousser le dépôt sur GitHub.
2. Soit **Blueprint** (`render.yaml` crée la base et le service), soit manuellement :
   - Build : `./build.sh` · Start : `python -m gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker`
3. Variables : `DATABASE_URL` (Internal URL), `SECRET_KEY`, `WEB_CONCURRENCY=4`, `DEBUG=False`,
   `GEMINI_API_KEY`, `DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD`, `SEED_DEMO=True` (optionnel).

## 9. Arborescence

```
config/            settings (env), urls, celery, asgi/wsgi
users/
  models.py        Utilisateur, ProfilAlimentaire, AnalyseProfilIA
  forms.py         formulaires + mixin d'accessibilité
  views.py         auth, espace citoyen, IA, nutritionniste, CRUD admin, erreurs
  permissions.py   PermissionOu403Mixin
  signals.py       groupes/permissions, profil automatique
  backends.py      connexion e-mail ou username
  ai.py            Gemini + validation + moteur local
  tasks.py         exécution asynchrone (Celery / thread)
  api/             DRF
  management/commands/  seed_demo, evaluer_ia
  emails.py        e-mails (confirmation, notification) + jeton
  email_backends.py  envoi via API Brevo
  tests/           117 tests
templates/         base, accueil, includes accessibles, erreurs
static/            css, js (menu, analyse IA)
```

## 10. Questions probables en soutenance

- **Pourquoi `AbstractUser` ?** Recommandation Django : modèle personnalisé dès le départ ; on garde
  tout l'existant (hachage, permissions) et on ajoute `role`, `telephone`, `avatar`.
- **Pourquoi `role` + groupes ?** `role` = source unique de vérité lisible ; le signal synchronise le
  groupe Django, et ce sont les **permissions** (pas le rôle) qui sont vérifiées dans les vues.
- **Pourquoi un repli local ?** L'API externe peut être lente, en panne ou hors quota : la fonctionnalité
  reste disponible et la source est transparente pour l'utilisateur.
- **Pourquoi asynchrone ?** Gemini prend quelques secondes ; un worker Gunicorn bloqué pendant ce temps
  ne sert personne d'autre. 202 + polling libère la requête immédiatement.
- **Comment évaluer une IA générative ?** Pas de vérité unique → critères vérifiables (contraintes
  respectées, cohérence des chiffres, pertinence par rapport aux goûts) + latence.
- **Comment empêcher le contournement par URL ?** Toutes les vues sensibles sont protégées côté serveur
  et testées (`test_permissions.py`), y compris les requêtes POST directes.
