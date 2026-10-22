// Client HTTP typé vers le backend FastAPI.
// Centralisé ici pour qu'il n'y ait qu'un seul endroit à changer si l'URL
// d'API bouge (dev vs prod). Les types reflètent les réponses de app/api/
// (GET /companies/{cik} et GET /companies/{cik}/signals).
//
// URL : variable d'environnement NEXT_PUBLIC_API_URL (lue côté navigateur
// ET côté serveur). Next.js ne lit que les .env de son propre dossier
// (frontend/) — en dev, le fallback ci-dessous suffit, en prod on posera
// frontend/.env.local.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Miroir du modèle Company de l'API (identité depuis la table companies).
export type Company = {
  id: string;
  cik: number;
  name: string;
  ticker: string | null;
  sector_group: string | null;
  signals: Signal[];
};

// Un signal de la table `signals` (dernier par type sur /companies/{cik},
// historique complet sur /signals). `details` est du jsonb libre : sa forme
// dépend du signal_type (criteria, ratios, absent…), on le type en somme
// d'objets pour ne rien imposer de faux.
export type Signal = {
  signal_type: SignalType;
  period_end: string; // ISO YYYY-MM-DD (exercice)
  value: number | null; // None affiché comme « donnée manquante »
  severity: Severity | Level;
  details: Record<string, unknown> | null;
  computed_at: string;
  filing_id: string | null;
  // Lien vers le dépôt source (filings.url, EDGAR) ; NULL pour composite.
  filing_url: string | null;
};

export type SignalType =
  | "altman"
  | "piotroski"
  | "beneish"
  | "divergence"
  | "runway"
  | "late_filing"
  | "critical_8k"
  | "insider_sales"
  | "net_debt_ebitda"
  | "dilution"
  | "lstm"
  | "composite";

// Sévérités des signaux unitaires (mêmes libellés que le backend).
export type Severity = "saine" | "vigilance" | "défaillance";
// Niveaux du score composite (faible → critique).
export type Level = "faible" | "modéré" | "élevé" | "critique";

// Résultat explicite de la recherche : jamais d'erreur silencieuse.
// - ready     : l'API a répondu, on a les données
// - not-found : l'API répond 404 (CIK inconnu OU non ingéré en base)
// - error     : API injoignable ou erreur inattendue
export type CompanyResult =
  | { state: "ready"; company: Company }
  | { state: "not-found" }
  | { state: "error"; message: string };

export async function fetchCompany(cik: number): Promise<CompanyResult> {
  try {
    // Pas d'option de cache : avec les Cache Components de Next 16, tout
    // fetch hors scope `use cache` est déjà non mis en cache — la fiche
    // est relue à chaque requête et reflète le dernier calcul nocturne.
    const res = await fetch(`${BASE}/companies/${cik}`);

    if (res.status === 404) {
      return { state: "not-found" };
    }
    if (!res.ok) {
      return {
        state: "error",
        message: `L'API a répondu ${res.status} pour le CIK ${cik}.`,
      };
    }
    return { state: "ready", company: (await res.json()) as Company };
  } catch {
    // Fetch a échoué : le plus souvent, le backend FastAPI n'est pas lancé.
    return {
      state: "error",
      message:
        "Impossible de joindre l'API. " +
        "Lancez le backend : uv run uvicorn app.api.main:app --reload",
    };
  }
}

// Ligne de suggestion de recherche (GET /search) : identité + niveau
// composite le plus récent (null = entreprise non encore scorée — jamais
// de niveau inventé).
export type SearchResult = {
  cik: number;
  name: string;
  ticker: string | null;
  sector_group: string | null;
  level: Level | null;
};

// Résultat de recherche : « ready » avec une liste éventuellement vide
// (pas de résultat = réponse légitime, pas une erreur).
export type SearchState =
  | { state: "ready"; results: SearchResult[] }
  | { state: "error"; message: string };

export async function searchCompanies(query: string): Promise<SearchState> {
  try {
    const res = await fetch(
      `${BASE}/search?q=${encodeURIComponent(query)}`,
    );
    if (!res.ok) {
      return {
        state: "error",
        message: `L'API a répondu ${res.status} pour la recherche.`,
      };
    }
    return { state: "ready", results: (await res.json()) as SearchResult[] };
  } catch {
    return {
      state: "error",
      message:
        "Impossible de joindre l'API. " +
        "Lancez le backend : uv run uvicorn app.api.main:app --reload",
    };
  }
}

// Identité d'entreprise sans signaux (GET /companies) — sert le sitemap
// (§7 : pages publiques indexables) qui doit énumérer les CIK. L'identifiant
// public est le CIK ; l'uuid interne de la table companies n'est pas exposé.
export type CompanyRef = {
  cik: number;
  name: string;
  ticker: string | null;
  sector_group: string | null;
};

export type CompanyListResult =
  | { state: "ready"; results: CompanyRef[] }
  | { state: "error"; message: string };

export async function fetchCompanyList(): Promise<CompanyListResult> {
  try {
    const res = await fetch(`${BASE}/companies`);
    if (!res.ok) {
      return {
        state: "error",
        message: `L'API a répondu ${res.status} pour la liste des entreprises.`,
      };
    }
    return { state: "ready", results: (await res.json()) as CompanyRef[] };
  } catch {
    return {
      state: "error",
      message:
        "Impossible de joindre l'API. " +
        "Lancez le backend : uv run uvicorn app.api.main:app --reload",
    };
  }
}

// Historique complet des signaux (GET /companies/{cik}/signals) — sert le
// graphique d'évolution 5 ans de la fiche (feuille de route §9).
export type HistoryResult =
  | { state: "ready"; signals: Signal[] }
  | { state: "error"; message: string };

export async function fetchSignalHistory(cik: number): Promise<HistoryResult> {
  try {
    const res = await fetch(`${BASE}/companies/${cik}/signals`);
    if (!res.ok) {
      return {
        state: "error",
        message: `L'API a répondu ${res.status} pour l'historique du CIK ${cik}.`,
      };
    }
    const body = (await res.json()) as { signals: Signal[] };
    return { state: "ready", signals: body.signals };
  } catch {
    return {
      state: "error",
      message:
        "Impossible de joindre l'API. " +
        "Lancez le backend : uv run uvicorn app.api.main:app --reload",
    };
  }
}
