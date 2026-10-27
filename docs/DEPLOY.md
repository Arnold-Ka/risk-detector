# Mise en production — plan gratuit (serverless)

Architecture cible, tout en free tier, sans machine à tourner la nuit :

```
GitHub (source + Actions)          Vercel          Render
├─ master ── autoDeploy ────────►  │ Frontend Next  │ API FastAPI (Docker, /health)
│  nightly  (05:30 UTC) ───────────┼───────────────►│        │
│  keepalive (/14 min) ────────────┼───────────────►│        │ lit/écrit
└─ secrets : DATABASE_URL,         └─ NEXT_PUBLIC_* │        ▼
   SEC_USER_AGENT, var API_URL                      PostgreSQL managé (Neon, 1 Go)
```

Cinq services à configurer : **GitHub, Neon, Render, Vercel et Clerk**.
Clerk sert uniquement à l'authentification ; les listes restent stockées dans
PostgreSQL sur Neon. Aucun ordinateur n'est nécessaire ensuite : le nightly
tourne dans GitHub Actions, l'API et le site sont toujours allumés.

> Pourquoi Neon et pas la base gratuite de Render : les bases gratuites de
> Render **expirent 30 jours après création** (données supprimées après 14
> jours de grâce) ; Neon est gratuit **sans expiration** (1 Go — notre base
> fait 829 Mo, la marge est expliquée dans « Vigies » plus bas).

## 1. GitHub — publier le dépôt

`gh` n'est pas nécessaire (ni de droits administrateur) : Git for Windows
embarque Git Credential Manager, qui ouvre la connexion GitHub dans le
navigateur au premier push. Créer le dépôt vide sur github.com (bouton
« New repository », public, sans README, licence ni `.gitignore`) puis :

```powershell
git remote add origin https://github.com/<vous>/risk-detector.git
git push -u origin master
```

Si `origin` a été ajouté avec une mauvaise URL (`remote origin already
exists`), la corriger plutôt que de le rajouter :
`git remote set-url origin https://github.com/<vous>/risk-detector.git`.

Avant le premier push d'un dépôt public : l'adresse e-mail de chaque commit
devient publique. Vérifier `git log --format='%ae' | sort | uniq -c` et
réécrire l'historique tant que rien n'a été poussé si besoin.

## 2. Neon — la base de données

1. Compte sur <https://neon.tech> → **Create project** (ex. `risk-detector`,
   région **AWS us-east-2 / Ohio** pour coller à Render plus bas).
2. Bouton **Connect** du tableau de bord : récupérer les **deux** chaînes
   de connexion (le mot de passe, généré par Neon, y est inclus — *Show
   password* ou *Copy snippet*). « Connection pooling » activé = hôte en
   `-pooler`, pour l'API et le nightly ; désactivé = chaîne directe, pour la
   migration. Mot de passe perdu : *Roles → neondb_owner → Reset password*.
3. Appliquer le schéma (fichier `app/db/schema.sql`) : soit l'onglet
   **SQL Editor** de Neon (coller le contenu du fichier), soit automatique
   lors de la migration ci-dessous (le dump contient le schéma).

**Migration des données locales (829 Mo)** — depuis la racine du projet,
la base locale doit tourner (`docker compose up -d --wait`) :

```powershell
# 1. dump binaire DANS le conteneur puis copie vers l'hôte
#    (jamais de redirection PowerShell sur du binaire : elle corrompt le fichier)
docker compose exec -T db bash -c "pg_dump -U risk -d risks --no-owner --no-privileges -Fc > /tmp/risks.dump"
docker compose cp db:/tmp/risks.dump ./risks.dump

# 2. restauration via l'image postgres:17 (aucun client psql local requis).
#    À taper dans un terminal PowerShell ordinaire, PAS via le préfixe « ! »
#    d'une session d'assistant : la chaîne contient le mot de passe et
#    finirait dans l'historique de la conversation. Guillemets simples : la
#    chaîne contient & et ? que PowerShell interpréterait. Compter 5 à 30
#    min sans affichage (envoi vers us-east-2 puis reconstruction des index).
$env:NEON_URL = 'postgresql://<user>:<pass>@<host-neon>/neondb?sslmode=require&channel_binding=require'
docker run --rm --mount "type=bind,source=$(Resolve-Path .\risks.dump),target=/dump.dump,ro" `
  postgres:17 pg_restore --no-owner --no-privileges --dbname="$env:NEON_URL" /dump.dump

# 3. nettoyage (le fichier est gitignoré, mais il contient des données : le supprimer)
Remove-Item Env:NEON_URL
Remove-Item .\risks.dump
```

Vérification : dans le SQL Editor de Neon,
`SELECT count(*) FROM signals;` → ~99 000.

## 3. Render — l'API

1. Compte sur <https://render.com> → **New + → Blueprint** → connecter le
   dépôt GitHub : `render.yaml` est détecté (service web Docker, région
   **Ohio** fixée dans le fichier, à côté de Neon). Une erreur du type
   `services[0].envVars[0]` vient du fichier, pas de la saisie : les
   variables d'un blueprint se déclarent avec `key:` (et non `id:`).
2. À la création, saisir les variables demandées :
    - `DATABASE_URL` : chaîne **pooled** de Neon ;
    - `SEC_USER_AGENT` : `Prénom Nom email@exemple.com` (l'API n'effectue
      aucune requête SEC, mais `app/config.py` exige la variable) ;
    - `CACHE_DIR` : la valeur pré-remplie va très bien ;
    - `FRONTEND_ORIGINS` : origine exacte du site Vercel, par ex.
      `https://risk-detector.vercel.app` ;
    - `WATCHLIST_API_SECRET` : secret aléatoire partagé avec Vercel (au moins
      32 caractères). Les endpoints de liste de suivi refusent les requêtes
      directes sans ce secret.
3. Attendre le premier déploiement, puis tester :
   `GET https://<url-service>.onrender.com/health` → JSON avec `"ok"`.

*Alternative sans blueprint* : **New + → Web Service** → repo → Runtime
**Docker** → le `Dockerfile` racine est détecté ; coller les mêmes env vars.

## 4. Vercel — le site

1. Compte sur <https://vercel.com> → **Add New → Project** → importer le
   dépôt GitHub.
2. **Root Directory = `frontend/`** (le déteateur est un monorepo ; Vercel
   détecte ensuite Next.js + pnpm tout seul).
3. Env vars du projet :
    - `NEXT_PUBLIC_API_URL` = URL Render (avec `https://`, sans `/` final) ;
    - `NEXT_PUBLIC_SITE_URL` = `https://<projet>.vercel.app` (servira aux
      canonicals et au sitemap) ;
    - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` et `CLERK_SECRET_KEY` : clés de
      l'application Clerk ;
    - `WATCHLIST_API_SECRET` : même valeur que sur Render. Cette variable
      reste côté serveur et ne doit jamais être préfixée `NEXT_PUBLIC_`.
4. Dans Clerk, créer une application, activer l'authentification par e-mail
   avec vérification, puis autoriser `localhost:3000` en développement et
   le domaine Vercel en production. Copier les clés dans les environnements
   correspondants ; ne jamais exposer `CLERK_SECRET_KEY`.
5. Générer un secret aléatoire d'au moins 32 caractères :

   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Enregistrer **la même valeur** dans `WATCHLIST_API_SECRET` côté Vercel et
   Render. En local, la placer dans `.env` à la racine et dans
   `frontend/.env.local` (copié depuis `frontend/.env.example`). Régler
   `FRONTEND_ORIGINS` côté Render sur l'origine exacte du site Vercel.

6. **Deploy**. Au premier passage, le build peut échouer si l'API Render
   n'est pas encore en ligne — recommencer (ou *Retry*) une fois l'API Render
   validée. Puis déployer **une seconde fois** après avoir renseigné
   `NEXT_PUBLIC_SITE_URL` si elle n'était pas connue au premier build.
7. **Vérifier l'adresse attribuée.** Si le nom de projet est déjà pris,
   Vercel en donne une autre (ex. `risk-detector-two.vercel.app`). Reporter
   cette adresse exacte dans `FRONTEND_ORIGINS` sur Render : sinon l'API
   répond 400 aux appels du navigateur, et la recherche de l'accueil comme
   la page Couverture restent vides, alors que les fiches (rendues côté
   serveur) fonctionnent — symptôme trompeur. Contrôle :
   `curl -X OPTIONS -H "Origin: https://<site>" -H "Access-Control-Request-Method: GET" https://<api>/search?q=apple`
   doit renvoyer `access-control-allow-origin: https://<site>`.

## 5. GitHub — secrets et workflows

Dans le dépôt : **Settings → Secrets and variables → Actions**

| Type | Clé | Valeur |
|---|---|---|
| Secret | `DATABASE_URL` | chaîne pooled Neon (identique à Render) |
| Secret | `SEC_USER_AGENT` | nom + e-mail réels (règle SEC) |
| Variable | `API_URL` | URL Render **sans** `/health` |
| Secret *(alertes)* | `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | relais SMTP du fournisseur d'envoi (Brevo, Resend, Mailgun…) |
| Secret *(alertes)* | `SMTP_PORT` | facultatif, `587` par défaut (`465` = TLS implicite) |
| Secret *(alertes)* | `ALERT_FROM_EMAIL` | expéditeur sur un domaine vérifié (SPF/DKIM), ex. `Détecteur de risque <alertes@mondomaine.fr>` |
| Variable *(alertes)* | `SITE_URL` | URL Vercel publique (= `NEXT_PUBLIC_SITE_URL`), utilisée dans les liens des e-mails |

Les secrets *(alertes)* sont facultatifs : sans `SMTP_HOST` ou
`ALERT_FROM_EMAIL`, le nightly détecte les changements de palier des
entreprises suivies et les journalise (comptes seulement, jamais d'adresse)
sans rien envoyer. Renseigner `SITE_URL` **avant** d'activer l'envoi, sinon
les liens pointent sur `localhost`.

Les clés Clerk et `WATCHLIST_API_SECRET` vont dans les variables d'environnement
de Vercel (et le secret partagé va aussi dans Render) ; elles ne sont pas
nécessaires aux jobs GitHub Actions.

Les endpoints `/me/watchlist` sont appelés par les route handlers serveur de
Next.js avec `WATCHLIST_API_SECRET` et l'identité Clerk vérifiée. Ne les
appelez pas directement depuis le navigateur et ne transmettez jamais un
`user_id` fourni par celui-ci.

Les deux workflows (`.github/workflows/`) sont actifs dès le push :
onglet **Actions** → autoriser les workflows si GitHub le demande.
Lancer le nightly manuellement une première fois :
*nightly → Run workflow* (voir « Recette »).

## 6. Recette

1. `https://<url>.onrender.com/health` → `{"status": "ok"}` (ou équivalent).
   Après le premier nightly : `https://<url>.onrender.com/health/data` →
   HTTP 200 avec `"status": "ok"` et `companies_with_level` proche de
   `companies`. Un 503 signifie des signaux de plus d'un jour (`stale`),
   une base sans signaux (`empty`) ou une base injoignable
   (`db_unavailable`).
2. `https://<projet>.vercel.app` → recherche d'entreprise fonctionnelle
   (elle appelle l'API Render), fiche **Apple (AAPL)** complète avec
   signaux, graphique et lien « dépôt source ».
3. `https://<projet>.vercel.app/sitemap.xml` → ~877 URLs, toutes en
   `https://<projet>.vercel.app`.
4. Actions → **nightly** vert ; le soir même, un second run vert (la
   première exécution remplit le cache EDGAR).
5. Actions → **keepalive** vert après 2 exécutions ; puis vérifier que
   `/health` répond **sans** délai même après 20 min sans visiteur.

## 7. Vigies et limites du plan gratuit

| Limite | Valeur | Notre utilisation / réflexe |
|---|---|---|
| Stockage Neon | 1 Go (base à **829 Mo**) | le nightly remplace des lignes, il ne fait pas grossir la base ; si > 900 Mo : purger `data/cache` local est sans effet — surveiller le dashboard Neon |
| Heures Render | 750 h/mois | keepalive = service toujours chaud = **744 h** consommées (31 j) ; un autre service gratuit du même workspace partagerait l'allocation |
| Spin-down Render | 15 min d'inactivité | neutralisé par le keepalive toutes les 14 min |
| Neon scale-to-zero | après 5 min | ~1-3 s au premier appel puis réveillé ; les crawlers SEO le subissent peu |
| Cache GitHub | 10 Go par dépôt | `edgar-cache-*` roulant ; purger via *Actions → Caches* si besoin |
| Minutes GitHub | illimité (dépôt public) | nightly ~10-20 min + keepalive ~2 s : négligeable |
| Artéfacts DL | `data/models/lstm.pt` + `lstm.meta.json` doivent être présents dans le checkout Actions | s'ils manquent ou si `input_dim` diffère, le nightly saute le LSTM ; suivre ou fournir les deux fichiers |

Coûts si le projet dépasse le gratuit : Neon *Launch* (facturé à
l'usage), Render *Starter* (bases sans expiration), Vercel *Pro* —
migration sans réécriture, mêmes points d'entrée.

## 8. Opérations courantes

- **Relancer le nightly** : Actions → nightly → *Run workflow*.
- **Nightly rouge** : lire la dernière ligne `ÉCHEC du nightly : …`. Plus
  de 20 % d'erreurs de calcul ou plus de 50 % d'échecs SEC (souvent un
  `SEC_USER_AGENT` refusé) font échouer le job ; les signaux des entreprises
  réussies restent écrits. Une étape « Fraîcheur » rouge seule signifie que
  l'API sert des données de plus d'un jour.
- **Déployer l'API après un push** : automatique (`autoDeploy: true`) ;
  sinon Render → service → *Manual Deploy*.
- **Changer `SEC_USER_AGENT`** : Secret GitHub + env Render (deux endroits).
- **Changer les poids ou les seuils du composite** : le premier nightly qui
  suit recalcule tous les niveaux, et chaque palier qui bouge déclenche une
  alerte pour ses abonnés. Pour un recalcul silencieux, lancer une fois
  `uv run python -m app.jobs.nightly --no-alerts` contre la base hébergée
  avant le prochain run planifié.
- **Revenir en local** : rien ne change — `docker compose up -d --wait`,
  `uv run uvicorn app.api.main:app --reload --port 8011`,
  `pnpm --dir frontend dev` continuent de pointer sur la base Docker
  (`localhost:5435`) via `.env` et `frontend/.env.local`.
