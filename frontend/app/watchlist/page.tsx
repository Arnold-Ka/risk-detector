// Liste de suivi — placeholder jusqu'à la phase 2 (comptes utilisateurs +
// table watchlists, feuille de route §7). Page server component statique.
//
// noindex : page vide = contenu mince, les moteurs ne doivent pas
// l'indexer (elle est aussi exclue de sitemap.ts).

import type { Metadata } from "next";
import Link from "next/link";
import WatchlistManager from "./watchlist-manager";

export const metadata: Metadata = {
  title: "Ma liste de suivi",
  robots: { index: false },
};

export default function WatchlistPage() {
  const watchlistConfigured = Boolean(
      process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
      process.env.CLERK_SECRET_KEY &&
      process.env.WATCHLIST_API_SECRET &&
      process.env.WATCHLIST_API_SECRET.length >= 32,
  );

  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6 sm:pt-14 lg:px-8">
      <header className="mb-7">
        <p className="text-xs font-bold tracking-[0.14em] text-brand">
          ESPACE PERSONNEL
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
          Votre liste de suivi
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Retrouvez les entreprises que vous souhaitez consulter régulièrement.
        </p>
      </header>
      {watchlistConfigured ? (
        <WatchlistManager />
      ) : (
        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-6 sm:p-8">
          <p className="text-xs font-bold tracking-[0.12em] text-amber-800">
            CONFIGURATION À TERMINER
          </p>
          <h2 className="mt-2 text-xl font-semibold text-ink">
            La connexion aux comptes n&apos;est pas encore activée
          </h2>
          <p className="mt-2 max-w-2xl leading-6 text-slate-600">
            Configurez Clerk et la clé privée de liaison avec l&apos;API pour
            enregistrer des entreprises en toute sécurité.
          </p>
          <Link
            href="/"
            className="mt-6 inline-flex rounded-xl border border-amber-300 bg-white px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-amber-100"
          >
            Rechercher une entreprise
          </Link>
        </section>
      )}
    </main>
  );
}
