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
//
// Règle produit affichée ici : jamais de score inventé — une donnée
// absente s'affiche comme « donnée manquante », avec le pourquoi quand le
// composite le signale (details.absent).

import type { Metadata } from "next";
import { Suspense } from "react";
import {
  fetchCompany,
  fetchSignalHistory,
  type Signal,
} from "@/lib/api";
import {
  SIGNAL_HINTS,
  SIGNAL_LABELS,
  SIGNAL_ORDER,
  absentSignals,
  badgeClass,
  formatValue,
} from "@/lib/signals";
import ScoreChart from "./score-chart";

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
  // Parallèle : identité+signaux récents et historique complet sont deux
  // endpoints indépendants — inutile de les chaîner.
  const [result, history] = await Promise.all([
    fetchCompany(Number(cik)),
    fetchSignalHistory(Number(cik)),
  ]);

  if (result.state === "error") {
    return (
      <section className="mt-2 rounded-xl border border-gray-200 p-6">
        <p className="text-red-700">{result.message}</p>
      </section>
    );
  }

  if (result.state === "not-found") {
    return (
      <section className="mt-2 rounded-xl border border-gray-200 p-6">
        <p className="text-gray-700">
          Aucune donnée pour le CIK {cik} : entreprise inconnue de la SEC ou
          encore non ingérée dans la base. Seules les entreprises chargées en
          base ont une fiche — jamais de score affiché sans données derrière.
        </p>
      </section>
    );
  }

  const { company } = result;
  const byType = new Map(company.signals.map((s) => [s.signal_type, s]));
  const composite = byType.get("composite");
  const absent = absentSignals(composite);
  // Signaux présents, dans l'ordre de la feuille de route (composite d'abord).
  const ordered = SIGNAL_ORDER.map((t) => byType.get(t)).filter(
    (s): s is Signal => s !== undefined,
  );

  return (
    <section className="mt-2 space-y-6">
      {/* Identité */}
      <div className="rounded-xl border border-gray-200 p-6">
        <p className="mb-1 text-sm text-gray-500">CIK {cik}</p>
        <h2 className="text-xl font-semibold">
          {company.name}
          {company.ticker && (
            <span className="ml-2 text-base font-normal text-gray-500">
              {company.ticker}
            </span>
          )}
        </h2>
        {company.sector_group && (
          <p className="mt-1 text-sm text-gray-500">Secteur : {company.sector_group}</p>
        )}
      </div>

      {/* Score global, mis en avant */}
      {composite && (
        <div className="rounded-xl border border-gray-200 p-6">
          <p className="text-sm text-gray-500">Niveau de risque global</p>
          <p className="mt-2 flex items-center gap-3">
            <span
              className={`rounded-full px-3 py-1 text-lg font-semibold ${badgeClass(
                composite.severity,
              )}`}
            >
              {composite.severity}
            </span>
            <span className="text-gray-600">{formatValue("composite", composite.value)}</span>
          </p>
          <p className="mt-3 text-sm text-gray-600">{SIGNAL_HINTS.composite}</p>
          {absent.length > 0 && (
            <p className="mt-2 text-sm text-amber-700">
              Signaux non calculés (donnée manquante) : {absent.join(", ")}.
            </p>
          )}
        </div>
      )}

      {/* Liste des signaux unitaires */}
      <div className="rounded-xl border border-gray-200 p-6">
        <h3 className="font-semibold">Signaux détaillés</h3>
        <ul className="mt-4 divide-y divide-gray-100">
          {ordered
            .filter((s) => s.signal_type !== "composite")
            .map((signal) => (
              <li key={signal.signal_type} className="py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {SIGNAL_LABELS[signal.signal_type]}
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-sm font-medium ${badgeClass(
                      signal.severity,
                    )}`}
                  >
                    {signal.severity}
                  </span>
                </div>
                <p className="mt-1 text-sm text-gray-700">
                  {formatValue(signal.signal_type, signal.value)}
                  <span className="text-gray-500">
                    {" "}
                    — exercice clos le {signal.period_end}
                  </span>
                </p>
                <p className="mt-1 text-sm text-gray-500">
                  {SIGNAL_HINTS[signal.signal_type]}
                </p>
                {signal.filing_url && (
                  <a
                    href={signal.filing_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-block text-sm text-blue-600 hover:underline"
                  >
                    Voir le dépôt source (SEC) ↗
                  </a>
                )}
              </li>
            ))}
        </ul>
        {ordered.filter((s) => s.signal_type !== "composite").length === 0 && (
          <p className="mt-3 text-gray-600">
            <em>Données manquantes</em> — aucun signal n&apos;a pu être calculé
            pour cette entreprise. Un score inventé ne sera jamais affiché.
          </p>
        )}
      </div>

      {/* Graphique d'évolution (feuille de route §9) : données complètes
          de l'historique, rendu interactif côté client. */}
      {history.state === "ready" && history.signals.length > 0 && (
        <div className="rounded-xl border border-gray-200 p-6">
          <h3 className="font-semibold">Évolution sur 5 ans</h3>
          <div className="mt-3">
            <ScoreChart signals={history.signals} />
          </div>
        </div>
      )}

      {/* Avertissement légal (feuille de route §9) */}
      <p className="text-xs text-gray-500">
        Ces scores sont des indicateurs statistiques publiés à titre
        d&apos;information : ils ne constituent pas un conseil en
        investissement. Chaque score est recalculé la nuit à partir des
        dépôts SEC liés ci-dessus.
      </p>
    </section>
  );
}
