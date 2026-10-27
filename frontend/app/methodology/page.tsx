// Page « Méthodologie et résultats » — feuille de route §7 : « publier le
// backtest : c'est le contenu le plus convaincant possible ». Page publique,
// indexable, entièrement statique (aucun appel d'API) : elle est prérendue
// au build.
//
// PROVENANCE DES CHIFFRES — à régénérer après tout retune du composite :
//   - taux globaux : `uv run python -m scripts.backtest`, règle
//     « niveau >= modéré » (exécuté le 2026-10-27, identique au README) ;
//   - exemples : même règle et même disponibilité que le backtest
//     (app/backtest/metrics.build_snapshots + pick_snapshot : un exercice
//     n'est connu qu'au dépôt le plus tardif de ses composantes), calculés
//     le 2026-10-27 sur la cohorte data/backtest/companies.json.
// Les échecs sont affichés au même rang que les réussites : c'est ce qui
// rend la page crédible, et c'est la vérité du backtest.

import type { Metadata } from "next";
import Link from "next/link";
import { SIGNAL_HINTS, SIGNAL_LABELS, badgeClass } from "@/lib/signals";
import type { SignalType } from "@/lib/api";

export const metadata: Metadata = {
  title: "Méthodologie et résultats — Détecteur de risque financier",
  description:
    "Comment le niveau de risque est calculé et ce qu'il aurait détecté : backtest sur 547 faillites américaines (2015-2025) et 328 sociétés saines, réussites et échecs compris.",
};

// --- Résultats globaux (scripts/backtest, règle « niveau >= modéré ») -------
const BANKRUPTCIES = 547;
const CONTROLS = 328;
const CONTROL_YEARS = 6246;
const KEY_FIGURES = [
  {
    value: "64,9 %",
    label: "des faillites signalées au moins 6 mois avant",
    note: "niveau modéré ou plus, connu 6 mois avant le dépôt de bilan",
  },
  {
    value: "56,7 %",
    label: "des faillites signalées au moins 12 mois avant",
    note: "même règle, un an avant",
  },
  {
    value: "9,3 %",
    label: "de fausses alertes par an",
    note: `part des ${CONTROL_YEARS.toLocaleString("fr-FR")} exercices de sociétés saines en alerte`,
  },
];
// Part des sociétés saines alertées au moins une fois sur toute la période.
const CONTROLS_EVER_ALERTED = "66,5 %";

// --- Exemples (voir PROVENANCE) ----------------------------------------------
type Example = {
  name: string;
  bankruptcy: string; // date du 8-K item 1.03 (ancre du backtest)
  at12: string; // niveau connu 12 mois avant
  at6: string; // niveau connu 6 mois avant
  // Mois entre le premier exercice d'une alerte ininterrompue (date de son
  // dépôt) et la faillite ; null = aucune alerte en cours à la faillite.
  leadMonths: number | null;
  note?: string;
};

const DETECTED: Example[] = [
  { name: "J.C. Penney", bankruptcy: "2020-05-18", at12: "modéré", at6: "modéré", leadMonths: 75 },
  { name: "Sears Holdings", bankruptcy: "2018-10-15", at12: "modéré", at6: "élevé", leadMonths: 55 },
  { name: "Party City", bankruptcy: "2023-01-18", at12: "modéré", at6: "modéré", leadMonths: 34 },
  { name: "Spirit Airlines", bankruptcy: "2024-11-18", at12: "modéré", at6: "modéré", leadMonths: 21 },
  { name: "Chesapeake Energy", bankruptcy: "2020-06-29", at12: "modéré", at6: "modéré", leadMonths: 16 },
  { name: "JOANN", bankruptcy: "2024-03-18", at12: "faible", at6: "modéré", leadMonths: 11 },
  { name: "Nikola", bankruptcy: "2025-02-19", at12: "faible", at6: "modéré", leadMonths: 11 },
  { name: "Pier 1 Imports", bankruptcy: "2020-02-18", at12: "faible", at6: "modéré", leadMonths: 9 },
  { name: "The Container Store", bankruptcy: "2024-12-23", at12: "faible", at6: "modéré", leadMonths: 6 },
];

const LATE: Example[] = [
  { name: "Big Lots", bankruptcy: "2024-09-10", at12: "faible", at6: "faible", leadMonths: 4 },
  { name: "Proterra", bankruptcy: "2023-08-08", at12: "faible", at6: "faible", leadMonths: 4 },
  { name: "Revlon", bankruptcy: "2022-06-16", at12: "faible", at6: "faible", leadMonths: 3, note: "niveau élevé au dernier rapport" },
  { name: "Lordstown Motors", bankruptcy: "2023-06-27", at12: "faible", at6: "faible", leadMonths: 3, note: "niveau élevé au dernier rapport" },
];

const MISSED: Example[] = [
  { name: "Bed Bath & Beyond", bankruptcy: "2023-04-24", at12: "faible", at6: "faible", leadMonths: null },
  { name: "Rite Aid", bankruptcy: "2023-10-16", at12: "faible", at6: "faible", leadMonths: null },
  { name: "Tupperware", bankruptcy: "2024-09-18", at12: "faible", at6: "faible", leadMonths: null },
  { name: "Express", bankruptcy: "2024-04-22", at12: "faible", at6: "faible", leadMonths: null },
  { name: "Hertz", bankruptcy: "2020-05-26", at12: "faible", at6: "faible", leadMonths: null, note: "choc brutal du COVID-19" },
  { name: "GNC", bankruptcy: "2020-06-24", at12: "faible", at6: "faible", leadMonths: null },
];

// Signaux du niveau global, dans l'ordre de la fiche (le LSTM est à part).
const COMPOSITE_SIGNALS: SignalType[] = [
  "altman",
  "piotroski",
  "beneish",
  "divergence",
  "runway",
  "late_filing",
  "critical_8k",
  "insider_sales",
  "net_debt_ebitda",
  "dilution",
];

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function LevelBadge({ level }: { level: string }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeClass(level)}`}>
      {level}
    </span>
  );
}

function ExampleTable({
  id,
  eyebrow,
  title,
  intro,
  examples,
}: {
  id: string;
  eyebrow: string;
  title: string;
  intro: string;
  examples: Example[];
}) {
  return (
    <section aria-labelledby={id} className="overflow-hidden rounded-2xl border border-line bg-white">
      <div className="border-b border-line bg-slate-50 p-5">
        <p className="text-xs font-bold tracking-[0.12em] text-brand">{eyebrow}</p>
        <h3 id={id} className="mt-1 text-lg font-semibold text-ink">
          {title}
        </h3>
        <p className="mt-1 text-sm leading-6 text-muted">{intro}</p>
      </div>
      {/* Défilement horizontal confiné au tableau sur mobile : la page,
          elle, ne défile jamais horizontalement. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="px-5 py-3 font-semibold">Entreprise</th>
              <th scope="col" className="px-3 py-3 font-semibold">Faillite</th>
              <th scope="col" className="px-3 py-3 font-semibold">12 mois avant</th>
              <th scope="col" className="px-3 py-3 font-semibold">6 mois avant</th>
              <th scope="col" className="px-5 py-3 font-semibold">Alerte ininterrompue</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/70">
            {examples.map((example) => (
              <tr key={example.name}>
                <th scope="row" className="px-5 py-3 font-semibold text-ink">
                  {example.name}
                  {example.note && (
                    <span className="block text-xs font-normal text-muted">{example.note}</span>
                  )}
                </th>
                <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                  {formatDate(example.bankruptcy)}
                </td>
                <td className="px-3 py-3"><LevelBadge level={example.at12} /></td>
                <td className="px-3 py-3"><LevelBadge level={example.at6} /></td>
                <td className="whitespace-nowrap px-5 py-3 text-slate-600">
                  {example.leadMonths === null
                    ? "aucune"
                    : `depuis ≈ ${example.leadMonths} mois`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function MethodologyPage() {
  return (
    <main className="mx-auto max-w-6xl space-y-12 px-4 pb-16 pt-10 sm:px-6 sm:pt-14 lg:px-8">
      <header className="max-w-3xl">
        <p className="text-xs font-bold tracking-[0.14em] text-brand">
          MÉTHODOLOGIE ET RÉSULTATS
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Ce que l&apos;outil aurait vu venir, et ce qu&apos;il a manqué
        </h1>
        <p className="mt-4 leading-7 text-slate-600">
          Nous avons rejoué le calcul du niveau de risque sur {BANKRUPTCIES}{" "}
          faillites d&apos;entreprises cotées américaines entre 2015 et 2025, en
          n&apos;utilisant que les informations publiées avant chaque date
          testée. Les chiffres ci-dessous sont mesurés, pas promis, et les
          échecs sont montrés au même titre que les réussites.
        </p>
      </header>

      <section aria-labelledby="figures-heading" className="space-y-4">
        <h2 id="figures-heading" className="sr-only">
          Résultats principaux
        </h2>
        <ul className="grid gap-4 md:grid-cols-3">
          {KEY_FIGURES.map((figure) => (
            <li
              key={figure.label}
              className="rounded-2xl border border-line bg-white p-6 shadow-[0_12px_36px_-30px_rgba(18,43,64,0.4)]"
            >
              <p className="text-4xl font-semibold tracking-tight text-brand">{figure.value}</p>
              <p className="mt-2 font-semibold text-ink">{figure.label}</p>
              <p className="mt-1 text-sm leading-5 text-muted">{figure.note}</p>
            </li>
          ))}
        </ul>
        <p className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-950">
          <span className="font-semibold">À lire avec ce chiffre : </span>
          sur l&apos;ensemble de la période, {CONTROLS_EVER_ALERTED} des {CONTROLS}{" "}
          sociétés saines du S&amp;P 500 ont reçu au moins une alerte de niveau
          modéré. Une alerte n&apos;annonce donc pas une faillite : elle signale
          une entreprise dont les comptes méritent d&apos;être regardés.
        </p>
      </section>

      <section aria-labelledby="method-heading" className="grid gap-8 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <p className="text-xs font-bold tracking-[0.14em] text-brand">MÉTHODE</p>
          <h2 id="method-heading" className="mt-1 text-2xl font-semibold tracking-tight text-ink">
            Comment le test a été mené
          </h2>
          <p className="mt-3 leading-7 text-slate-600">
            Le but est de reproduire ce qu&apos;un investisseur aurait vu à
            l&apos;époque, sans tricher avec des informations publiées plus
            tard.
          </p>
        </div>
        <ol className="space-y-4">
          {[
            {
              title: "Deux groupes d'entreprises",
              body: `${BANKRUPTCIES} entreprises ayant déposé le bilan (premier rapport 8-K « Item 1.03 », faillite, entre 2015 et 2025), comparées à ${CONTROLS} sociétés du S&P 500 jamais concernées.`,
            },
            {
              title: "Aucune information du futur",
              body: "Un score n'est considéré comme connu qu'à la date où le dernier rapport nécessaire à son calcul a été déposé à la SEC. Un rapport annuel publié trois mois après la clôture ne compte qu'à partir de sa publication.",
            },
            {
              title: "Une règle d'alerte fixe",
              body: "Une faillite est « signalée » si le niveau global connu 6 (ou 12) mois avant le dépôt de bilan était modéré, élevé ou critique. Le même seuil sert à compter les fausses alertes chez les sociétés saines.",
            },
            {
              title: "Pas de score inventé",
              body: "Un indicateur qui ne peut pas être calculé est exclu, jamais compté comme sain. Le niveau global fait la moyenne pondérée des indicateurs disponibles ; les poids ont été ajustés sur ce même backtest.",
            },
          ].map((step, index) => (
            <li key={step.title} className="flex gap-4 rounded-2xl border border-line bg-white p-5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-bold text-brand">
                {index + 1}
              </span>
              <div>
                <h3 className="font-semibold text-ink">{step.title}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="examples-heading" className="space-y-5">
        <div className="max-w-3xl">
          <p className="text-xs font-bold tracking-[0.14em] text-brand">EXEMPLES</p>
          <h2 id="examples-heading" className="mt-1 text-2xl font-semibold tracking-tight text-ink">
            Des faillites connues, réussites comme échecs
          </h2>
          <p className="mt-3 leading-7 text-slate-600">
            Une sélection de faillites médiatisées, avec le niveau que
            l&apos;outil affichait 12 et 6 mois avant. « Alerte ininterrompue »
            indique depuis combien de temps le niveau était au moins modéré
            sans interruption au moment de la faillite. Les taux ci-dessus
            portent sur les {BANKRUPTCIES} faillites, pas seulement sur ces
            exemples.
          </p>
        </div>
        <ExampleTable
          id="detected-heading"
          eyebrow="SIGNALÉES À TEMPS"
          title="Niveau modéré ou plus au moins 6 mois avant"
          intro="Le signal était visible assez tôt pour réagir."
          examples={DETECTED}
        />
        <ExampleTable
          id="late-heading"
          eyebrow="SIGNALÉES TARD"
          title="Alerte apparue moins de 6 mois avant"
          intro="Le niveau a monté, mais tard : souvent parce que le rapport annuel qui révèle les difficultés arrive peu avant la faillite."
          examples={LATE}
        />
        <ExampleTable
          id="missed-heading"
          eyebrow="MANQUÉES"
          title="Aucune alerte avant la faillite"
          intro="Le niveau est resté faible. Les causes typiques : un choc soudain que les comptes annuels ne pouvaient pas montrer, ou des difficultés révélées après le dernier rapport disponible."
          examples={MISSED}
        />
      </section>

      <section aria-labelledby="signals-heading" className="space-y-5">
        <div className="max-w-3xl">
          <p className="text-xs font-bold tracking-[0.14em] text-brand">LES INDICATEURS</p>
          <h2 id="signals-heading" className="mt-1 text-2xl font-semibold tracking-tight text-ink">
            Ce qui compose le niveau global
          </h2>
          <p className="mt-3 leading-7 text-slate-600">
            Dix indicateurs calculés à partir des rapports déposés à la SEC et
            des cours de bourse. Chacun est classé sain, vigilance ou
            défaillance, puis le niveau global en fait la moyenne pondérée.
            Chaque indicateur affiché sur une fiche renvoie au rapport dont il
            est tiré.
          </p>
        </div>
        <ul className="grid gap-3 md:grid-cols-2">
          {COMPOSITE_SIGNALS.map((type) => (
            <li key={type} className="rounded-2xl border border-line bg-white p-4">
              <p className="font-semibold text-ink">{SIGNAL_LABELS[type]}</p>
              <p className="mt-1 text-sm leading-6 text-slate-600">{SIGNAL_HINTS[type]}</p>
            </li>
          ))}
        </ul>
        <p className="text-sm leading-6 text-muted">
          Un modèle d&apos;apprentissage profond (LSTM) donne en plus une
          estimation séparée sur la fiche. Il n&apos;entre pas dans le niveau
          global, et ses résultats sont mesurés à part.
        </p>
      </section>

      <section aria-labelledby="limits-heading" className="rounded-3xl border border-line bg-white p-6 sm:p-8">
        <p className="text-xs font-bold tracking-[0.14em] text-brand">LIMITES</p>
        <h2 id="limits-heading" className="mt-1 text-2xl font-semibold tracking-tight text-ink">
          Ce que l&apos;outil ne fait pas
        </h2>
        <ul className="mt-5 grid gap-4 text-sm leading-6 text-slate-600 md:grid-cols-2">
          <li>
            <span className="font-semibold text-ink">Il ne prédit pas les faillites.</span>{" "}
            Le niveau résume la qualité des comptes publiés ; un tiers des
            faillites testées n&apos;étaient pas signalées 6 mois avant.
          </li>
          <li>
            <span className="font-semibold text-ink">Il ne voit pas les chocs soudains.</span>{" "}
            Les indicateurs reposent surtout sur les rapports annuels : un
            événement brutal (pandémie, fraude découverte) peut précéder tout
            signal.
          </li>
          <li>
            <span className="font-semibold text-ink">Il ne couvre pas les banques, assurances et REITs.</span>{" "}
            Ces scores ne sont pas adaptés à leurs bilans ; aucun niveau
            n&apos;est affiché pour elles.
          </li>
          <li>
            <span className="font-semibold text-ink">Ce n&apos;est pas un conseil en investissement.</span>{" "}
            Les résultats passés du backtest ne garantissent pas les
            résultats futurs. Vérifiez toujours les rapports sources.
          </li>
        </ul>
      </section>

      <section className="flex flex-col items-start gap-4 rounded-3xl bg-brand-soft/60 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
        <div>
          <h2 className="text-xl font-semibold text-ink">Vérifiez par vous-même</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            Le code est ouvert sous licence MIT : le calcul, les poids et le
            backtest peuvent être audités et rejoués. Chaque fiche renvoie aux
            rapports SEC d&apos;origine.
          </p>
        </div>
        <Link
          href="/"
          className="inline-flex shrink-0 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Rechercher une entreprise
        </Link>
      </section>
    </main>
  );
}
