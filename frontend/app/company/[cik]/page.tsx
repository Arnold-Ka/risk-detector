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
import Link from "next/link";
import { Suspense } from "react";
import {
  fetchCompany,
  fetchSignalHistory,
  type Signal,
  type SignalType,
} from "@/lib/api";
import {
  SIGNAL_HINTS,
  SIGNAL_LABELS,
  SIGNAL_ORDER,
  SIMPLE_SIGNAL_COPY,
  absentSignals,
  attributionOf,
  badgeClass,
  formatValue,
  isSectorScoreExcluded,
  simpleRiskSummary,
} from "@/lib/signals";
import ScoreChart from "./score-chart";
import WatchlistAction from "./watchlist-action";

function formatAnalysisDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(date);
}

function simpleSignalOutcome(signal: Signal): string {
  const { value, signal_type: type } = signal;
  const copy = SIMPLE_SIGNAL_COPY[type];
  if (value === null) return copy?.explanation ?? "Ce signal mérite attention.";

  switch (type) {
    case "piotroski":
      return `${Math.round(value)} critères financiers sur 9 sont favorables.`;
    case "runway":
      return `La trésorerie représente environ ${Math.round(value)} mois au rythme actuel.`;
    case "divergence":
      return `Cette divergence apparaît depuis ${Math.round(value)} exercice(s).`;
    case "late_filing":
      return `${Math.round(value)} rapport(s) ont été déposés en retard.`;
    case "critical_8k":
      return `${Math.round(value)} événement(s) important(s) ont été signalés.`;
    case "insider_sales":
      return `Les ventes déclarées par les dirigeants représentent ${(value * 100).toFixed(2)} % de la valeur boursière de l'entreprise.`;
    case "net_debt_ebitda":
      return `La dette nette représente ${value.toFixed(1)} fois les résultats de l'activité.`;
    case "dilution":
      return `Le nombre d'actions a augmenté de ${(value * 100).toFixed(1)} % sur un an.`;
    default:
      return copy?.explanation ?? "Ce signal mérite attention.";
  }
}

function severityRailClass(severity: string): string {
  switch (severity) {
    case "défaillance":
    case "critique":
      return "border-l-rose-500";
    case "élevé":
      return "border-l-orange-400";
    case "vigilance":
    case "modéré":
      return "border-l-amber-400";
    default:
      return "border-l-emerald-500";
  }
}

type WeightedComponent = {
  signalType: SignalType;
  severity: string;
  weight: number;
  contribution: number;
  signal?: Signal;
};

function formatWeight(weight: number): string {
  return `${weight.toLocaleString("fr-FR", { maximumFractionDigits: 1 })}×`;
}

function formatContribution(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toLocaleString("fr-FR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function SummarySignalCard({
  component,
  periodEnd,
}: {
  component: WeightedComponent;
  periodEnd: string;
}) {
  const copy = SIMPLE_SIGNAL_COPY[component.signalType];
  if (!copy) return null;

  return (
    <li
      className={`rounded-2xl border border-line border-l-4 bg-white p-5 shadow-[0_12px_36px_-30px_rgba(18,43,64,0.4)] ${severityRailClass(component.severity)}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-ink">{copy.label}</h3>
          <p className="mt-1 text-xs font-medium text-muted">
            Exercice {periodEnd.slice(0, 4)}
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass(component.severity)}`}>
          {component.severity === "défaillance" ? "Point important" : "À surveiller"}
        </span>
      </div>
      <p className="mt-4 text-sm leading-6 text-slate-600">
        {component.signal
          ? simpleSignalOutcome(component.signal)
          : copy.explanation}
      </p>
      <p className="mt-4 border-t border-line pt-3 text-xs font-medium text-muted">
        Poids {formatWeight(component.weight)}
        <span className="mx-1.5 text-slate-300">·</span>
        contribution {formatContribution(component.contribution)} point(s)
      </p>
      {component.signal?.filing_url && (
        <a
          href={component.signal.filing_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex text-xs font-semibold text-brand hover:text-brand-dark hover:underline"
        >
          Voir le dépôt source ↗
        </a>
      )}
    </li>
  );
}

function DetailedSignalCard({ signal }: { signal: Signal }) {
  return (
    <li className={`rounded-2xl border border-line border-l-4 bg-white p-5 shadow-sm ${severityRailClass(signal.severity)}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.1em] text-muted">
            {SIGNAL_LABELS[signal.signal_type]}
          </p>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-ink">
            {formatValue(signal.signal_type, signal.value)}
          </p>
          <p className="mt-1 text-xs text-muted">
            Exercice clos le {formatAnalysisDate(signal.period_end)}
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass(signal.severity)}`}>
          {signal.severity}
        </span>
      </div>
      <p className="mt-4 border-t border-line pt-3 text-sm leading-6 text-slate-600">
        {SIGNAL_HINTS[signal.signal_type]}
      </p>
      {signal.signal_type === "lstm" && attributionOf(signal).length > 0 && (
        <div className="mt-4 rounded-xl border border-brand/10 bg-brand-soft/60 p-4">
          <p className="text-xs font-semibold text-brand">
            Facteurs qui influencent l&apos;estimation (SHAP)
          </p>
          <ul className="mt-3 space-y-2">
            {attributionOf(signal).map((item) => (
              <li
                key={item.label}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <span className="text-slate-700">{item.label}</span>
                <span
                  className={
                    item.value >= 0
                      ? "font-semibold text-rose-700"
                      : "font-semibold text-emerald-700"
                  }
                >
                  {item.value >= 0 ? "+" : ""}
                  {item.value.toFixed(3)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-5 text-slate-500">
            Une contribution positive augmente le risque estimé par ce modèle.
          </p>
        </div>
      )}
      {signal.filing_url && (
        <a
          href={signal.filing_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:text-brand-dark hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Consulter le dépôt source
          <span aria-hidden="true">↗</span>
        </a>
      )}
    </li>
  );
}

// Titre/description dynamiques pour le SEO (feuille de route §7 : pages
// publiques = trafic gratuit et durable) — le nom de l'entreprise EST la
// requête des utilisateurs, pas son CIK. Le fetch company est le même que
// celui du corps de page (non caché, cf. lib/api.ts) : deux appels internes
// par requête, sans dépendance de cache périmé entre métadonnées et contenu.
export async function generateMetadata(
  props: PageProps<"/company/[cik]">,
): Promise<Metadata> {
  const { cik } = await props.params;
  const result = await fetchCompany(Number(cik));

  if (result.state !== "ready") {
    // Erreur API ou CIK inconnu : titre de repli au CIK — jamais de nom
    // inventé pour une entreprise qu'on n'a pas pu charger.
    return { title: `Fiche de risque — CIK ${cik}` };
  }

  const { name, ticker, signals, sector_group: sectorGroup } = result.company;
  const composite = isSectorScoreExcluded(sectorGroup)
    ? undefined
    : signals.find((s) => s.signal_type === "composite");
  const displayName = ticker ? `${name} (${ticker})` : name;
  return {
    title: `${displayName} — Fiche de risque`,
    description: composite
      ? `Score de risque global : ${composite.severity}. Signaux financiers (Altman, Piotroski, événements SEC…) reliés aux dépôts sources. Information générale, pas un conseil en investissement.`
      : isSectorScoreExcluded(sectorGroup)
        ? `Les signaux financiers standards ne sont pas présentés pour ce secteur. Consultez les dépôts publics de ${displayName}.`
        : `Signaux financiers (Altman, Piotroski, événements SEC…) reliés aux dépôts sources. Information générale, pas un conseil en investissement.`,
    alternates: { canonical: `/company/${cik}` },
  };
}

export default function CompanyPage(props: PageProps<"/company/[cik]">) {
  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:px-6 sm:pt-12 lg:px-8">
      {/* Suspense : le fallback s'affiche pendant que params + fetch
          résolvent ; la page complète est streamée au navigateur. */}
      <Suspense
        fallback={
          <div className="animate-pulse rounded-3xl border border-line bg-white p-8 shadow-sm">
            <div className="h-3 w-28 rounded bg-slate-200" />
            <div className="mt-5 h-8 w-2/3 rounded bg-slate-200" />
            <div className="mt-3 h-4 w-1/2 rounded bg-slate-100" />
            <div className="mt-8 h-36 rounded-2xl bg-slate-100" />
          </div>
        }
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
      <div className="rounded-3xl border border-rose-200 bg-white p-8 shadow-sm">
        <p className="text-xs font-bold tracking-[0.12em] text-rose-700">CONNEXION IMPOSSIBLE</p>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Le résumé ne peut pas être chargé</h1>
        <p className="mt-2 max-w-xl leading-6 text-muted">{result.message}</p>
        <Link href="/" className="mt-6 inline-flex rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-dark">
          Retour à la recherche
        </Link>
      </div>
    );
  }

  if (result.state === "not-found") {
    return (
      <div className="rounded-3xl border border-line bg-white p-8 shadow-sm">
        <p className="text-xs font-bold tracking-[0.12em] text-brand">FICHE INTROUVABLE</p>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Cette entreprise n&apos;a pas encore de résumé</h1>
        <p className="mt-2 max-w-xl leading-6 text-muted">
          Essayez une autre entreprise à partir de son nom ou de son symbole boursier.
        </p>
        <Link href="/" className="mt-6 inline-flex rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-dark">
          Rechercher une entreprise
        </Link>
      </div>
    );
  }

  const { company } = result;
  if (isSectorScoreExcluded(company.sector_group)) {
    return (
      <section className="space-y-7">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm font-semibold text-muted hover:text-brand"
        >
          ← Retour à la recherche
        </Link>
        <header className="border-b border-line pb-6">
          <p className="text-xs font-bold tracking-[0.14em] text-brand">
            ENTREPRISE PRÉSENTE DANS LA BASE
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
            {company.name}
            {company.ticker && (
              <span className="ml-2 text-lg font-medium text-muted">{company.ticker}</span>
            )}
          </h1>
        </header>
        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-6 sm:p-8">
          <p className="text-xs font-bold tracking-[0.12em] text-amber-800">
            SECTEUR NON ÉVALUÉ PAR CES SCORES
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-ink">
            Aucun niveau de risque standard n&apos;est affiché
          </h2>
          <p className="mt-3 max-w-3xl leading-6 text-slate-600">
            Les indicateurs de solvabilité présentés ailleurs sont conçus pour
            des entreprises non financières. Ils ne sont pas adaptés aux banques,
            assurances ou REITs ; afficher leur résultat ici pourrait induire en
            erreur. La présence dans cette base ne signifie donc pas qu&apos;un score
            comparable est disponible.
          </p>
          <p className="mt-4 text-sm font-medium text-amber-950">
            Secteur : {company.sector_group}. Les données historiques restent
            conservées pour l&apos;analyse et l&apos;amélioration des modèles.
          </p>
        </section>
      </section>
    );
  }

  const byType = new Map(company.signals.map((s) => [s.signal_type, s]));
  const composite = byType.get("composite");
  const absent = absentSignals(composite);
  const rawComponents = composite?.details?.components;
  const rawWeights = composite?.details?.weights;
  const components =
    rawComponents && typeof rawComponents === "object" && !Array.isArray(rawComponents)
      ? (rawComponents as Record<string, unknown>)
      : {};
  const weights =
    rawWeights && typeof rawWeights === "object" && !Array.isArray(rawWeights)
      ? (rawWeights as Record<string, unknown>)
      : {};
  const severityPoints: Record<string, number> = {
    saine: 0,
    vigilance: 1,
    défaillance: 2,
  };
  // Signaux présents, dans l'ordre produit. Le LSTM reste séparé du composite.
  const ordered = SIGNAL_ORDER.map((t) => byType.get(t)).filter(
    (s): s is Signal => s !== undefined,
  );
  const componentRows = Object.entries(components).flatMap(([name, severity]) => {
    const weight = weights[name];
    const points = severityPoints[String(severity)];
    if (
      !SIMPLE_SIGNAL_COPY[name as SignalType] ||
      typeof weight !== "number" ||
      weight <= 0 ||
      points === undefined
    ) {
      return [];
    }
    const signal =
      history.state === "ready"
        ? history.signals.find(
            (item) =>
              item.signal_type === name && item.period_end === composite?.period_end,
          )
        : undefined;
    return [
      {
        signalType: name as SignalType,
        severity: String(severity),
        weight,
        severityPoints: points,
        signal,
      },
    ];
  });
  const totalWeight = componentRows.reduce((sum, item) => sum + item.weight, 0);
  const weightedComponents: WeightedComponent[] = componentRows.map((item) => ({
    signalType: item.signalType,
    severity: item.severity,
    weight: item.weight,
    contribution: (item.weight * item.severityPoints) / totalWeight,
    signal: item.signal,
  }));
  const availableSignalCount = weightedComponents.length;
  const summarySignals = weightedComponents
    .filter((component) => component.severity !== "saine")
    .sort((left, right) => right.contribution - left.contribution)
    .slice(0, 3);
  const lstmSignal = byType.get("lstm");

  return (
    <section className="space-y-8">
      <Link
        href="/"
        className="inline-flex items-center gap-2 rounded-lg text-sm font-semibold text-muted transition hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand"
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-4">
          <path d="M16 10H4m5-5-5 5 5 5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        </svg>
        Retour à la recherche
      </Link>

      <header className="flex flex-col gap-4 border-b border-line pb-7 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-bold tracking-[0.14em] text-brand">
            APERÇU FINANCIER
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
              {company.name}
            </h1>
            {company.ticker && (
              <span className="rounded-lg border border-line bg-white px-2.5 py-1 text-sm font-bold text-slate-600">
                {company.ticker}
              </span>
            )}
          </div>
          <p className="mt-2 text-sm text-muted">
            Entreprise américaine · Données issues de publications publiques
          </p>
        </div>
        {process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
          process.env.CLERK_SECRET_KEY &&
          process.env.WATCHLIST_API_SECRET &&
          process.env.WATCHLIST_API_SECRET.length >= 32 && (
            <WatchlistAction cik={Number(cik)} />
          )}
      </header>

      {composite && (
        <section className="grid overflow-hidden rounded-3xl border border-line bg-white shadow-[0_22px_60px_-42px_rgba(18,43,64,0.45)] lg:grid-cols-[1.18fr_0.82fr]">
          <div className="p-6 sm:p-8 lg:p-9">
            <p className="text-xs font-bold tracking-[0.14em] text-brand">
              NIVEAU GLOBAL
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                {simpleRiskSummary(composite.severity)}
              </h2>
              <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${badgeClass(composite.severity)}`}>
                {composite.severity}
              </span>
            </div>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-600">
              Ce niveau résume les signaux financiers calculables à partir des
              dépôts publics. Il ne prédit pas une faillite et ne constitue pas
              un conseil en investissement.
            </p>
          </div>

          <aside className="border-t border-line bg-slate-50/80 p-6 sm:p-8 lg:border-l lg:border-t-0 lg:p-9">
            <p className="text-xs font-bold tracking-[0.12em] text-muted">
              BASE DE L&apos;ANALYSE
            </p>
            <div className="mt-3 flex items-center gap-3">
              <span className="text-4xl font-semibold tracking-tight text-ink">
                {availableSignalCount}
              </span>
              <span className="max-w-32 text-sm leading-5 text-muted">
                signal{availableSignalCount === 1 ? "" : "s"} pris en compte
              </span>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-4 border-t border-line pt-4">
              <div>
                <p className="text-xs font-medium text-muted">Mis à jour</p>
                <p className="mt-1 text-sm font-semibold text-ink">
                  {formatAnalysisDate(composite.computed_at)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted">Sans données</p>
                <p className="mt-1 text-sm font-semibold text-ink">
                  {absent.length} signal{absent.length === 1 ? "" : "s"}
                </p>
              </div>
            </div>
            {absent.length > 0 && (
              <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-5 text-amber-900">
                Certains indicateurs n&apos;ont pas pu être calculés. Leur absence
                n&apos;est pas interprétée comme un résultat positif.
              </p>
            )}
          </aside>
        </section>
      )}

      {!composite && (
        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-6 sm:p-8">
          <p className="text-xs font-bold tracking-[0.12em] text-amber-800">
            INFORMATIONS INSUFFISANTES
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-ink">Résumé non disponible</h2>
          <p className="mt-2 max-w-2xl leading-6 text-slate-600">
            Les informations disponibles ne suffisent pas à calculer un niveau
            global. Aucun score n&apos;est inventé.
          </p>
        </section>
      )}

      <section className="rounded-2xl border border-brand/15 bg-brand-soft/40 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold tracking-[0.12em] text-brand">
              MODÈLE COMPLÉMENTAIRE · HORIZON 12 MOIS
            </p>
            <h2 className="mt-1 text-lg font-semibold text-ink">
              Estimation du modèle de deep learning
            </h2>
          </div>
          {lstmSignal && (
            <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${badgeClass(lstmSignal.severity)}`}>
              {lstmSignal.severity}
            </span>
          )}
        </div>
        {lstmSignal ? (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-3xl font-semibold tracking-tight text-brand">
                Score du modèle : {formatValue("lstm", lstmSignal.value)}
              </p>
              <p className="mt-1 text-sm text-muted">
                Exercice {lstmSignal.period_end.slice(0, 4)}
                {typeof lstmSignal.details?.window_years === "number" &&
                  ` · Fenêtre de ${lstmSignal.details.window_years} exercices`}
                {` · Calculé le ${formatAnalysisDate(lstmSignal.computed_at)}`}
                {typeof lstmSignal.details?.trained_at === "string" &&
                  ` · Entraîné le ${formatAnalysisDate(lstmSignal.details.trained_at)}`}
              </p>
            </div>
            <p className="max-w-xl text-sm leading-6 text-slate-600 sm:text-right">
              C&apos;est un score expérimental du modèle, pas une probabilité calibrée.
              Il est présenté séparément et ne modifie pas le niveau global.
            </p>
          </div>
        ) : (
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            Aucune estimation du modèle n&apos;est disponible pour cette entreprise.
            Le niveau global ci-dessus repose uniquement sur les signaux classiques.
          </p>
        )}
      </section>

      <section aria-labelledby="reasons-heading" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-bold tracking-[0.14em] text-brand">
              EXPLICATION DU RÉSULTAT
            </p>
            <h2 id="reasons-heading" className="mt-1 text-2xl font-semibold tracking-tight text-ink">
              Les principaux points d&apos;attention
            </h2>
          </div>
          <span className="text-sm text-muted">Jusqu&apos;à 3 signaux</span>
        </div>
        {summarySignals.length > 0 ? (
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {summarySignals.map((component) => (
              <SummarySignalCard
                key={component.signalType}
                component={component}
                periodEnd={composite?.period_end ?? ""}
              />
            ))}
          </ul>
        ) : (
          <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white text-emerald-700 ring-1 ring-emerald-200">
              <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-5">
                <path d="m5 10 3.2 3.2L15.5 6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
              </svg>
            </span>
            <div>
              <p className="font-semibold text-emerald-950">
                Aucun point d&apos;attention marqué parmi les signaux classiques intégrés au niveau global
              </p>
              <p className="mt-1 text-sm leading-5 text-emerald-900/80">
                Cela ne garantit pas l&apos;absence de risque. Consultez la couverture
                des données ci-dessus et les détails si nécessaire.
              </p>
            </div>
          </div>
        )}
      </section>

      <details className="group overflow-hidden rounded-3xl border border-line bg-white shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-5 transition hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-brand sm:px-7">
          <span className="flex items-center gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="size-5">
                <path d="M4 19.5h16M6.5 16V11m5 5V5m5 11v-7" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
              </svg>
            </span>
            <span>
              <span className="block text-xs font-bold tracking-[0.12em] text-brand">
                POUR ALLER PLUS LOIN
              </span>
              <span className="mt-1 block text-base font-semibold text-ink sm:text-lg">
                Analyse détaillée
              </span>
              <span className="mt-0.5 hidden text-sm text-muted sm:block">
                Indicateurs, historique et dépôts sources
              </span>
            </span>
          </span>
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            fill="none"
            className="size-5 shrink-0 text-muted transition-transform group-open:rotate-180"
          >
            <path d="m5 7.5 5 5 5-5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
          </svg>
        </summary>

        <div className="space-y-8 border-t border-line p-5 sm:p-7">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl bg-slate-50 p-4">
              <p className="text-xs font-bold tracking-[0.1em] text-muted">
                RÉFÉRENCE SEC
              </p>
              <p className="mt-1 text-sm font-semibold text-ink">CIK {cik}</p>
              {company.sector_group && (
                <p className="mt-1 text-sm text-muted">Secteur : {company.sector_group}</p>
              )}
            </div>
            <div className="rounded-2xl border border-brand/10 bg-brand-soft/50 p-4">
              <p className="text-xs font-bold tracking-[0.1em] text-brand">
                À SAVOIR
              </p>
              <p className="mt-1 text-sm leading-5 text-slate-700">
                Le modèle LSTM est une estimation complémentaire. Il n&apos;est pas
                inclus dans le niveau global.
              </p>
            </div>
          </div>

          {absent.length > 0 && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950">
              <span className="font-semibold">Données manquantes : </span>
              {absent.join(", ")}.
            </div>
          )}

          {composite && (
            <section className="overflow-hidden rounded-2xl border border-line bg-white">
              <div className="border-b border-line bg-slate-50 p-5">
                <p className="text-xs font-bold tracking-[0.12em] text-brand">
                  DÉCOMPOSITION DU SCORE
                </p>
                <h3 className="mt-1 text-xl font-semibold text-ink">
                  Comment le niveau global est calculé
                </h3>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
                  Chaque signal reçoit un poids et une sévérité. Sa contribution
                  est calculée ainsi : poids × sévérité ÷ somme des poids
                  disponibles (saine = 0, vigilance = 1, défaillance = 2).
                  L&apos;indice est une moyenne, pas une probabilité. Les signaux
                  manquants sont exclus, jamais considérés comme sains.
                </p>
                <p className="mt-3 text-sm font-semibold text-ink">
                  Indice obtenu : {formatValue("composite", composite.value)}
                  <span className="ml-2 font-normal text-muted">
                    · Niveau {composite.severity}
                  </span>
                </p>
              </div>
              <ul className="divide-y divide-line/70">
                {weightedComponents.map((component) => {
                  const copy = SIMPLE_SIGNAL_COPY[component.signalType];
                  if (!copy) return null;
                  return (
                    <li
                      key={component.signalType}
                      className="grid gap-2 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-5"
                    >
                      <div>
                        <p className="font-semibold text-ink">{copy.label}</p>
                        <p className="mt-0.5 text-xs text-muted">{copy.explanation}</p>
                      </div>
                      <span className={`w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass(component.severity)}`}>
                        {component.severity}
                      </span>
                      <div className="flex items-center justify-between gap-4 text-xs sm:block sm:text-right">
                        <span className="text-muted">
                          Poids {formatWeight(component.weight)}
                        </span>
                        <span className="font-semibold text-ink sm:mt-1 sm:block">
                          Contribution {formatContribution(component.contribution)} pt
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {absent.length > 0 && (
                <p className="border-t border-line bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-950">
                  Non inclus dans le calcul faute de données : {absent.join(", ")}.
                </p>
              )}
            </section>
          )}

          <section aria-labelledby="signals-heading">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
              <div>
                <p className="text-xs font-bold tracking-[0.12em] text-brand">
                  INDICATEURS
                </p>
                <h3 id="signals-heading" className="mt-1 text-xl font-semibold text-ink">
                  Tous les signaux disponibles
                </h3>
              </div>
              <p className="text-sm text-muted">
                {ordered.filter((signal) => signal.signal_type !== "composite").length} indicateurs
              </p>
            </div>
            <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {ordered
                .filter((signal) => signal.signal_type !== "composite")
                .map((signal) => (
                  <DetailedSignalCard key={signal.signal_type} signal={signal} />
                ))}
            </ul>
            {ordered.filter((signal) => signal.signal_type !== "composite").length ===
              0 && (
              <p className="rounded-2xl border border-line bg-slate-50 p-5 text-sm text-muted">
                Aucun indicateur détaillé n&apos;a pu être calculé avec les données disponibles.
              </p>
            )}
          </section>

          {history.state === "ready" && history.signals.length > 0 && (
            <section className="rounded-2xl border border-line bg-white p-4 sm:p-6" aria-labelledby="history-heading">
              <div className="mb-4">
                <p className="text-xs font-bold tracking-[0.12em] text-brand">
                  HISTORIQUE
                </p>
                <h3 id="history-heading" className="mt-1 text-xl font-semibold text-ink">
                  Évolution des indicateurs
                </h3>
              </div>
              <ScoreChart signals={history.signals} />
            </section>
          )}
        </div>
      </details>

      <p className="text-center text-xs leading-5 text-muted">
        Résumé établi à partir des données publiques disponibles. Pas un conseil
        en investissement.
      </p>
    </section>
  );
}
