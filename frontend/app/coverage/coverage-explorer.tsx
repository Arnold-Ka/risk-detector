"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { fetchCoverage, type CoverageResult, type CoverageStatus } from "@/lib/api";
import { badgeClass, simpleRiskSummary } from "@/lib/signals";

const PAGE_SIZE = 50;

const STATUS_COPY: Record<
  CoverageStatus,
  { label: string; className: string }
> = {
  scored: {
    label: "Score disponible",
    className: "bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200",
  },
  partial: {
    label: "Analyse partielle",
    className: "bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-200",
  },
  not_scored: {
    label: "Pas encore évaluée",
    className: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200",
  },
  not_comparable: {
    label: "Secteur non évalué",
    className: "bg-violet-50 text-violet-800 ring-1 ring-inset ring-violet-200",
  },
};

function formatDate(value: string | null): string {
  if (!value) return "Date indisponible";
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

export default function CoverageExplorer() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<CoverageResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    void fetchCoverage(query, offset, PAGE_SIZE)
      .then((response) => {
        if (active) setResult(response);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [offset, query, retryKey]);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setOffset(0);
    setQuery(input.trim());
  }

  const page = result?.state === "ready" ? result.page : null;
  const totalPages = page ? Math.ceil(page.total / PAGE_SIZE) : 0;
  const currentPage = page ? Math.floor(page.offset / page.limit) + 1 : 1;

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-white shadow-sm">
      <div className="flex flex-col gap-4 border-b border-line p-5 sm:p-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-bold tracking-[0.12em] text-brand">
            RÉPERTOIRE DE CETTE BASE
          </p>
          <h2 className="mt-1 text-xl font-semibold text-ink">
            {page ? `${page.total.toLocaleString("fr-FR")} fiches disponibles` : "Rechercher une entreprise"}
          </h2>
          <p className="mt-1 text-sm text-muted">
            Une fiche présente ne signifie pas toujours que tous ses signaux sont calculables.
          </p>
        </div>
        <form onSubmit={search} className="flex w-full gap-2 lg:max-w-md">
          <label htmlFor="coverage-search" className="sr-only">
            Rechercher dans les entreprises disponibles
          </label>
          <input
            id="coverage-search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Nom, symbole ou CIK"
            className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-slate-50 px-3.5 text-sm text-ink outline-none transition placeholder:text-slate-400 focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
          />
          <button
            type="submit"
            className="h-11 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
          >
            Rechercher
          </button>
        </form>
      </div>

      <div className="border-b border-line bg-slate-50/80 px-5 py-3 text-xs leading-5 text-muted sm:px-6">
        Cette liste reflète les entreprises chargées dans cette base, pas
        l&apos;ensemble des sociétés cotées aux États-Unis. Le score est une
        indication, jamais une probabilité de faillite.
      </div>

      {result?.state === "error" && (
        <div role="alert" className="m-5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 sm:m-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{result.message}</span>
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                setRetryKey((current) => current + 1);
              }}
              className="font-semibold underline underline-offset-2"
            >
              Réessayer
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-3 p-5 sm:p-6" aria-label="Chargement des entreprises">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="h-16 animate-pulse rounded-xl bg-slate-100" />
          ))}
        </div>
      ) : page && page.items.length > 0 ? (
        <ul className="divide-y divide-line/70">
          {page.items.map((company) => {
            const status = STATUS_COPY[company.status];
            return (
              <li key={company.cik}>
                <Link
                  href={`/company/${company.cik}`}
                  className="flex flex-col gap-3 px-5 py-4 transition hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-ink">
                      {company.name}
                      {company.ticker && (
                        <span className="ml-2 text-sm font-medium text-muted">
                          {company.ticker}
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block text-xs text-muted">
                      CIK {company.cik}
                      {company.period_end && ` · Dernier exercice : ${company.period_end.slice(0, 4)}`}
                    </span>
                    {company.status === "partial" && company.missing_components > 0 && (
                      <span className="mt-1 block text-xs text-amber-800">
                        {company.missing_components === 1
                          ? "1 signal n'a pas pu être calculé"
                          : `${company.missing_components} signaux n'ont pas pu être calculés`}
                        {" "}faute de données ou de prise en charge du formulaire.
                      </span>
                    )}
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${status.className}`}>
                      {status.label}
                    </span>
                    {company.level && (
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass(company.level)}`}>
                        {simpleRiskSummary(company.level)}
                      </span>
                    )}
                    {company.computed_at && (
                      <span className="text-xs text-muted">
                        Mise à jour {formatDate(company.computed_at)}
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : !result || (result.state === "ready" && page?.total === 0) ? (
        <p className="px-5 py-12 text-center text-sm text-muted sm:px-6">
          Aucune entreprise trouvée dans les données actuellement chargées.
        </p>
      ) : result.state === "ready" ? (
        <p className="px-5 py-12 text-center text-sm text-muted sm:px-6">
          Aucune autre entreprise sur cette page.
        </p>
      ) : null}

      {page && page.total > 0 && (
        <footer className="flex items-center justify-between gap-4 border-t border-line px-5 py-4 sm:px-6">
          <p className="text-xs text-muted">
            Page {currentPage} sur {Math.max(totalPages, 1)}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => {
                setLoading(true);
                setOffset(Math.max(0, offset - PAGE_SIZE));
              }}
              className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Précédent
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= page.total || loading}
              onClick={() => {
                setLoading(true);
                setOffset(offset + PAGE_SIZE);
              }}
              className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Suivant
            </button>
          </div>
        </footer>
      )}
    </section>
  );
}
