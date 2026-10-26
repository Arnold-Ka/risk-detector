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
    "Score estimé par un modèle d'apprentissage profond sur 3 à 5 exercices. Son pourcentage n'est pas une probabilité calibrée et il ne modifie pas le niveau global.",
};

// Formulations courtes pour le résumé destiné aux personnes qui découvrent
// l'analyse financière. Les noms et explications techniques restent dans les
// détails afin que le résumé ne remplace pas l'analyse complète.
export const SIMPLE_SIGNAL_COPY: Partial<
  Record<SignalType, { label: string; explanation: string }>
> = {
  altman: {
    label: "Solvabilité (score Altman Z)",
    explanation:
      "Un score fondé sur les actifs, les dettes, les bénéfices et la valeur boursière. Il classe un profil de risque ; ce n'est pas une probabilité de faillite.",
  },
  piotroski: {
    label: "Amélioration financière (score Piotroski F)",
    explanation:
      "Note de 0 à 9 fondée sur neuf critères comptables. Une note basse signifie que peu de critères sont favorables.",
  },
  beneish: {
    label: "Anomalies comptables possibles (score Beneish M)",
    explanation:
      "Repère des combinaisons de chiffres parfois associées à une manipulation. Une alerte n'est pas une preuve de fraude.",
  },
  divergence: {
    label: "Bénéfices et trésorerie",
    explanation: "Le bénéfice progresse alors que l'argent généré par l'activité baisse.",
  },
  runway: {
    label: "Réserves de trésorerie",
    explanation: "Estime combien de temps la trésorerie peut durer au rythme actuel.",
  },
  late_filing: {
    label: "Retards de déclaration à la SEC",
    explanation:
      "L'entreprise a signalé qu'un rapport annuel ou trimestriel ne serait pas déposé à temps.",
  },
  critical_8k: {
    label: "Événements importants (rapports SEC 8-K)",
    explanation:
      "Un rapport courant à la SEC signale un événement comme une faillite, un défaut de paiement ou une correction de comptes.",
  },
  insider_sales: {
    label: "Ventes déclarées par des dirigeants",
    explanation:
      "Compare la valeur des ventes déclarées par les dirigeants à la valeur boursière de l'entreprise. Une vente seule ne prouve pas un problème.",
  },
  net_debt_ebitda: {
    label: "Dette nette comparée aux résultats",
    explanation:
      "Estime combien d'années de résultats de l'activité représenteraient la dette restante après déduction de la trésorerie.",
  },
  dilution: {
    label: "Nombre d'actions",
    explanation: "Une hausse du nombre d'actions réduit la part détenue par chaque actionnaire.",
  },
};

export function simpleRiskSummary(level: Level | string): string {
  switch (level) {
    case "faible":
      return "Peu de signaux de risque détectés";
    case "modéré":
      return "Quelques points méritent attention";
    case "élevé":
      return "Plusieurs signaux de risque importants";
    case "critique":
      return "Le niveau de risque calculé est très élevé";
    default:
      return "Résumé du risque indisponible";
  }
}

export function isSectorScoreExcluded(sectorGroup: string | null): boolean {
  return sectorGroup === "bank" || sectorGroup === "insurance" || sectorGroup === "reit";
}

/** Badge coloré par sévérité (signaux) ou niveau (composite). */
export function badgeClass(severity: Severity | Level | string): string {
  switch (severity) {
    case "saine":
    case "faible":
      return "bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200";
    case "vigilance":
    case "modéré":
      return "bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-200";
    case "élevé":
      return "bg-orange-50 text-orange-900 ring-1 ring-inset ring-orange-200";
    case "défaillance":
    case "critique":
      return "bg-rose-50 text-rose-800 ring-1 ring-inset ring-rose-200";
    default:
      return "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200";
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

// --- « Ce qui a changé » depuis l'exercice précédent ------------------------
// Même règle que les alertes e-mail (app/alerts/changes.py) : on compare les
// composantes du composite du dernier exercice à celles de l'exercice
// précédent. Calcul fait ici à partir de l'historique déjà chargé par la
// fiche (GET /companies/{cik}/signals) : aucun appel d'API supplémentaire.

const SEVERITY_RANK: Record<string, number> = {
  saine: 0,
  vigilance: 1,
  défaillance: 2,
  faible: 0,
  modéré: 1,
  élevé: 2,
  critique: 3,
};

export type ComponentChange = {
  signalType: SignalType;
  // null = signal non calculé cet exercice-là (donnée manquante, jamais
  // assimilée à « saine »).
  before: string | null;
  after: string | null;
  beforeValue: number | null;
  afterValue: number | null;
  // true = aggravation, false = amélioration, null = apparition/disparition
  // (on ne peut pas dire si une donnée manquante est meilleure ou pire).
  worsened: boolean | null;
};

export type YearOverYear = {
  previousPeriod: string;
  currentPeriod: string;
  levelBefore: string;
  levelAfter: string;
  changes: ComponentChange[];
};

function componentsOf(signal: Signal): Record<string, string> {
  const raw = signal.details?.["components"];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
}

/**
 * Compare les deux derniers composites de l'historique.
 * null si moins de deux exercices ont un composite (rien à comparer).
 */
export function yearOverYear(history: Signal[]): YearOverYear | null {
  const composites = history
    .filter((s) => s.signal_type === "composite")
    .sort((a, b) => b.period_end.localeCompare(a.period_end));
  if (composites.length < 2) return null;
  const [current, previous] = composites;

  const valueAt = (type: string, period: string): number | null =>
    history.find((s) => s.signal_type === type && s.period_end === period)
      ?.value ?? null;

  const before = componentsOf(previous);
  const after = componentsOf(current);
  const changes = SIGNAL_ORDER.filter(
    (type) => (type in before || type in after) && before[type] !== after[type],
  ).map((type): ComponentChange => {
    const old = before[type] ?? null;
    const now = after[type] ?? null;
    return {
      signalType: type,
      before: old,
      after: now,
      beforeValue: valueAt(type, previous.period_end),
      afterValue: valueAt(type, current.period_end),
      worsened:
        old === null || now === null
          ? null
          : SEVERITY_RANK[now] > SEVERITY_RANK[old],
    };
  });

  return {
    previousPeriod: previous.period_end,
    currentPeriod: current.period_end,
    levelBefore: previous.severity,
    levelAfter: current.severity,
    changes,
  };
}

/** Hausse (1), baisse (-1) ou stabilité (0) entre deux niveaux composites. */
export function levelDirection(before: string, after: string): -1 | 0 | 1 {
  const delta = (SEVERITY_RANK[after] ?? 0) - (SEVERITY_RANK[before] ?? 0);
  return delta > 0 ? 1 : delta < 0 ? -1 : 0;
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
