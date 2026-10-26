# Déploiement EcoAssiette sur Render

Le dépôt prépare automatiquement les dépendances, les fichiers statiques et les migrations avec `build.sh`.
Les secrets et les services externes doivent être configurés dans **Render > ecoassiette > Environment**.

## Variables obligatoires

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | Fournie automatiquement par la base PostgreSQL Render |
| `SECRET_KEY` | Générée par Render ; ne jamais la modifier après mise en production |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | Domaine Render et éventuel domaine personnalisé |
| `SEED_DEMO` | `False` en production : évite les comptes aux mots de passe de démonstration connus |

## E-mails de confirmation avec Brevo

Render gratuit pouvant bloquer SMTP, la production utilise l'API HTTPS Brevo.

1. Créer un compte Brevo et vérifier une adresse d'expéditeur.
2. Créer une clé API Brevo.
3. Ajouter dans Render :

```text
BREVO_API_KEY=<clé API>
DEFAULT_FROM_EMAIL=EcoAssiette <adresse vérifiée dans Brevo>
CONFIRMATION_EMAIL=True
```

Sans clé Brevo ni identifiants SMTP, EcoAssiette désactive automatiquement la confirmation afin de ne pas bloquer les nouvelles inscriptions. Ne définir `CONFIRMATION_EMAIL=True` qu'après un test d'envoi réussi.

## Photos et vidéos persistantes avec Cloudflare R2

1. Dans Cloudflare, créer un bucket R2 privé nommé par exemple `ecoassiette-media`.
2. Créer un jeton API limité à ce bucket avec la permission **Object Read & Write**.
3. Copier l'Account ID, l'Access Key ID et la Secret Access Key.
4. Ajouter dans Render :

```text
CLOUDFLARE_R2_ACCOUNT_ID=<account id>
CLOUDFLARE_R2_ACCESS_KEY_ID=<access key id>
CLOUDFLARE_R2_SECRET_ACCESS_KEY=<secret access key>
CLOUDFLARE_R2_BUCKET=ecoassiette-media
```

Le bucket doit rester privé. Django produit des liens signés valables une heure pour les images, vidéos, avatars et preuves.

## Intelligence artificielle

Ajouter `GEMINI_API_KEY` dans Render. Sans cette variable, les moteurs locaux de secours restent disponibles mais les fonctions génératives sont limitées.

## Premier déploiement et vérifications

Le build exécute automatiquement :

```text
pip install -r requirements.txt
python manage.py check --deploy
python manage.py collectstatic --no-input
python manage.py migrate
```

Après le déploiement :

1. Créer un compte et confirmer l'e-mail reçu.
2. Ajouter une image produit depuis l'administration, redéployer, puis vérifier qu'elle existe encore.
3. Générer un planning, ajouter un menu aux repas, envoyer une preuve et l'approuver.
4. Vérifier les points et générer un bon PDF.
5. Tester une analyse Gemini et contrôler le moteur indiqué dans le résultat.

Les données SQLite locales, les utilisateurs locaux et le dossier `media/` local ne sont jamais copiés automatiquement vers PostgreSQL/R2.
