"use client";

import { SignInButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { Level } from "@/lib/api";
import { badgeClass, simpleRiskSummary } from "@/lib/signals";

type WatchlistItem = {
  cik: number;
  name: string;
  ticker: string | null;
  added_at: string;
  level: Level | null;
};

type WatchlistResponse = {
  items: WatchlistItem[];
  limit: number;
};

async function responseMessage(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as
    | { detail?: unknown }
    | null;
  return typeof body?.detail === "string"
    ? body.detail
    : "Une erreur est survenue. Réessayez dans un instant.";
}

export default function WatchlistManager() {
  const { isLoaded, isSignedIn, userId } = useAuth();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loadedUserId, setLoadedUserId] = useState<string | null>(null);
  const [limit, setLimit] = useState(10);
  const [loading, setLoading] = useState(false);
  const [pendingCik, setPendingCik] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadWatchlist = useCallback(async (): Promise<WatchlistResponse> => {
    const response = await fetch("/api/watchlist", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await responseMessage(response));
    }
    return (await response.json()) as WatchlistResponse;
  }, []);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !userId) return;
    let active = true;
    void loadWatchlist()
      .then((data) => {
        if (!active) return;
        setItems(data.items);
        setLimit(data.limit);
        setError(null);
        setLoadedUserId(userId);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setItems([]);
        setError(
          cause instanceof Error
            ? cause.message
            : "Impossible de charger votre liste pour le moment.",
        );
        setLoadedUserId(userId);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isLoaded, isSignedIn, userId, loadWatchlist]);

  async function removeCompany(cik: number) {
    setPendingCik(cik);
    setError(null);
    try {
      const response = await fetch(`/api/watchlist?cik=${cik}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await responseMessage(response));
      setItems((current) => current.filter((item) => item.cik !== cik));
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Impossible de retirer cette entreprise.",
      );
    } finally {
      setPendingCik(null);
    }
  }

  if (!isLoaded) {
    return (
      <div className="animate-pulse rounded-3xl border border-line bg-white p-8 shadow-sm">
        <div className="h-4 w-36 rounded bg-slate-200" />
        <div className="mt-5 h-20 rounded-2xl bg-slate-100" />
      </div>
    );
  }

  if (!isSignedIn) {
    return (
      <section className="rounded-3xl border border-line bg-white p-8 shadow-sm sm:p-10">
        <span className="flex size-12 items-center justify-center rounded-2xl bg-brand-soft text-brand">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="size-6">
            <path d="M7 4.75h10A2.25 2.25 0 0 1 19.25 7v13l-7.25-4-7.25 4V7A2.25 2.25 0 0 1 7 4.75Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
          </svg>
        </span>
        <h2 className="mt-5 text-2xl font-semibold tracking-tight text-ink">
          Connectez-vous pour retrouver vos entreprises
        </h2>
        <p className="mt-2 max-w-xl leading-6 text-muted">
          Votre sélection est privée et liée à votre compte. Vous pourrez y
          enregistrer jusqu&apos;à {limit} entreprises.
        </p>
        <SignInButton mode="modal">
          <button className="mt-6 rounded-xl bg-brand px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
            Connexion / inscription
          </button>
        </SignInButton>
      </section>
    );
  }

  const currentItems = userId && loadedUserId === userId ? items : [];
  const currentError = userId && loadedUserId === userId ? error : null;
  const currentLoading = loading || !userId || loadedUserId !== userId;

  return (
    <section className="overflow-hidden rounded-3xl border border-line bg-white shadow-sm">
      <div className="flex flex-col gap-4 border-b border-line bg-white p-5 sm:flex-row sm:items-center sm:justify-between sm:p-7">
        <div>
          <p className="text-xs font-bold tracking-[0.13em] text-brand">
            VOTRE ESPACE PERSONNEL
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight text-ink">
            Entreprises suivies
          </h2>
          <p className="mt-1 text-sm text-muted">
            Gardez vos analyses importantes à portée de main.
          </p>
        </div>
        <div className="min-w-40 rounded-2xl bg-slate-50 px-4 py-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-semibold text-ink">
              {currentItems.length} sur {limit}
            </span>
            <span className="text-xs text-muted">entreprises</span>
          </div>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200"
            role="progressbar"
            aria-label="Nombre d'entreprises suivies"
            aria-valuenow={currentItems.length}
            aria-valuemin={0}
            aria-valuemax={limit}
          >
            <div
              className="h-full rounded-full bg-brand transition-[width]"
              style={{ width: `${Math.min((currentItems.length / limit) * 100, 100)}%` }}
            />
          </div>
        </div>
      </div>

      {currentError && (
        <div
          role="alert"
          className="mx-5 mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 sm:mx-7"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{currentError}</span>
            <button
              type="button"
              onClick={() => {
                if (!userId) return;
                setLoading(true);
                setError(null);
                void loadWatchlist()
                  .then((data) => {
                    setItems(data.items);
                    setLimit(data.limit);
                    setLoadedUserId(userId);
                  })
                  .catch((cause: unknown) => {
                    setItems([]);
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Impossible de charger votre liste pour le moment.",
                    );
                    setLoadedUserId(userId);
                  })
                  .finally(() => setLoading(false));
              }}
              className="font-semibold underline underline-offset-2"
            >
              Réessayer
            </button>
          </div>
        </div>
      )}

      {currentLoading ? (
        <div className="space-y-3 p-5 sm:p-7" aria-label="Chargement de la liste">
          {[0, 1, 2].map((row) => (
            <div key={row} className="h-16 animate-pulse rounded-xl bg-slate-100" />
          ))}
        </div>
      ) : currentItems.length === 0 ? (
        <div className="px-5 py-12 text-center sm:px-7">
          <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-brand-soft text-brand">
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="size-6">
              <path d="M7 4.75h10A2.25 2.25 0 0 1 19.25 7v13l-7.25-4-7.25 4V7A2.25 2.25 0 0 1 7 4.75Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
            </svg>
          </span>
          <h3 className="mt-4 text-lg font-semibold text-ink">
            Votre liste est encore vide
          </h3>
          <p className="mt-1 text-sm text-muted">
            Ajoutez une entreprise depuis sa fiche pour la retrouver ici.
          </p>
          <Link
            href="/"
            className="mt-5 inline-flex rounded-xl border border-line px-4 py-2.5 text-sm font-semibold text-ink transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand"
          >
            Explorer les entreprises
          </Link>
        </div>
      ) : (
        <ul className="divide-y divide-line/70">
          {currentItems.map((item) => (
            <li
              key={item.cik}
              className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7"
            >
              <Link
                href={`/company/${item.cik}`}
                className="min-w-0 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
              >
                <span className="block truncate font-semibold text-ink">
                  {item.name}
                  {item.ticker && (
                    <span className="ml-2 text-sm font-medium text-muted">
                      {item.ticker}
                    </span>
                  )}
                </span>
                <span className="mt-1 block text-xs text-muted">
                  Ajoutée le {new Date(item.added_at).toLocaleDateString("fr-FR", { timeZone: "UTC" })}
                </span>
              </Link>
              <div className="flex items-center justify-between gap-3 sm:justify-end">
                {item.level ? (
                  <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${badgeClass(item.level)}`}>
                    {simpleRiskSummary(item.level)}
                  </span>
                ) : (
                  <span className="text-xs text-muted">Résumé indisponible</span>
                )}
                <button
                  type="button"
                  onClick={() => void removeCompany(item.cik)}
                  disabled={pendingCik === item.cik}
                  aria-label={`Retirer ${item.name} de votre liste`}
                  className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-50"
                >
                  {pendingCik === item.cik ? "Retrait…" : "Retirer"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
