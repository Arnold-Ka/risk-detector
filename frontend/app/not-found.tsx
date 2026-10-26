import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-6xl items-center px-4 py-12 sm:px-6 lg:px-8">
      <section className="mx-auto w-full max-w-2xl rounded-3xl border border-line bg-white p-8 shadow-sm sm:p-12">
        <p className="text-xs font-bold tracking-[0.14em] text-brand">
          ERREUR 404
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Cette page est introuvable
        </h1>
        <p className="mt-3 max-w-lg leading-6 text-muted">
          Le lien est peut-être incorrect ou la page a été déplacée. Vous pouvez
          revenir à la recherche d&apos;entreprise.
        </p>
        <Link
          href="/"
          className="mt-7 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-3 text-sm font-semibold text-white transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Retour à l&apos;accueil
          <span aria-hidden="true">→</span>
        </Link>
      </section>
    </main>
  );
}
