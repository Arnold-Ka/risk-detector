"""Z-score d'Altman — probabilité de détresse financière sous 2 ans.

Les entrées sont les cinq variables brutes de la formule, déjà normalisées
à partir de XBRL (normaliseur phase 1). Elles se mappent vers les ratios
classiques :

    A = fonds de roulement  / actif total      (liquidité)
    B = bénéfices non distribués / actif total (rentabilité cumulée)
    C = ebit                / actif total      (rentabilité opérationnelle)
    D = market_value_debt   / actif total      <- ATTENTION : la feuille de
        route définit D comme valeur boursière / dettes totales ; confirmer
        la variante exacte à l'implémentation (Z-scores « public
        manufacturers » vs « public non-manufacturers » n'utilisent pas les
        mêmes coefficients).
    E = chiffre d'affaires  / actif total      (rotation des actifs)

    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0E

Seuils d'interprétation (emetteurs industriels cotés) :
    Z > 2.99  zone sûre
    1.81–2.99 zone grise (à un an de la détresse)
    Z < 1.81  zone de détresse  <-- déclencheur d'alerte

Avertissement de secteur (feuille de route §2) : le score n'est PAS fiable
pour les banques, les assurances et les REIT. L'appelant doit filtrer sur
companies.sector_group en amont.
"""


# CORRECTIF : la fonction s'appelait `alman_z` (coquille). Renommée
# `altman_z` pour correspondre au nom de la formule ; aucun autre module ne
# l'importait encore.
def altman_z(
    working_capital,
    total_assets,
    retained_earnings,
    ebit,
    market_value_debt,
    sales,
) -> float | None:
    """Renvoie le Z-score, ou None quand les données manquent.

    `float | None` est le mécanisme qui applique la règle produit « afficher
    'donnée manquante' plutôt qu'un faux score » : l'appelant DOIT gérer
    None (afficher « donnée manquante ») au lieu de se rabattre sur 0.0, qui
    ressemblerait à un score de détresse extrême.
    """
    # Garde 1 — dénominateur manquant : sans total_assets, chaque ratio est
    # indéfini (division par zéro). Le test « truthy » capture aussi 0 et None.
    if not total_assets:
        return None

    # TODO(phase 1) : calculer les cinq ratios et la somme pondérée, ex. :
    #   a = working_capital / total_assets
    #   b = retained_earnings / total_assets
    #   c = ebit / total_assets
    #   d = market_value_debt / total_assets   (voir note D dans la docstring)
    #   e = sales / total_assets
    #   return 1.2*a + 1.4*b + 3.3*c + 0.6*d + 1.0*e
    #
    # État actuel : chute à travers et renvoie None, c'est-à-dire que la
    # fonction est toujours « donnée manquante » — inoffensif (jamais un
    # faux score) mais inutile. Ne pas livrer tant que la formule ci-dessus
    # n'est pas implémentée et couverte par un test (tests/test_altman.py).
    return None
