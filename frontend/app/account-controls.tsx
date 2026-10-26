"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";

export default function AccountControls() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return <span className="h-9 w-24 animate-pulse rounded-full bg-slate-100" aria-hidden="true" />;
  }

  if (!isSignedIn) {
    return (
      <SignInButton mode="modal">
        <button className="rounded-full bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
          Connexion / inscription
        </button>
      </SignInButton>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <Link
        href="/watchlist"
        className="rounded-full border border-line px-3 py-2 text-sm font-semibold text-ink transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        Ma liste
      </Link>
      <UserButton />
    </div>
  );
}
