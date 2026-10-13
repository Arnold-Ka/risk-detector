"use client";

// Page d'accueil : recherche d'entreprise par nom ou symbole boursier
// (feuille de route §9), avec repli CIK numérique en accès direct.
// Composant client car il gère un formulaire, un appel API et une
// navigation ; la fiche (/company/[cik]) est, elle, rendue côté serveur
// pour le SEO (pages publiques indexables = canal d'acquisition gratuit).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { searchCompanies, type SearchState } from "@/lib/api";
import { badgeClass } from "@/lib/signals";

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<SearchState | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    // Un CIK est un identifiant exact : pas de recherche, accès direct
    // (comportement historique conservé pour les liens/partages existants).
    if (/^\d+$/.test(trimmed)) {
      setSearch(null);
      router.push(`/company/${trimmed}`);
      return;
    }

    setLoading(true);
    setSearch(await searchCompanies(trimmed));
    setLoading(false);
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-3xl font-bold tracking-tight">
        Détecteur de risque financier
      </h1>
      <p className="mt-3 text-gray-600">
        Entrez le <strong>nom</strong> ou le <strong>symbole boursier</strong>{" "}
        d&apos;une entreprise américaine (ou son CIK numérique) pour afficher
        sa fiche de risque. Exemples :
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ex. Apple, AAPL ou 320193"
          aria-label="Nom, symbole ou CIK"
          className="w-full rounded-lg border border-gray-300 px-4 py-2 focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-blue-600 px-5 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {loading ? "Recherche…" : "Rechercher"}
        </button>
      </form>

      {/* Résultats : jamais de liste fantôme — état vide/explicitement en erreur. */}
      {search?.state === "error" && (
        <p className="mt-4 text-red-700">{search.message}</p>
      )}

      {search?.state === "ready" && search.results.length === 0 && (
        <p className="mt-4 text-gray-600">
          Aucune entreprise trouvée. Seules les entreprises déjà ingérées en
          base apparaissent — la couverture s&apos;élargit à mesure que le
          pipeline collecte de nouveaux dépôts SEC.
        </p>
      )}

      {search?.state === "ready" && search.results.length > 0 && (
        <ul className="mt-4 divide-y divide-gray-100 rounded-xl border border-gray-200">
          {search.results.map((co) => (
            <li key={co.cik}>
              <a
                href={`/company/${co.cik}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-gray-50"
              >
                <span>
                  <span className="font-medium">{co.name}</span>
                  <span className="ml-2 text-sm text-gray-500">
                    {co.ticker ?? "sans symbole"} · CIK {co.cik}
                  </span>
                </span>
                {co.level && (
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-sm font-medium ${badgeClass(
                      co.level,
                    )}`}
                  >
                    {co.level}
                  </span>
                )}
              </a>
            </li>
          ))}
        </ul>
      )}

      {/* Liens de démonstration : le trio de validation de la phase 0
          (Apple saine / AMC en difficulté / BBBY faillie 2023) — seules
          entreprises ingérées en base pour l'instant. */}
      <ul className="mt-6 flex flex-wrap gap-3 text-sm">
        {[
          { cik: "320193", label: "Apple" },
          { cik: "1411579", label: "AMC" },
          { cik: "886158", label: "Bed Bath & Beyond" },
        ].map((co) => (
          <li key={co.cik}>
            <a
              href={`/company/${co.cik}`}
              className="rounded-full border border-gray-300 px-3 py-1 hover:bg-gray-100"
            >
              {co.label} <span className="text-gray-400">(CIK {co.cik})</span>
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}
