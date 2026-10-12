// Client HTTP typé vers le backend FastAPI.
// Centralisé ici pour qu'il n'y ait qu'un seul endroit à changer si l'URL
// d'API bouge (dev vs prod). Les types reflètent les réponses de app/api/.
//
// URL : variable d'environnement NEXT_PUBLIC_API_URL (lue côté navigateur
// ET côté serveur). Next.js ne lit que les .env de son propre dossier
// (frontend/) — en dev, le fallback ci-dessous suffit, en prod on posera
// frontend/.env.local.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Miroir du modèle Company de l'API (phase 1 : enrichi depuis la table companies).
export type Company = {
  cik: number;
  name: string;
  ticker: string | null;
};

// Résultat explicite de la recherche : jamais d'erreur silencieuse.
// - ready           : l'API a répondu, on a les données
// - not-implemented : l'API répond 501 volontairement (squelette phase 1)
// - error           : API injoignable ou erreur inattendue
export type CompanyResult =
  | { state: "ready"; company: Company }
  | { state: "not-implemented" }
  | { state: "error"; message: string };

export async function fetchCompany(cik: number): Promise<CompanyResult> {
  try {
    const res = await fetch(`${BASE}/companies/${cik}`, {
      // Pas de cache : la fiche sera mise à jour chaque nuit, on verra les
      // nouveaux signaux dès le rechargement.
      cache: "no-store",
    });

    if (res.status === 501) {
      return { state: "not-implemented" };
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
