// Fiche de risque d'une entreprise, rendue côté SERVER COMPONENT :
// le fetch vers FastAPI se fait sur le serveur Next (pas dans le navigateur),
// ce qui rend la page indexable par Google et rapide à afficher.
//
// Conventions Next 16 (Cache Components) :
// - PageProps<'...'> est un helper global (généré par typegen/dev/build),
//   `params` est une Promise => on l'await ;
// - une page qui attend params + fetch doit isoler cette attente dans un
//   composant async placé sous <Suspense>, sinon `next build` refuse de
//   prerender la route ("uncached or runtime data ... outside of Suspense").
//   Ici : le squelette de page s'affiche instantanément, la donnée arrive
//   en streaming.

import type { Metadata } from "next";
import { Suspense } from "react";
import { fetchCompany, type CompanyResult } from "@/lib/api";

// Titre dynamique pour le SEO : la page entreprise doit être indexable
// (feuille de route §7 : pages publiques = trafic gratuit et durable).
export async function generateMetadata(
  props: PageProps<"/company/[cik]">,
): Promise<Metadata> {
  const { cik } = await props.params;
  return { title: `Fiche de risque — CIK ${cik}` };
}

export default function CompanyPage(props: PageProps<"/company/[cik]">) {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">Fiche de risque</h1>
      {/* Suspense : le fallback s'affiche pendant que params + fetch
          résolvent ; la page complète est streamée au navigateur. */}
      <Suspense
        fallback={<p className="mt-4 text-gray-500">Chargement…</p>}
      >
        <CompanySection params={props.params} />
      </Suspense>
    </main>
  );
}

// Composant async isolé : seul endroit qui attend params/fetch.
async function CompanySection({
  params,
}: {
  params: PageProps<"/company/[cik]">["params"];
}) {
  const { cik } = await params;
  const result: CompanyResult = await fetchCompany(Number(cik));

  return (
    <section className="mt-2 rounded-xl border border-gray-200 p-6">
      <p className="mb-3 text-sm text-gray-500">CIK {cik}</p>

      {result.state === "ready" && (
        <>
          <h2 className="text-xl font-semibold">{result.company.name}</h2>
          <p className="mt-2 text-gray-600">
            Signaux : <em>données manquantes</em> — le moteur de scores est
            prévu en phase 1. Aucun faux score ne sera jamais affiché.
          </p>
        </>
      )}

      {result.state === "not-implemented" && (
        <p className="text-gray-700">
          Cette fiche n&apos;est pas encore alimentée : l&apos;API répond
          volontairement « pas implémenté » (501) tant que la phase 1 n&apos;a
          pas rempli la base. Ici, une donnée manquante s&apos;affiche comme
          manquante — jamais comme un score inventé.
        </p>
      )}

      {result.state === "error" && <p className="text-red-700">{result.message}</p>}
    </section>
  );
}
