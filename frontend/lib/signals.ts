// Libellés, formats et couleurs des signaux — utilisés par la fiche
// entreprise. Tout texte visible par l'utilisateur est ici en français
// (convention du projet : prose utilisateur en FR, identifiants en code).

import type { Level, Severity, Signal, SignalType } from "./api";

// Ordre d'affichage sur la fiche : score global d'abord, puis les
// signaux unitaires dans l'ordre de la feuille de route §2.
export const SIGNAL_ORDER: SignalType[] = [
  "composite",
  "altman",
  "piotroski",
  "beneish",
  "divergence",
  "runway",
  "late_filing",
  "critical_8k",
  "insider_sales",
  "net_debt_ebitda",
  "dilution",
  "lstm",
];

export const SIGNAL_LABELS: Record<SignalType, string> = {
  composite: "Score global",
  altman: "Altman Z",
  piotroski: "Piotroski F",
  beneish: "Beneish M",
  divergence: "Écart bénéfice/cash",
  runway: "Autonomie de trésorerie",
  late_filing: "Dépôts en retard",
  critical_8k: "8-K critiques",
  insider_sales: "Ventes de dirigeants",
  net_debt_ebitda: "Dette nette / EBITDA",
  dilution: "Dilution d'actions",
  lstm: "Modèle séquentiel (LSTM)",
};

// Courte explication en langage simple (feuille de route §9 :
// « explication en langage simple » sur la fiche).
export const SIGNAL_HINTS: Record<SignalType, string> = {
  composite: "Moyenne pondérée des signaux disponibles — le niveau global de risque.",
  altman:
    "Solvabilité : actifs, capitaux propres et rentabilité. Sous 1,81 = zone de faillite.",
  piotroski:
    "0 à 9 critères comptables améliorés sur un an. 0-2 = entreprise fragile.",
  beneish:
    "Risque de manipulation des comptes. Au-dessus de -1,78 = suspect.",
  divergence:
    "Le bénéfice monte pendant que la trésorerie baisse : qualité des profits en doute.",
  runway:
    "Combien de mois de trésorerie au rythme actuel de consommation de cash.",
  late_filing:
    "Rapports trimestriels/annuels déposés après le délai (formulaires NT) — souvent un problème dans les comptes.",
  critical_8k:
    "Événements graves annoncés en 8-K : faillite, défaut de dette, comptes corrigés, changement d'auditeur, départ de dirigeant.",
  insider_sales:
    "Part des actions vendues par les dirigeants (officiers, administrateurs) sur un an. Au-dessus de 0,25 % du capital = vigilance, 1 % = défaillance.",
  net_debt_ebitda:
    "Dette long terme moins la trésorerie, rapportée au cash-flow brut généré. Au-dessus de 4 et en hausse = alerte de la feuille de route.",
  dilution:
    "Augmentation du nombre d'actions sur un an. Plus de 10 % = alerte, plus de 5 % = vigilance : les actionnaires sont dilués.",
  lstm:
    "Probabilité de faillite dans les 12 mois estimée par un modèle d'apprentissage profond sur les 3 à 5 derniers exercices (ratios comptables et événements de dépôt).",
};

/** Badge coloré par sévérité (signaux) ou niveau (composite). */
export function badgeClass(severity: Severity | Level | string): string {
  switch (severity) {
    case "saine":
    case "faible":
      return "bg-emerald-100 text-emerald-800";
    case "vigilance":
    case "modéré":
      return "bg-amber-100 text-amber-800";
    case "élevé":
      return "bg-orange-100 text-orange-800";
    case "défaillance":
    case "critique":
      return "bg-red-100 text-red-800";
    default:
      return "bg-gray-100 text-gray-700";
  }
}

/** Formatage de la valeur selon le type (null = donnée manquante). */
export function formatValue(type: SignalType, value: number | null): string {
  if (value === null) {
    // Valeur absente avec une EXISTENCE du signal : EBITDA ≤ 0 (la
    // sévérité est calculable, le ratio n'est pas — cf. leverage.py).
    return type === "net_debt_ebitda"
      ? "EBITDA ≤ 0"
      : "donnée manquante";
  }
  switch (type) {
    case "altman":
      return value.toFixed(2);
    case "piotroski":
      // Score entier stocké en float (sum de booléens).
      return `${Math.round(value)} / 9`;
    case "beneish":
      return value.toFixed(3);
    case "runway":
      return `${Math.round(value)} mois`;
    case "divergence":
      return value === 0 ? "aucun" : `${Math.round(value)} exercice(s)`;
    case "late_filing":
      return value === 0 ? "aucun" : `${Math.round(value)} dépôt(s) tardif(s)`;
    case "critical_8k":
      return value === 0 ? "aucun" : `${Math.round(value)} 8-K critique(s)`;
    case "insider_sales":
      // Valeur = ratio (part du capital vendue) ; 0 = aucune vente.
      return value === 0
        ? "aucune vente"
        : `${(value * 100).toFixed(2)} % du capital`;
    case "net_debt_ebitda":
      // Valeur = ratio (multiples de l'EBITDA) ; null = EBITDA ≤ 0.
      return `${value.toFixed(2)} × EBITDA`;
    case "dilution":
      // Valeur = croissance annuelle des parts (0.1 = +10 %).
      return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} % sur un an`;
    case "lstm":
      // Valeur = probabilité de faillite à 12 mois (0..1).
      return `${(value * 100).toFixed(1)} %`;
    case "composite":
      return `indice ${value.toFixed(1)} / 2`;
  }
}

/** Signaux absents du composite (« donnée manquante » à afficher). */
export function absentSignals(signal: Signal | undefined): string[] {
  const absent = signal?.details?.["absent"];
  if (!Array.isArray(absent)) return [];
  return absent
    .filter((name): name is string => typeof name === "string")
    .map((name) => SIGNAL_LABELS[name as SignalType] ?? name);
}

// --- Attribution SHAP du signal LSTM (« explication par variable ») ---------
// Clés = identifiants anglais des features du modèle (app/dl/attribution,
// ordre exact de dataset.vectorize) ; valeurs = libellés FR affichés.

export const FEATURE_LABELS: Record<string, string> = {
  cash: "Trésorerie",
  cfo: "Cash-flow opérationnel",
  current_assets: "Actifs circulants",
  current_liabilities: "Dettes circulantes",
  depreciation: "Amortissements",
  gross_profit: "Résultat brut",
  interest_expense: "Charges d'intérêts",
  inventory: "Stocks",
  long_term_debt: "Dettes long terme",
  net_income: "Résultat net",
  operating_income: "Résultat d'exploitation",
  ppe: "Immobilisations corporelles",
  receivables: "Créances clients",
  retained_earnings: "Résultats accumulés",
  sales: "Chiffre d'affaires",
  sga: "Frais généraux (SG&A)",
  stockholders_equity: "Capitaux propres",
  total_liabilities: "Dettes totales",
  critical_defaillance: "8-K critiques (faillite, défaut, comptes corrigés)",
  critical_vigilance: "8-K de surveillance (changement d'auditeur, dirigeant)",
  late_filing: "Rapports déposés en retard (formulaires NT)",
  events_missing: "Absence de données de dépôts",
};

/** Identifiant de feature -> libellé FR (suffixes ratio/manquant gérés). */
export function featureLabel(feature: string): string {
  if (feature.endsWith("_missing")) {
    const base = FEATURE_LABELS[feature.slice(0, -"_missing".length)];
    return `${base ?? feature.slice(0, -"_missing".length)} (manquant)`;
  }
  if (feature.endsWith("_ratio")) {
    const base = FEATURE_LABELS[feature.slice(0, -"_ratio".length)];
    return base ?? feature.slice(0, -"_ratio".length);
  }
  return FEATURE_LABELS[feature] ?? feature;
}

/**
 * Attribution SHAP du signal LSTM (top-k dans details.attribution) ->
 * [{label, value}] prêt à afficher ; [] si absente (historique, échec
 * SHAP, autre type de signal).
 */
export function attributionOf(
  signal: Signal | undefined,
): { label: string; value: number }[] {
  const raw = signal?.details?.["attribution"];
  if (!Array.isArray(raw)) return [];
  const out: { label: string; value: number }[] = [];
  for (const item of raw) {
    if (item && typeof item === "object") {
      const feature = (item as { feature?: unknown }).feature;
      const value = (item as { value?: unknown }).value;
      if (typeof feature === "string" && typeof value === "number") {
        out.push({ label: featureLabel(feature), value });
      }
    }
  }
  return out;
}
