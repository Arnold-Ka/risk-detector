"use client";

// Page d'accueil : recherche d'entreprise par nom ou symbole boursier
// (feuille de route §9), avec repli CIK numérique en accès direct.
// Composant client car il gère un formulaire, un appel API et une
// navigation ; la fiche (/company/[cik]) est, elle, rendue côté serveur
// pour le SEO (pages publiques indexables = canal d'acquisition gratuit).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { searchCompanies, type SearchState } from "@/lib/api";
import {
  badgeClass,
  isSectorScoreExcluded,
  simpleRiskSummary,
} from "@/lib/signals";

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
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6 sm:pt-14 lg:px-8 lg:pt-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1.08fr_0.92fr] lg:gap-14">
        <div className="max-w-2xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-brand/15 bg-brand-soft px-3 py-1.5 text-xs font-bold tracking-wide text-brand">
            <span className="size-1.5 rounded-full bg-brand" />
            DONNÉES PUBLIQUES · ÉTATS-UNIS
          </span>
          <h1 className="mt-6 text-4xl font-semibold tracking-tight text-ink sm:text-5xl sm:leading-[1.12] lg:text-[3.5rem]">
            Les signaux financiers,
            <span className="block text-brand">enfin plus clairs.</span>
          </h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">
            Comprenez rapidement ce qui mérite attention dans les comptes d&apos;une
            entreprise. Commencez par le résumé ; explorez les détails seulement
            si vous le souhaitez.
          </p>

          <div className="mt-8 rounded-2xl border border-line bg-white p-4 shadow-[0_16px_50px_-32px_rgba(18,43,64,0.35)] sm:p-6">
            <form onSubmit={onSubmit}>
              <label
                htmlFor="company-search"
                className="mb-2 block text-sm font-semibold text-ink"
              >
                Quelle entreprise souhaitez-vous comprendre ?
              </label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="relative min-w-0 flex-1">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-slate-400"
                  >
                    <circle cx="10.8" cy="10.8" r="6.3" stroke="currentColor" strokeWidth="1.8" />
                    <path d="m15.5 15.5 4 4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
                  </svg>
                  <input
                    id="company-search"
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Ex. Apple ou AAPL"
                    aria-label="Nom ou symbole boursier"
                    autoComplete="off"
                    className="h-12 w-full rounded-xl border border-line bg-slate-50 pl-11 pr-4 text-sm text-ink outline-none transition placeholder:text-slate-400 focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-wait disabled:opacity-70"
                >
                  {loading ? "Recherche…" : "Voir le résumé"}
                  {!loading && (
                    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-4">
                      <path d="M4 10h11m-4-4 4 4-4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
                    </svg>
                  )}
                </button>
              </div>
            </form>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <span className="mr-1 text-xs font-medium text-muted">
                À découvrir :
              </span>
              {[
                { cik: "320193", label: "Apple", ticker: "AAPL" },
                { cik: "1411579", label: "AMC", ticker: "AMC" },
                { cik: "886158", label: "Bed Bath & Beyond", ticker: null },
              ].map((company) => (
                <Link
                  key={company.cik}
                  href={`/company/${company.cik}`}
                  className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink/80 transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                >
                  {company.label}
                  {company.ticker && (
                    <span className="ml-1.5 font-medium text-muted">
                      {company.ticker}
                    </span>
                  )}
                </Link>
              ))}
            </div>
            <Link
              href="/coverage"
              className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-brand transition hover:text-brand-dark hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            >
              Voir les entreprises actuellement couvertes
              <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>

        <aside className="relative isolate overflow-hidden rounded-[2rem] bg-[#14283f] p-7 text-white shadow-[0_28px_70px_-38px_rgba(15,38,60,0.65)] sm:p-9 lg:p-10">
          <div aria-hidden="true" className="absolute -right-20 -top-24 -z-10 size-72 rounded-full bg-brand/35 blur-3xl" />
          <div aria-hidden="true" className="absolute -bottom-32 -left-16 -z-10 size-72 rounded-full bg-cyan-500/15 blur-3xl" />
          <div className="flex items-center gap-2 text-xs font-bold tracking-[0.16em] text-teal-200">
            <span className="size-2 rounded-full bg-teal-300" />
            UNE LECTURE EN 3 ÉTAPES
          </div>
          <h2 className="mt-5 max-w-sm text-2xl font-semibold tracking-tight sm:text-3xl">
            Les chiffres racontent une histoire. Voici comment la lire.
          </h2>

          <ol className="mt-8 space-y-6">
            {[
              {
                number: "01",
                title: "Un résumé d'abord",
                text: "Un niveau global, fondé sur les indicateurs disponibles.",
              },
              {
                number: "02",
                title: "Les raisons ensuite",
                text: "Les principaux points d'attention expliqués simplement.",
              },
              {
                number: "03",
                title: "Les sources à portée de main",
                text: "Chaque indicateur détaillé renvoie aux dépôts publics.",
              },
            ].map((step) => (
              <li key={step.number} className="flex gap-4">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white/5 text-xs font-bold text-teal-200">
                  {step.number}
                </span>
                <div>
                  <h3 className="text-sm font-semibold text-white">{step.title}</h3>
                  <p className="mt-1 text-sm leading-5 text-slate-300">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-8 border-t border-white/10 pt-5 text-xs leading-5 text-slate-300">
            Information utile, pas une prédiction de faillite ni un conseil
            d&apos;investissement.
          </div>
        </aside>
      </section>

      <section className="mt-10" aria-live="polite">
        {search?.state === "error" && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">
            <p className="font-semibold">La recherche n&apos;a pas abouti.</p>
            <p className="mt-1">{search.message}</p>
          </div>
        )}

        {search?.state === "ready" && search.results.length === 0 && (
          <div className="rounded-2xl border border-line bg-white p-5 shadow-sm">
            <p className="font-semibold text-ink">Aucune fiche trouvée</p>
            <p className="mt-1 text-sm text-muted">
              Vérifiez l&apos;orthographe ou essayez le symbole boursier de l&apos;entreprise.
            </p>
          </div>
        )}

        {search?.state === "ready" && search.results.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-line bg-white shadow-sm">
            <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line px-5 py-4 sm:px-6">
              <div>
                <p className="text-xs font-bold tracking-[0.12em] text-brand">
                  RÉSULTATS DE RECHERCHE
                </p>
                <h2 className="mt-1 text-lg font-semibold text-ink">
                  Choisissez une entreprise
                </h2>
              </div>
              <span className="text-sm text-muted">
                {search.results.length} résultat{search.results.length === 1 ? "" : "s"}
              </span>
            </div>
            <ul className="divide-y divide-line/70">
              {search.results.map((company) => {
                const excludedSector = isSectorScoreExcluded(company.sector_group);
                return (
                  <li key={company.cik}>
                    <Link
                      href={`/company/${company.cik}`}
                      className="flex flex-col gap-3 px-5 py-4 transition hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                    >
                      <span>
                        <span className="block font-semibold text-ink">{company.name}</span>
                        <span className="mt-0.5 block text-sm text-muted">
                          {company.ticker ?? "Symbole non disponible"}
                        </span>
                      </span>
                      <span
                        className={`w-fit max-w-full rounded-full px-3 py-1.5 text-xs font-semibold ${
                          company.level && !excludedSector
                            ? badgeClass(company.level)
                            : "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200"
                        }`}
                      >
                        {excludedSector
                          ? "Scores non comparables pour ce secteur"
                          : company.level
                            ? simpleRiskSummary(company.level)
                            : "Résumé indisponible"}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>
    </main>
  );
}
