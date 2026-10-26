import "server-only";

import { auth, currentUser } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8011";

export async function forwardWatchlistRequest(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: { cik: number },
): Promise<NextResponse> {
  const apiKey = process.env.WATCHLIST_API_SECRET;
  if (
    !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
    !process.env.CLERK_SECRET_KEY ||
    !apiKey ||
    apiKey.length < 32
  ) {
    return NextResponse.json(
      { detail: "La liste de suivi n'est pas encore configurée." },
      { status: 503 },
    );
  }

  let userId: string | null = null;
  let email: string | undefined;
  try {
    ({ userId } = await auth());
    if (!userId) {
      return NextResponse.json(
        { detail: "Connectez-vous pour accéder à votre liste de suivi." },
        { status: 401 },
      );
    }
    const user = await currentUser();
    const primaryEmail = user?.primaryEmailAddress;
    if (
      primaryEmail?.verification?.status === "verified" &&
      primaryEmail.emailAddress
    ) {
      email = primaryEmail.emailAddress;
    }
  } catch {
    return NextResponse.json(
      { detail: "Le service de connexion est temporairement indisponible." },
      { status: 503 },
    );
  }

  if (!email) {
    return NextResponse.json(
      { detail: "Vérifiez l'adresse e-mail principale de votre compte." },
      { status: 403 },
    );
  }

  try {
    const response = await fetch(`${API_URL}/me/watchlist${path}`, {
      method,
      headers: {
        "X-Watchlist-Api-Key": apiKey,
        "X-Clerk-User-Id": userId,
        "X-Clerk-User-Email": email,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      cache: "no-store",
    });
    const data: unknown = await response.json().catch(() => ({
      detail: "Réponse invalide du service de liste de suivi.",
    }));
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Le service de liste de suivi est temporairement inaccessible." },
      { status: 502 },
    );
  }
}
