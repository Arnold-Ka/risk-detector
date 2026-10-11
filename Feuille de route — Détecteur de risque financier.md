# Feuille de route — Détecteur de risque financier

Oct 6, 2026 · @Arnold · révisé en octobre 2026 : projet open source (licence MIT) et deep learning intégré au produit

## 1. Vision du projet

Construire, seul et en 18 mois, un système d'alerte précoce qui signale les entreprises cotées en danger financier avant que la presse n'en parle, en expliquant chaque alerte en langage simple.

**Le problème.** Les investisseurs particuliers découvrent les difficultés d'une entreprise trop tard : au moment de l'effondrement du cours. Les signaux existaient pourtant des mois avant, dispersés dans des centaines de pages de rapports, des déclarations de transactions des dirigeants et des annonces réglementaires que personne n'a le temps de lire.

**La solution.** Un outil web qui surveille en continu les entreprises choisies par l'utilisateur, calcule des scores de risque reconnus, détecte les événements inquiétants, suit l'historique d'indicateurs avec des modèles de deep learning et compare le texte des rapports d'une période à l'autre. Chaque alerte indique sa source exacte.

**La cible, par ordre de priorité :**

1. Investisseurs particuliers actifs (portefeuille d'actions individuelles américaines) ;
2. Auteurs de newsletters et créateurs de contenu financier ;
3. Petits gestionnaires, conseillers indépendants et clubs d'investissement.

**La proposition de valeur en une phrase :** « Sois prévenu quand une entreprise que tu détiens commence à mal tourner, avec les preuves. »

**Pourquoi c'est faisable seul :** les données américaines sont publiques et gratuites, les scores sont des formules connues, le deep learning s'entraîne gratuitement sur ces mêmes données publiques, et le code est open source sous licence MIT : chacun peut auditer le calcul. L'utilisateur ne confie ni argent ni données personnelles. Il juge l'outil sur des cas réels qu'il peut vérifier lui-même.

&#91;embedded content: feuille de route · 5 phases, 4 étapes de validation\]

On ne passe à la phase suivante que si l'étape de validation est atteinte ; le backtest de la phase 1 est la plus décisive.

## 2. Les signaux de risque

Le produit repose sur quatre familles de signaux : les chiffres, les événements, le texte et les modèles de deep learning. Les deux premières suffisent pour la première version ; le texte analysé par IA devient le principal avantage concurrentiel ensuite ; les modèles de deep learning viennent renforcer la détection en apprenant sur l'historique, sans jamais remplacer les scores traçables.

### Signaux quantitatifs (calculés à partir des états financiers)

| Signal | Ce qu'il mesure | Seuil d'alerte | Version |
| --- | --- | --- | --- |
| Z-score d'Altman | Risque de faillite à 2 ans | Inférieur à 1,81 = zone de détresse | MVP |
| F-score de Piotroski | Solidité financière, de 0 à 9 | 0 à 2 = entreprise fragile | MVP |
| M-score de Beneish | Probabilité de manipulation comptable | Supérieur à −1,78 = suspect | MVP |
| Écart bénéfice / cash | Bénéfice en hausse mais cash opérationnel en baisse | 2 trimestres consécutifs | MVP |
| Autonomie de trésorerie | Mois de survie au rythme de dépenses actuel | Moins de 12 mois | MVP |
| Dette nette / EBITDA | Poids de la dette | Supérieur à 4 et en hausse | V2 |
| Dilution | Augmentation du nombre d'actions | Plus de 10 % sur un an | V2 |

Formule du Z-score d'Altman (version entreprises industrielles cotées), où A = fonds de roulement / actif total, B = bénéfices non distribués / actif total, C = EBIT / actif total, D = capitalisation boursière / dettes totales, E = chiffre d'affaires / actif total :

```latex
Z = 1{,}2A + 1{,}4B + 3{,}3C + 0{,}6D + 1{,}0E
```

Attention : ces scores sont peu fiables pour les banques, les assurances et les sociétés immobilières (REIT). Il faudra les exclure ou utiliser des indicateurs adaptés à ces secteurs.

### Signaux d'événements (détectés dans les dépôts réglementaires)

| Événement | Pourquoi c'est inquiétant | Où le trouver |
| --- | --- | --- |
| Ventes massives d'actions par les dirigeants | Ceux qui savent le plus vendent | Formulaire 4 |
| Changement d'auditeur | Désaccord possible sur les comptes | 8-K, item 4.01 |
| Départ du directeur financier ou du PDG | Souvent avant de mauvaises nouvelles | 8-K, item 5.02 |
| Rapport déposé en retard | Problème dans les comptes | Formulaire NT 10-K / NT 10-Q |
| Doute sur la continuité d'exploitation | L'auditeur doute de la survie | Texte du 10-K |
| Comptes corrigés après publication | Erreurs ou fraude | 8-K, item 4.02 |
| Défaut ou déclenchement d'une clause de dette | Difficulté de financement | 8-K, item 2.04 |

### Signaux textuels (analysés par IA)

- **Nouveaux facteurs de risque** ajoutés au rapport annuel par rapport à l'année précédente ;
- **Changement de ton** : formulations plus prudentes, plus de conditionnel, objectifs flous ;
- **Promesses disparues** : un objectif annoncé l'an dernier qui n'est plus mentionné ;
- **Contradictions** entre le discours des dirigeants et les chiffres publiés.

### Signaux deep learning (appris sur l'historique)

Plutôt que de coder à la main chaque règle, un modèle apprend la différence entre des entreprises qui ont fait faillite et des entreprises saines, à partir de leurs séries d'indicateurs normalisés (actif total, cash opérationnel, dette… sur 5 ans).

- **Modèle séquentiel (LSTM ou transformer financier)** : enchaîne les trimestres d'indicateurs et produit une probabilité de détresse à 6–12 mois. Entraîné d'abord sur la cohorte du backtest (phase 1), inférence ajoutée à la fiche de risque dès la phase 2 ;
- **Traçabilité maintenue** : le score du modèle est un signal comme un autre (date, sévérité, source = dernières valeurs observées + cohorte d'entraînement). Il s'affiche *à côté* des scores classiques, jamais à leur place, tant qu'il ne les a pas battus sur le backtest ;
- **Explicabilité** : attribution de la contribution de chaque variable (SHAP ou équivalent) pour que chaque alerte du modèle reste explicable en langage simple, comme pour les scores classiques ;
- **Biais à surveiller** : surapprentissage sur une centaine de faillites seulement, dérive quand les pratiques comptables changent → réentraînement trimestriel (phase 4).

### Score global

Chaque entreprise reçoit un niveau de risque (faible, modéré, élevé, critique) calculé à partir des signaux actifs, pondérés selon leur gravité. Le poids de chaque signal sera ajusté grâce au backtest (phase 1) : on vérifie quels signaux étaient réellement présents avant les faillites passées.

## 3. Sources de données

Presque tout vient gratuitement de la base EDGAR de la SEC ; seuls les cours de bourse nécessitent une source externe.

| Besoin | Source | Coût | Remarque |
| --- | --- | --- | --- |
| Liste des dépôts d'une entreprise | API `data.sec.gov/submissions` | Gratuit | Un fichier JSON par entreprise (identifiant CIK) |
| Chiffres comptables structurés | API `data.sec.gov/api/xbrl/companyfacts` | Gratuit | Tous les postes du bilan, compte de résultat, flux de trésorerie |
| Comparaison entre entreprises | API `xbrl/frames` | Gratuit | Un indicateur pour toutes les entreprises sur une période |
| Téléchargement massif | Archives nocturnes `companyfacts.zip` et `submissions.zip` | Gratuit | Idéal pour l'historique et le backtest |
| Transactions des dirigeants | Formulaires 4 (XML) | Gratuit | À analyser soi-même |
| Événements importants | Formulaires 8-K | Gratuit | Classés par numéro d'item |
| Texte des rapports annuels | 10-K et 10-Q (HTML) | Gratuit | Section « Risk Factors » = item 1A |
| Cours de bourse et capitalisation | API boursière tierce | Gratuit à \~30 $/mois | Nécessaire pour le Z-score (variable D) |

**Règles d'accès à respecter :** la SEC limite à 10 requêtes par seconde et exige un en-tête User-Agent contenant un nom et une adresse e-mail. Il faut mettre les données en cache plutôt que d'interroger la SEC à chaque visite d'utilisateur.

**Données pour le backtest :** les faillites passées sont repérables via les 8-K item 1.03 (dépôt de bilan). On constitue ainsi une liste d'entreprises qui ont réellement fait faillite, pour vérifier si l'outil les aurait signalées à l'avance.

**Limites connues :**

- Les entreprises n'utilisent pas toujours les mêmes noms de postes comptables (XBRL) : il faut une table de correspondance pour chaque indicateur ;
- Certaines petites entreprises ont des données incomplètes : l'outil doit afficher « donnée manquante » plutôt qu'un score faux ;
- Les entreprises étrangères cotées aux États-Unis déposent des formulaires différents (20-F, 6-K).

**Plus tard (phase 4) :** l'Europe, via les rapports au format ESEF que les sociétés cotées de l'UE publient depuis 2021, plus dispersés et moins standardisés.

## 4. Architecture technique

Une architecture volontairement simple : un seul langage (Python) pour la collecte et les calculs, une base de données unique, et un site web léger. Tout doit pouvoir tourner sur un petit serveur à moins de 50 $ par mois au début. Le code est open source (licence MIT) publié sur GitHub : l'entraînement des modèles a lieu hors ligne, l'inférence en production reste légère.

&#91;embedded content: architecture · 4 couches, 10 composants\]

Le moteur de signaux est le cœur du produit ; le module IA texte n'arrive qu'en phase 3, et le moteur de deep learning s'installe par-dessus, du backtest (entraînement) à l'inférence nightly (phase 2).

### Les composants

1. **Collecteur** : tâches planifiées qui récupèrent chaque nuit les nouveaux dépôts EDGAR (et toutes les 10 minutes pour les 8-K et formulaires 4) ;
2. **Normalisateur** : transforme les postes XBRL hétérogènes en indicateurs standard (actif total, cash opérationnel, dette…) ;
3. **Moteur de signaux** : calcule les scores et détecte les événements, stocke chaque signal avec sa date et sa source ;
4. **Moteur de deep learning** : entraînement hors ligne sur la cohorte du backtest (séries d'indicateurs), inférence nightly à partir de la phase 2, explication par variable obligatoire à l'affichage ;
5. **Module IA texte** (phase 3) : extrait la section des facteurs de risque, la compare à l'année précédente et résume les changements ;
6. **Base de données** : entreprises, chiffres, signaux, utilisateurs, listes de suivi ;
7. **API + site web** : recherche d'entreprise, fiche de risque, liste de suivi, compte utilisateur ;
8. **Système d'alertes** : e-mail (puis notifications) quand un nouveau signal apparaît sur une entreprise suivie.

### Stack recommandée

| Couche | Choix | Pourquoi |
| --- | --- | --- |
| Collecte et calculs | Python (requests, pandas) | Écosystème financier riche |
| Deep learning | PyTorch | Écosystème dominant, modèles open source pré-entraînés, gratuit sur CPU à cette échelle |
| Planification | Cron ou une file de tâches simple (RQ, Celery plus tard) | Suffisant au début |
| Base de données | PostgreSQL | Fiable, gratuit, gère bien l'historique |
| API | FastAPI | Rapide à écrire, documentation automatique |
| Site web | Next.js (pnpm, Tailwind) | Rendu rapide, bon pour le référencement |
| Licence du code | MIT, dépôt public GitHub | Open source : confiance, auditabilité, contributions |
| Paiements | Stripe | Abonnements gérés clé en main |
| E-mails | Un service transactionnel (Resend, Postmark…) | Délivrabilité |
| IA texte | API d'un grand modèle de langage + transformer open source fine-tuné (phase 3) | Synthèse par l'API, détection fine par le modèle maison |
| Hébergement | Un VPS (Hetzner, DigitalOcean…) puis montée en charge | Coût faible et prévisible |

### Principes

- **Tout calcul est traçable** : chaque score affiché doit pouvoir montrer les chiffres et le dépôt exact dont il vient ;
- **Pré-calculer plutôt que calculer à la demande** : les scores sont mis à jour la nuit, la page s'affiche instantanément ;
- **Garder l'historique** : chaque signal daté permet le backtest et les graphiques d'évolution ;
- **Code ouvert, valeur ailleurs** : tout le code est publié sous licence MIT ; l'avantage concurrentiel vient des données nettoyées, du backtest public, du service hébergé et de la confiance gagnée — pas du secret du code.

## 5. Phase 0 — Préparation et validation (semaines 1 à 2)

Objectif : vérifier, avant d'écrire du vrai code, que les données sont exploitables et que des gens veulent ce produit.

**Semaine 1 — Les données**

- [ ] Lire la documentation des API EDGAR et récupérer manuellement les données de 3 entreprises (une saine, une en difficulté, une ayant fait faillite) ;
- [ ] Calculer à la main le Z-score de ces 3 entreprises dans un tableur, pour comprendre chaque variable ;
- [ ] Lister les noms de postes XBRL nécessaires pour chaque score et noter les variantes rencontrées ;
- [ ] Choisir une source de cours de bourse et tester son offre gratuite.

**Semaine 2 — Le marché**

- [ ] Étudier 5 concurrents (Simply Wall St, Seeking Alpha, Koyfin, GuruFocus, Stockopedia) : prix, fonctionnalités de risque, avis négatifs des utilisateurs ;
- [ ] Poster une question ou une étude de cas sur des communautés d'investisseurs (Reddit r/stocks, r/ValueInvesting, forums spécialisés) pour mesurer l'intérêt ;
- [ ] Créer une page d'accueil simple avec une inscription à une liste d'attente ;
- [ ] Choisir le nom du produit et réserver le nom de domaine.

**Critère pour passer à la phase 1 :** les données des 3 entreprises sont récupérées automatiquement, et au moins 50 personnes se sont inscrites sur la liste d'attente ou ont réagi positivement.

## 6. Phase 1 — Prototype et MVP (semaines 3 à 10)

Objectif : un site fonctionnel où l'on tape le nom d'une entreprise américaine et où l'on obtient sa fiche de risque complète, avec la preuve que l'outil aurait détecté des faillites passées.

**Semaines 3 à 4 — Le pipeline de données**

- [ ] Script de téléchargement des archives `companyfacts` et `submissions` ;
- [ ] Table de correspondance XBRL → indicateurs standard ;
- [ ] Base PostgreSQL : tables entreprises, périodes, indicateurs ;
- [ ] Tests automatiques sur 20 entreprises connues pour vérifier les chiffres.

**Semaines 5 à 6 — Le moteur de signaux**

- [ ] Calcul des scores Altman, Piotroski, Beneish, écart bénéfice/cash, autonomie de trésorerie ;
- [ ] Analyse des formulaires 4 (ventes des dirigeants) ;
- [ ] Détection des 8-K critiques (items 1.03, 2.04, 4.01, 4.02, 5.02) et des dépôts tardifs ;
- [ ] Score global de risque avec pondération initiale.

**Semaines 7 à 8 — Le backtest (étape décisive)**

- [ ] Constituer une liste d'au moins 100 entreprises ayant fait faillite entre 2015 et 2025 ;
- [ ] Constituer un groupe témoin d'entreprises saines comparables ;
- [ ] Exporter le jeu de données d'entraînement du deep learning : séries d'indicateurs sur 5 ans + étiquette faillite / sain ;
- [ ] Entraîner un premier modèle séquentiel (LSTM, PyTorch) sur ce jeu de données, à comparer aux scores classiques ;
- [ ] Mesurer : combien de faillites auraient été signalées 6 et 12 mois avant ? Combien de fausses alertes sur les entreprises saines ? — pour les scores classiques **et** pour le modèle ;
- [ ] Ajuster les pondérations des signaux selon les résultats.

**Semaines 9 à 10 — Le site minimal**

- [ ] Recherche d'entreprise par nom ou symbole boursier ;
- [ ] Fiche de risque : niveau global, liste des signaux, explication en langage simple, lien vers chaque dépôt source ;
- [ ] Graphique d'évolution des scores sur 5 ans ;
- [ ] Mention claire : information, pas conseil en investissement.

**Critère pour passer à la phase 2 :** le backtest montre qu'au moins 60 à 70 % des faillites étaient signalées au moins 6 mois avant, avec un taux de fausses alertes acceptable. Ces chiffres deviennent ton argument marketing principal.

## 7. Phase 2 — Lancement public et premiers utilisateurs (mois 3 à 5)

Objectif : 1 000 utilisateurs inscrits et des retours concrets, sans encore chercher à gagner de l'argent.

**Fonctionnalités à ajouter**

- [ ] Comptes utilisateurs et liste de suivi (jusqu'à 10 entreprises en gratuit) ;
- [ ] Alertes par e-mail quand un nouveau signal apparaît ;
- [ ] Signal deep learning en production : inférence nightly du modèle séquentiel, affiché sur la fiche de risque avec son explication par variable ;
- [ ] Un résumé hebdomadaire : « les 10 entreprises dont le risque a le plus augmenté cette semaine » ;
- [ ] Pages publiques par entreprise, indexables par Google (une source de visiteurs gratuite et durable).

**Stratégie d'acquisition (sans budget publicitaire)**

1. **Publier le backtest** : un article détaillé « notre outil aurait signalé ces faillites X mois à l'avance ». C'est le contenu le plus convaincant possible ;
2. **Études de cas régulières** : chaque fois qu'une entreprise s'effondre, montrer publiquement les signaux qui étaient visibles avant ;
3. **Communautés d'investisseurs** : participer sincèrement aux discussions, partager des analyses utiles, pas de spam ;
4. **Le résumé hebdomadaire** comme newsletter gratuite, facile à partager ;
5. **Lancement sur Product Hunt et Hacker News** une fois le produit stable — publier le dépôt open source (README complet, backtest, licence MIT) en même temps : Show HN récompense les projets ouverts et vérifiables.

**À mesurer chaque semaine :** inscriptions, entreprises ajoutées en suivi, taux d'ouverture des alertes, utilisateurs revenant au moins une fois par semaine.

**Critère pour passer à la phase 3 :** au moins 1 000 inscrits, dont 20 % actifs chaque mois, et des demandes répétées pour suivre plus d'entreprises ou recevoir des alertes plus rapides.

## 8. Phase 3 — Monétisation et IA textuelle (mois 5 à 9)

Objectif : lancer l'offre payante et ajouter la fonctionnalité qui distingue le produit des concurrents : l'analyse du texte des rapports.

**L'analyse textuelle par IA**

- [ ] Extraire automatiquement la section « Risk Factors » (item 1A) des 10-K ;
- [ ] Fine-tuner un transformer open source (type DeBERTa) sur nos paires de rapports pour détecter les changements de ton et les nouvelles formulations de risque, en complément de l'API de synthèse ;
- [ ] Comparer avec la version de l'année précédente : risques ajoutés, supprimés, reformulés ;
- [ ] Résumer les changements importants en 3 à 5 phrases simples, avec la citation exacte du passage modifié ;
- [ ] Mesurer l'évolution du ton dans les sections de discussion de la direction (MD&A) ;
- [ ] Vérifier manuellement 50 résumés pour contrôler que l'IA n'invente rien.

**L'offre payante**

- [ ] Intégrer Stripe et les abonnements mensuels / annuels ;
- [ ] Réserver au payant : suivi illimité, alertes en temps réel (8-K et formulaire 4 dans les 15 minutes), analyse IA du texte, export des données ;
- [ ] Offrir 14 jours d'essai gratuit de la version payante ;
- [ ] Proposer un tarif « membre fondateur » réduit à vie aux 200 premiers abonnés.

**Analyse du portefeuille**

- [ ] Import d'un portefeuille par fichier CSV (pas de connexion au compte de courtage : aucune confiance requise) ;
- [ ] Vue globale : quelle part du portefeuille est exposée à un risque élevé.

**Critère pour passer à la phase 4 :** au moins 100 abonnés payants et un taux de désabonnement mensuel inférieur à 8 %.

## 9. Phase 4 — Croissance et expansion (mois 9 à 18)

Objectif : passer de produit de niche à référence de la détection de risque, avec plusieurs sources de revenus.

**Nouvelles offres**

- [ ] **API pour professionnels** : newsletters, petits fonds, développeurs d'applications financières accèdent aux scores et signaux par API, facturés à l'usage ou par forfait ;
- [ ] **Offre équipe** : plusieurs utilisateurs, portefeuilles partagés, rapports exportables pour clubs d'investissement et conseillers ;
- [ ] **Widgets intégrables** : un badge de risque que les sites et blogs financiers affichent sur leurs pages, avec lien vers ton outil (source de visibilité).

**Nouveaux marchés**

- [ ] Europe via les rapports ESEF, en commençant par un pays (France ou Royaume-Uni, où les données sont les plus accessibles) ;
- [ ] Entreprises non cotées, en reprenant l'idée du risque client pour les PME (marché B2B plus large).

**Amélioration continue du modèle**

- [ ] Refaire le backtest chaque trimestre avec les nouvelles faillites ;
- [ ] Réentraîner le modèle deep learning sur la cohorte actualisée, tester une version plus profonde (transformer financier) et ne la déployer que si elle bat l'ancienne et les scores classiques ;
- [ ] Publier un rapport annuel public de performance des alertes : la transparence remplace la réputation que tu n'as pas encore.

**Organisation**

- [ ] Envisager une première embauche ou un associé (marketing ou finance) quand le revenu mensuel dépasse 5 000 à 10 000 $ ;
- [ ] Décider entre croissance autofinancée ou levée de fonds selon la traction obtenue.

## 10. Modèle économique et concurrence

Un modèle « freemium » : la version gratuite attire et prouve la valeur, l'abonnement payant finance le projet. Les prix ci-dessous sont des hypothèses de départ à tester.

**Le code est open source, le service ne l'est pas.** La licence MIT autorise librement toute réutilisation, y compris commerciale, du code. Cela ne rend pas le service gratuit : l'hébergement, les alertes, les données nettoyées, l'interface et la mise à jour continue restent payants — c'est le modèle classique des entreprises open source (ex. GitLab). Le dépôt public est aussi un canal d'acquisition : les stars GitHub et les contributions reportent des visiteurs.

### Grille tarifaire proposée

| Offre | Prix envisagé | Contenu |
| --- | --- | --- |
| Gratuit | 0 $ | Fiches de risque publiques, 10 entreprises suivies, alertes quotidiennes par e-mail |
| Pro | 12 $/mois ou 120 $/an | Suivi illimité, alertes en temps réel, analyse IA du texte, import de portefeuille |
| Expert | 29 $/mois | Tout Pro + export des données, historique complet, filtres de recherche avancés |
| API / Professionnels | À partir de 99 $/mois | Accès programmatique aux scores et signaux |

### Ordre de grandeur des revenus (exemple illustratif)

| Scénario | Abonnés payants | Prix moyen | Revenu mensuel |
| --- | --- | --- | --- |
| Démarrage | 100 | 13 $ | \~1 300 $ |
| Viable pour une personne | 400 | 15 $ | \~6 000 $ |
| Petite entreprise solide | 1 500 | 16 $ + API | \~25 000 $ et plus |

Avec un taux de conversion gratuit → payant typique de 2 à 5 %, il faut environ 10 000 à 20 000 utilisateurs gratuits pour atteindre 400 abonnés.

### Concurrence

| Concurrent | Positionnement | Ta différence |
| --- | --- | --- |
| Simply Wall St | Analyse visuelle généraliste, scores de « santé financière » | Spécialisation exclusive sur le danger, alertes en temps réel |
| Seeking Alpha | Articles d'analystes + notes quantitatives | Signaux factuels et sourcés plutôt qu'opinions |
| GuruFocus / Stockopedia | Scores financiers nombreux, interface dense | Simplicité, explication en langage courant |
| Terminaux professionnels (Bloomberg…) | Complets, très chers | Accessible aux particuliers |

### Ton avantage durable

1. **La spécialisation** : un outil qui ne fait qu'une chose, très bien ;
2. **L'analyse du texte** : peu de concurrents comparent les rapports d'une année à l'autre ;
3. **La transparence prouvée** : backtest public et chaque alerte reliée à sa source ;
4. **L'historique des alertes** : avec le temps, tes alertes passées vérifiables deviennent ta réputation ;
5. **L'open source** : un code public que chacun peut auditer (licence MIT) — les concurrents fermés ne peuvent pas promettre la même confiance, et la communauté peut contribuer correctifs et modèles.

## 11. Aspects juridiques et réglementaires

Le projet reste du bon côté de la loi s'il fournit de l'information factuelle et générale, jamais de recommandation personnalisée. Les points ci-dessous sont des repères, pas un avis juridique : une consultation avec un avocat spécialisé est recommandée avant la phase 3.

| Sujet | Risque | Comment s'en protéger |
| --- | --- | --- |
| Conseil en investissement | Être considéré comme conseiller financier sans agrément | Information générale et identique pour tous ; jamais « achetez » ou « vendez » ; avertissement visible sur chaque page |
| Diffamation | Une entreprise conteste une alerte | Présenter des signaux factuels et sourcés, pas des accusations ; vocabulaire neutre (« signal de risque », pas « fraude ») |
| Erreurs de données | Un utilisateur perd de l'argent à cause d'un chiffre faux | Conditions d'utilisation limitant la responsabilité ; lien vers la source originale ; afficher les données manquantes |
| Licences des cours de bourse | Redistribuer des données sans en avoir le droit | Lire les conditions de l'API choisie ; payer une licence de redistribution si nécessaire |
| Résumés par IA | Une erreur de l'IA présentée comme un fait | Étiqueter « résumé généré par IA », citer le passage original, vérifications régulières |
| Données personnelles | Non-respect du RGPD pour les utilisateurs européens | Collecter le minimum (e-mail), politique de confidentialité claire, suppression de compte possible |
| Code open source (MIT) | Réutilisation sans respect de la licence, ou contributions indésirables | Publier le fichier `LICENSE` complet, un `CONTRIBUTING.md` avec accord de contribution simple (CLA), et vérifier qu'aucun secret ni donnée personnelle n'entre dans le dépôt |
| Paiements internationaux | Stripe n'est pas disponible dans tous les pays | Vérifier la disponibilité dans ton pays ; sinon, un « marchand officiel » comme Paddle ou Lemon Squeezy, qui gère aussi les taxes internationales |

Les données de la SEC sont publiques et réutilisables librement, à condition de respecter les règles d'accès (limite de requêtes, identification).

## 12. Budget, indicateurs et risques

Le projet peut démarrer avec moins de 100 $ par mois ; ton temps reste la ressource principale.

### Budget mensuel estimé

| Poste | Phases 0–1 | Phases 2–3 | Phase 4 |
| --- | --- | --- | --- |
| Serveur et base de données | 10–20 $ | 40–80 $ | 150–400 $ |
| Données boursières | 0 $ (offre gratuite) | 30–100 $ | 100–500 $ (licence de redistribution) |
| API d'IA pour l'analyse de texte | 0 $ | 30–150 $ | 150–600 $ |
| Calcul ML / deep learning | 0 $ (CPU + Colab gratuit) | 0–30 $ | 30–150 $ (GPU à la demande pour les réentraînements) |
| E-mails transactionnels | 0 $ | 0–20 $ | 20–80 $ |
| Nom de domaine et outils | \~5 $ | \~20 $ | \~50 $ |
| **Total approximatif** | **15–25 $** | **120–400 $** | **500–1 780 $** |

Ces montants sont des estimations à vérifier selon les fournisseurs choisis.

### Indicateurs clés à suivre

| Indicateur | Pourquoi | Objectif phase 3 |
| --- | --- | --- |
| Taux de détection du backtest | Preuve que l'outil fonctionne | ≥ 60–70 % des faillites signalées 6 mois avant |
| Taux de fausses alertes | Crédibilité | À minimiser, publié honnêtement |
| Utilisateurs actifs mensuels | Intérêt réel | 20 % des inscrits |
| Conversion gratuit → payant | Viabilité | 2–5 % |
| Désabonnement mensuel | Satisfaction | < 8 % |
| Revenu mensuel récurrent | Survie du projet | Couvrir tous les coûts |

### Risques du projet

| Risque | Probabilité | Impact | Plan de réponse |
| --- | --- | --- | --- |
| Le backtest montre une faible capacité de prédiction | Moyenne | Élevé | Revoir les pondérations, se repositionner sur « signaux à surveiller » plutôt que « prédiction » |
| Trop de fausses alertes, les utilisateurs se lassent | Élevée | Élevé | Niveaux de gravité, réglages d'alerte personnalisés |
| Un concurrent copie la fonctionnalité | Moyenne | Moyen | Avancer vite sur l'analyse textuelle et le backtest public ; le code étant open source, la valeur est dans les données, le service et la confiance, pas dans la dissimulation |
| Le modèle deep learning surapprend et échoue en production | Moyenne | Moyen | Ne jamais remplacer les scores classiques sans le battre sur le backtest ; explication par variable obligatoire ; réentraînement trimestriel |
| Données XBRL incohérentes | Élevée | Moyen | Tests automatiques, affichage des données manquantes |
| Épuisement (projet mené seul) | Moyenne | Élevé | Phases courtes avec critères clairs, abandonner une fonctionnalité plutôt que le projet |
| Coûts d'IA qui explosent | Faible | Moyen | Analyser seulement les nouveaux rapports, mettre les résultats en cache |
| Plainte d'une entreprise | Faible | Élevé | Vocabulaire neutre, sources systématiques, conseil juridique |

## 13. Prochaines actions cette semaine

Six actions concrètes pour démarrer dès maintenant :

- [ ] Publier le dépôt GitHub public avec la licence MIT (et le fichier `.env` hors dépôt !) ;
- [ ] Choisir 3 entreprises test : une solide, une en difficulté, une ayant fait faillite récemment ;
- [ ] Récupérer leurs données via l'API `companyfacts` de la SEC (avec un User-Agent contenant ton e-mail) ;
- [ ] Calculer leur Z-score d'Altman dans un tableur et comparer avec ce qui s'est réellement passé ;
- [ ] Lister les 5 concurrents et noter ce qui manque dans leurs fonctionnalités de risque ;
- [ ] Créer une page d'accueil avec inscription à la liste d'attente.

À la fin de la semaine, tu sauras si les données sont exploitables et si le sujet intéresse des gens : deux réponses qui conditionnent tout le reste.
