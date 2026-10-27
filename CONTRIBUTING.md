# Contribuer

Projet personnel à but pédagogique : les contributions (corrections de
bugs, fixtures EDGAR supplémentaires, améliorations de docs) sont les
bienvenues, les gros changements de fonctionnalité sont mieux discutés
en amont (issue) avant d'écrire le code.

## Conventions

- **Identifiants de code et messages de commit en anglais** ; **commentaires,
  docstrings et textes destinés à l'utilisateur en français** (règle du
  dépôt — le code commenté en anglais y est rejeté, l'inverse aussi).
- Pas d'ORM : SQL brut via psycopg. Signaux = fonctions pures déterministes
  (`app/signals/`) : données manquantes → `None`, jamais une valeur inventée
  (« donnée manquante » vaut mieux qu'un faux score).
- Tout score doit rester traçable jusqu'au dépôt source (`signals.filing_id`).

## Avant d'ouvrir une PR

```bash
uv run pytest                 # 209 tests doivent passer
pnpm --dir frontend lint      # sans erreur
pnpm --dir frontend build     # build Next.js valide
```

N'ajoutez jamais de secret, d'URL de dépôt privé ou de donnée personnelle ;
`.env` est ignoré par git, seule sa vitrine `.env.example` est versionnée.
Les requêtes SEC doivent rester sous la limite de 10/s (le client
`app/edgar/client.py` l'impose déjà — ne pas le contourner).

## CLA simplifié

En soumettant une contribution, vous confirmez qu'elle est votre travail et
qu'elle peut être publiée sous la licence MIT du dépôt.
