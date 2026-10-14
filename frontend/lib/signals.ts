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
  if (value === null) return "donnée manquante";
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
