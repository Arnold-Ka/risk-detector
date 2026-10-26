import { NextResponse } from "next/server";
import { forwardWatchlistRequest } from "@/lib/server-watchlist";

export async function GET() {
  return forwardWatchlistRequest("GET", "");
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Requête JSON invalide." }, { status: 400 });
  }

  if (
    !body ||
    typeof body !== "object" ||
    !("cik" in body) ||
    typeof body.cik !== "number" ||
    !Number.isInteger(body.cik) ||
    body.cik <= 0
  ) {
    return NextResponse.json(
      { detail: "Indiquez un identifiant d'entreprise valide." },
      { status: 400 },
    );
  }

  return forwardWatchlistRequest("POST", "", { cik: body.cik });
}

export async function DELETE(request: Request) {
  const value = new URL(request.url).searchParams.get("cik");
  const cik = value ? Number(value) : Number.NaN;
  if (!Number.isInteger(cik) || cik <= 0) {
    return NextResponse.json(
      { detail: "Indiquez un identifiant d'entreprise valide." },
      { status: 400 },
    );
  }

  return forwardWatchlistRequest("DELETE", `/${cik}`);
}
