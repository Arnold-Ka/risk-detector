"use client";

import { SignInButton, useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";

async function errorMessage(response: Response): Promise<string> {
  const data = (await response.json().catch(() => null)) as
    | { detail?: unknown }
    | null;
  return typeof data?.detail === "string"
    ? data.detail
    : "Impossible de mettre à jour votre liste pour le moment.";
}

export default function WatchlistAction({ cik }: { cik: number }) {
  const { isLoaded, isSignedIn, userId } = useAuth();
  const [savedState, setSavedState] = useState<{
    userId: string;
    saved: boolean;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{
    userId: string;
    text: string;
    isError: boolean;
  } | null>(null);
  const isSaved =
    userId && savedState?.userId === userId ? savedState.saved : null;

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !userId) return;
    let current = true;
    void fetch("/api/watchlist", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(await errorMessage(response));
        return (await response.json()) as { items: { cik: number }[] };
      })
      .then((data) => {
        if (current) {
          setSavedState({
            userId,
            saved: data.items.some((item) => item.cik === cik),
          });
          setMessage(null);
        }
      })
      .catch((cause: unknown) => {
        if (current) {
          setSavedState({ userId, saved: false });
          setMessage({
            userId,
            text:
              cause instanceof Error
                ? cause.message
                : "Impossible de vérifier votre liste.",
            isError: true,
          });
        }
      });
    return () => {
      current = false;
    };
  }, [cik, isLoaded, isSignedIn, userId]);

  async function toggleWatchlist() {
    if (!userId || isSaved === null) return;
    const wasSaved = isSaved;
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch(
        wasSaved ? `/api/watchlist?cik=${cik}` : "/api/watchlist",
        {
          method: wasSaved ? "DELETE" : "POST",
          ...(wasSaved
            ? {}
            : {
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ cik }),
              }),
        },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      setSavedState({ userId, saved: !wasSaved });
      setMessage({
        userId,
        text: wasSaved
          ? "Entreprise retirée de votre liste."
          : "Entreprise ajoutée à votre liste.",
        isError: false,
      });
    } catch (cause) {
      setMessage({
        userId,
        text:
          cause instanceof Error
            ? cause.message
            : "Impossible de mettre à jour votre liste.",
        isError: true,
      });
    } finally {
      setPending(false);
    }
  }

  if (!isLoaded) {
    return (
      <button
        type="button"
        disabled
        className="h-11 animate-pulse rounded-xl bg-slate-100 px-4 text-sm text-muted"
      >
        Chargement…
      </button>
    );
  }

  if (!isSignedIn) {
    return (
      <SignInButton mode="modal">
        <button className="inline-flex h-11 items-center gap-2 rounded-xl border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
          <span aria-hidden="true">＋</span>
          Se connecter pour suivre
        </button>
      </SignInButton>
    );
  }

  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <button
        type="button"
        onClick={() => void toggleWatchlist()}
        disabled={pending || isSaved === null}
        aria-pressed={isSaved === true}
        className={`inline-flex h-11 items-center gap-2 rounded-xl px-4 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-wait disabled:opacity-60 ${
          isSaved
            ? "border border-line bg-white text-ink hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700"
            : "bg-brand text-white shadow-sm hover:bg-brand-dark"
        }`}
      >
        <span aria-hidden="true">{isSaved ? "✓" : "＋"}</span>
        {pending
          ? "Mise à jour…"
          : isSaved
            ? "Dans votre liste"
            : "Ajouter à ma liste"}
      </button>
      {message?.userId === userId && (
        <p
          role="status"
          className={`max-w-xs text-xs ${message.isError ? "text-rose-700" : "text-muted"}`}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
