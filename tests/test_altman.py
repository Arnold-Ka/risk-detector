"""Tests du signal Altman Z.

Stratégie de test (utile pour la suite) :
  - ICI : comportement pur, sans base, sans réseau — les fonctions de
    app/signals/ sont des calculs déterministes, c'est ce qui les rend
    testables ainsi.
  - PHASE 1 : ajouter des fixtures XBRL réelles (fichiers JSON d'entreprises
    connues, figés dans tests/fixtures/) pour vérifier le normalisateur, puis
    les 20 entreprises de référence de la feuille de route §6.

Commande pour ce fichier seul :
    uv run pytest tests/test_altman.py -v
"""

from app.signals.altman import altman_z

# Données manquantes : total_assets à 0/None -> le calcul est impossible.
# Règle produit : renvoyer None ("donnée manquante"), JAMAIS un faux score.
def test_missing_data_returns_none():
    assert altman_z(0, 0, 0, 0, 0, 0) is None


# Garde-fou supplémentaire : total_assets absent (None) même si les autres
# valeurs sont fournies -> pas de division par zéro, None.
def test_missing_total_assets_returns_none():
    assert altman_z(100, None, 200, 150, 500, 1200) is None
