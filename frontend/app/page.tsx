"use client";

// Page d'accueil : recherche d'entreprise par CIK.
// Composant client car il gère un formulaire et une navigation au submit ;
// la fiche (/company/[cik]) est, elle, rendue côté serveur pour le SEO
// (pages publiques indexables = canal d'acquisition gratuit, feuille de route §7).

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

export default function Home() {
  const router = useRouter();
  const [cik, setCik] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    // Un CIK SEC est un nombre (parfois padé sur 10 chiffres dans les URLs
    // EDGAR, ex. 0000320193 ; l'API accepte les deux formes grâce au cast int).
    const trimmed = cik.trim();
    if (!/^\d+$/.test(trimmed)) return; // champ vide ou non numérique : rien
    router.push(`/company/${trimmed}`);
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-3xl font-bold tracking-tight">
        Détecteur de risque financier
      </h1>
      <p className="mt-3 text-gray-600">
        Entrez le <strong>CIK</strong> d&apos;une entreprise américaine
        (identifiant SEC, un nombre) pour afficher sa fiche de risque. Exemples :
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex gap-2">
        <input
          type="text"
          inputMode="numeric"
          value={cik}
          onChange={(e) => setCik(e.target.value)}
          placeholder="ex. 320193"
          aria-label="CIK SEC"
          className="w-full rounded-lg border border-gray-300 px-4 py-2 focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-5 py-2 font-medium text-white hover:bg-blue-700"
        >
          Voir la fiche
        </button>
      </form>

      {/* Liens de démonstration : CIK réels connus (Apple, Tesla, Enron=faillite
          historique utile pour les tests futurs du backtest). */}
      <ul className="mt-6 flex flex-wrap gap-3 text-sm">
        {[
          { cik: "320193", label: "Apple" },
          { cik: "1318605", label: "Tesla" },
          { cik: "1045810", label: "Nvidia" },
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
