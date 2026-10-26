import type { Metadata } from "next";
import CoverageExplorer from "./coverage-explorer";

export const metadata: Metadata = {
  title: "Entreprises couvertes — Détecteur de risque financier",
  description:
    "Consultez les entreprises présentes dans la base et vérifiez l'état de leurs analyses financières.",
  robots: { index: false },
};

export default function CoveragePage() {
  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6 sm:pt-14 lg:px-8">
      <header className="mb-8">
        <p className="text-xs font-bold tracking-[0.14em] text-brand">
          PÉRIMÈTRE DE L&apos;ANALYSE
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Entreprises disponibles
        </h1>
        <p className="mt-3 max-w-3xl leading-6 text-muted">
          Parcourez les entreprises actuellement présentes dans la base et voyez
          si un résumé financier est disponible. Cette liste ne représente pas
          toutes les sociétés cotées aux États-Unis.
        </p>
      </header>
      <CoverageExplorer />
    </main>
  );
}
