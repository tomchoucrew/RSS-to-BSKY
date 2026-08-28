# Xboxygen → Bluesky automatique

Ce petit bot surveille le flux RSS de Xboxygen et publie automatiquement les nouveaux articles sur Bluesky avec :

- le titre de l'article ;
- le lien cliquable ;
- une card avec titre, description et image OpenGraph lorsque l'image est disponible ;
- une protection contre les doublons en vérifiant les derniers posts Bluesky.

## 1. Créer un dépôt GitHub

Crée un nouveau dépôt GitHub, idéalement **public** si tu veux utiliser les GitHub Actions planifiées sans consommer le quota d'un dépôt privé.

Décompresse ensuite ce ZIP et envoie tous les fichiers dans le dépôt, y compris le dossier caché `.github`.

## 2. Créer un App Password Bluesky

Dans Bluesky :

**Settings → Privacy and Security → App Passwords → Add App Password**

Crée par exemple un mot de passe nommé `Xboxygen GitHub`.

Ne mets jamais ton mot de passe Bluesky principal dans GitHub.

## 3. Ajouter 3 secrets GitHub

Dans ton dépôt :

**Settings → Secrets and variables → Actions → New repository secret**

Ajoute :

### `BSKY_HANDLE`
Ton identifiant Bluesky, par exemple :

`xboxygen.bsky.social`

### `BSKY_APP_PASSWORD`
L'App Password créé à l'étape précédente.

### `RSS_URL`
L'URL exacte du flux RSS Xboxygen.

Tu peux récupérer l'URL via le lien **Flux RSS** présent dans le footer de Xboxygen.

## 4. Tester immédiatement

Dans GitHub :

**Actions → Xboxygen RSS vers Bluesky → Run workflow**

Le bot ne republie que les articles récents (45 minutes par défaut), afin d'éviter d'envoyer tout l'historique du RSS lors du premier lancement.

## 5. Fonctionnement automatique

Le fichier :

`.github/workflows/rss-to-bluesky.yml`

demande à GitHub de vérifier le flux toutes les **10 minutes**.

Attention : les GitHub Actions planifiées ne garantissent pas un déclenchement à la seconde près. Il peut y avoir quelques minutes de retard.

## Modifier la fréquence

Dans `.github/workflows/rss-to-bluesky.yml` :

Toutes les 10 minutes :

`*/10 * * * *`

Toutes les 15 minutes :

`*/15 * * * *`

Toutes les 30 minutes :

`*/30 * * * *`

GitHub n'accepte pas une fréquence planifiée inférieure à 5 minutes.

## Format du post

Le post généré ressemble à :

**Titre de l'article**

https://www.xboxygen.com/...

Puis une card Bluesky avec l'image, le titre et la description de l'article.

## Éviter les doublons

Aucun fichier d'état n'est nécessaire : avant de poster, le bot regarde les derniers posts du compte Bluesky et vérifie que l'URL de l'article n'a pas déjà été publiée.

## Réglages utiles

Dans le workflow :

`INITIAL_LOOKBACK_MINUTES: "45"`

empêche le premier lancement de republier des articles anciens.

`MAX_POSTS_PER_RUN: "3"`

limite à trois publications au maximum par exécution, utile si plusieurs articles sortent entre deux passages du bot.
