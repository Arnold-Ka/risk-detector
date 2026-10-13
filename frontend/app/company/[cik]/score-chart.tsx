"use client";

// Graphique d'évolution des scores sur 5 ans (feuille de route §9).
// Composant CLIENT : il gère le choix de la série et le rendu interactif,
// mais les données lui sont passées en props depuis la page serveur
// (pas de second fetch côté navigateur).
//
// Choix techniques :
// - SVG « maison » au lieu d'une librairie de charts : une série par page,
//   ~19 points d'exercice — recharts ajouterait ~100 ko pour rien, et
//   rien dans le projet ne justifie une dépendance graphique aujourd'hui ;
// - traits pointillés = seuils d'alerte du signal (bandes de la feuille
//   de route §2) : on lit la zone de danger directement sur la courbe ;
// - points colorés par sévérité (même palette que les badges de la fiche) ;
// - fenêtre glissante 5 ans calculée depuis l'exercice le plus récent.

import { useMemo, useState } from "react";
import type { Signal, SignalType } from "@/lib/api";
import { SIGNAL_LABELS, SIGNAL_ORDER } from "@/lib/signals";

// Palette sévérité (hex — les classes Tailwind ne s'appliquent pas en SVG).
const SEVERITY_COLORS: Record<string, string> = {
  saine: "#059669",
  faible: "#059669",
  vigilance: "#d97706",
  modéré: "#d97706",
  élevé: "#ea580c",
  défaillance: "#dc2626",
  critique: "#dc2626",
};

// Seuils d'alerte par signal (feuille de route §2) — traits pointillés.
const THRESHOLDS: Partial<Record<SignalType, number[]>> = {
  altman: [2.99, 1.81],
  piotroski: [7, 3],
  beneish: [-1.78, -2.27],
  composite: [1.5, 1, 0.5],
  runway: [24, 12],
  divergence: [2, 1],
};

// Géométrie du viewBox (coordonnées fixes, le SVG se met à l'échelle).
const W = 640;
const H = 260;
const PAD = { top: 16, right: 52, bottom: 30, left: 48 };

function axisLabel(value: number): string {
  // Échelle compacte : assez de décimales pour lire, pas pour noyer.
  return Math.abs(value) >= 10 ? value.toFixed(0) : value.toFixed(1);
}

export default function ScoreChart({ signals }: { signals: Signal[] }) {
  // Séries disponibles : types présents avec au moins une valeur exploitable,
  // dans l'ordre de la feuille de route (composite d'abord).
  const available = useMemo(() => {
    const present = new Set(
      signals.filter((s) => s.value !== null).map((s) => s.signal_type),
    );
    return SIGNAL_ORDER.filter((t) => present.has(t));
  }, [signals]);

  const [type, setType] = useState<SignalType>(available[0] ?? "composite");

  const points = useMemo(() => {
    // Fenêtre 5 ans : à partir de l'exercice le plus récent de TOUTE
    // l'historique (pas de la série choisie) — les axes sont stables quand
    // on change de série.
    const maxEnd = signals.reduce(
      (max, s) => (s.period_end > max ? s.period_end : max),
      "",
    );
    const cutoff = new Date(maxEnd);
    cutoff.setFullYear(cutoff.getFullYear() - 5);
    const isoCutoff = cutoff.toISOString().slice(0, 10);

    return signals
      .filter(
        (s) =>
          s.signal_type === type &&
          s.value !== null &&
          s.period_end >= isoCutoff,
      )
      .sort((a, b) => a.period_end.localeCompare(b.period_end))
      .map((s) => ({
        t: Date.parse(s.period_end),
        value: s.value as number,
        severity: s.severity,
        period_end: s.period_end,
      }));
  }, [signals, type]);

  if (available.length === 0 || points.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        Aucune valeur exploitable sur les 5 dernières années pour cette série.
      </p>
    );
  }

  // --- Échelles -------------------------------------------------------------
  const thresholds = THRESHOLDS[type] ?? [];
  const values = points.map((p) => p.value);
  const tMin = Math.min(...values, ...thresholds);
  const tMax = Math.max(...values, ...thresholds);
  const span = tMax - tMin || 1;
  const yMin = tMin - span * 0.1;
  const yMax = tMax + span * 0.1;

  const xMin = Math.min(...points.map((p) => p.t));
  const xMax = Math.max(...points.map((p) => p.t));
  const xSpan = xMax - xMin || 1;

  const x = (t: number) =>
    PAD.left + ((t - xMin) / xSpan) * (W - PAD.left - PAD.right);

  // Fonction y : valeur → pixel (haut de l'image = grand nombre).
  const yPx = (v: number) =>
    PAD.top + ((yMax - v) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);

  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${yPx(p.value).toFixed(1)}`)
    .join(" ");

  return (
    <div>
      <div className="mb-2 flex items-center gap-3">
        <label htmlFor="serie" className="text-sm text-gray-600">
          Série :
        </label>
        <select
          id="serie"
          value={type}
          onChange={(e) => setType(e.target.value as SignalType)}
          className="rounded-lg border border-gray-300 px-2 py-1 text-sm"
        >
          {available.map((t) => (
            <option key={t} value={t}>
              {SIGNAL_LABELS[t]}
            </option>
          ))}
        </select>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Évolution de ${SIGNAL_LABELS[type]} sur 5 ans`}
        className="w-full"
      >
        {/* Axes bornes (min/max de la plage affichée) */}
        <text x={PAD.left - 6} y={yPx(yMax) + 4} textAnchor="end" fontSize="11" fill="#6b7280">
          {axisLabel(yMax)}
        </text>
        <text x={PAD.left - 6} y={yPx(yMin) + 4} textAnchor="end" fontSize="11" fill="#6b7280">
          {axisLabel(yMin)}
        </text>

        {/* Seuils d'alerte : traits pointillés + valeur à droite */}
        {thresholds.map((th) => (
          <g key={th}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={yPx(th)}
              y2={yPx(th)}
              stroke="#9ca3af"
              strokeWidth="1"
              strokeDasharray="4 4"
            />
            <text x={W - PAD.right + 4} y={yPx(th) + 4} fontSize="10" fill="#6b7280">
              {axisLabel(th)}
            </text>
          </g>
        ))}

        {/* Courbe : trait unique (la couleur d'alerte porte sur les points) */}
        <path d={path} fill="none" stroke="#2563eb" strokeWidth="2" />

        {/* Points : couleur = sévérité de l'exercice, bulle native = détail */}
        {points.map((p) => (
          <circle
            key={p.period_end}
            cx={x(p.t)}
            cy={yPx(p.value)}
            r="4"
            fill={SEVERITY_COLORS[p.severity] ?? "#6b7280"}
          >
            <title>{`${p.period_end} — ${p.value.toFixed(2)} (${p.severity})`}</title>
          </circle>
        ))}

        {/* Années en abscisse : première, médiane, dernière */}
        {[points[0], points[Math.floor(points.length / 2)], points[points.length - 1]].map(
          (p, i) => (
            <text
              key={i}
              x={x(p.t)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
              fontSize="11"
              fill="#6b7280"
            >
              {p.period_end.slice(0, 4)}
            </text>
          ),
        )}
      </svg>

      <p className="mt-2 text-xs text-gray-500">
        5 dernières années — points colorés par sévérité (survolez pour le
        détail), traits pointillés = seuils d&apos;alerte ({SIGNAL_LABELS[type]}).
      </p>
    </div>
  );
}
