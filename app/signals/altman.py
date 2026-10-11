"""Altman Z-score — probability of financial distress within 2 years.

Inputs are the five raw variables of the formula, already normalized from
XBRL (phase 1 normalizer). They map to the classic ratios as:

    A = working_capital  / total_assets      (liquidity)
    B = retained_earnings / total_assets     (accumulated profitability)
    C = ebit             / total_assets      (operating profitability)
    D = market_value_debt / total_assets     <- NOTE: roadmap defines D as
        market value of equity / total debt; confirm the exact variant
        when implementing (public-manufacturer vs public-non-manufacturer
        Z-scores do not use the same coefficients).
    E = sales            / total_assets      (asset turnover)

    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0E

Interpretation thresholds (public manufacturing issuers):
    Z > 2.99  safe zone
    1.81-2.99 grey zone (one year from distress)
    Z < 1.81  distress zone  <-- the alert trigger

Sector caveat (roadmap §2): the score is NOT reliable for banks, insurers
and REITs. The caller must filter on companies.sector_group first.
"""


# BUGFIX: function was named `alman_z` (typo). Renamed to `altman_z` so it
# matches the formula's name; no other module imported it yet.
def altman_z(
    working_capital,
    total_assets,
    retained_earnings,
    ebit,
    market_value_debt,
    sales,
) -> float | None:
    """Return the Z-score, or None when data is missing.

    `float | None` is the mechanism enforcing the product rule "show
    'donnée manquante' rather than a wrong score": callers MUST handle None
    (display "data missing") instead of defaulting to 0.0, which would look
    like an extreme-distress score.
    """
    # Guard 1 — missing denominator: without total_assets every ratio is
    # undefined (division by zero). Falsy check also catches 0 and None.
    if not total_assets:
        return None

    # TODO(phase 1): compute the five ratios and the weighted sum, e.g.
    #   a = working_capital / total_assets
    #   b = retained_earnings / total_assets
    #   c = ebit / total_assets
    #   d = market_value_debt / total_assets   (see docstring note on D)
    #   e = sales / total_assets
    #   return 1.2*a + 1.4*b + 3.3*c + 0.6*d + 1.0*e
    #
    # Current state: falls through and returns None, i.e. the function is
    # still "always missing data" — harmless (never a fake score) but
    # useless. Do not ship until the formula above is implemented and
    # covered by a test (tests/test_altman.py).
    return None
