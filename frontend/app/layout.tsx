import type { Metadata } from "next";
import Link from "next/link";
import { ClerkProvider } from "@clerk/nextjs";
import { frFR } from "@clerk/localizations";
import { Geist, Geist_Mono } from "next/font/google";
import { SITE_URL } from "@/lib/site";
import AccountControls from "./account-controls";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Métadonnées racine : affichées par défaut sur toutes les pages (chaque
// page peut les surcharger, cf. generateMetadata sur /company/[cik]).
// Langue fr : l'interface est en français (convention projet).
// metadataBase : rend les URLs relatives (canonical, OG) absolues pour les
// moteurs — sans lui Next avertit et les crawlers reçoivent des URL vides.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Détecteur de risque financier",
  description:
    "Un résumé clair des signaux financiers des entreprises américaines, fondé sur leurs dépôts publics.",
  openGraph: {
    siteName: "Détecteur de risque financier",
    locale: "fr_FR",
    type: "website",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const clerkPublishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const clerkConfigured = Boolean(
    clerkPublishableKey && process.env.CLERK_SECRET_KEY,
  );

  const application = (
    <>
      <header className="sticky top-0 z-20 border-b border-line/80 bg-white/90 backdrop-blur-xl">
        <nav className="mx-auto flex h-[4.5rem] max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="group flex items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand">
            <span className="flex size-10 items-center justify-center rounded-xl bg-brand text-white shadow-sm shadow-brand/20 transition group-hover:bg-brand-dark">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                className="size-5"
              >
                <path
                  d="M4 18.5h16M6.5 15V11m5 4V6m5 9v-6"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                />
              </svg>
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-bold tracking-tight text-ink sm:text-base">
                Détecteur de risque
              </span>
              <span className="hidden text-xs text-muted sm:block">
                Entreprises américaines
              </span>
            </span>
          </Link>
          <div className="flex items-center gap-2 sm:gap-4">
            {clerkConfigured && <AccountControls />}
            <Link
              href="/coverage"
              className="hidden rounded-full border border-line px-3 py-2 text-sm font-semibold text-ink transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand md:inline-flex"
            >
              Couverture
            </Link>
            <Link
              href="/"
              className="hidden rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink transition hover:border-brand/30 hover:bg-brand-soft hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand sm:inline-flex"
            >
              Rechercher
            </Link>
          </div>
        </nav>
      </header>

      <div className="flex-1">{children}</div>

      <footer className="mt-16 border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-xs leading-5 text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <p>
            Analyse informative fondée sur les dépôts publics. Elle ne constitue
            pas un conseil en investissement ni une prédiction de faillite.
          </p>
          <p className="shrink-0 font-medium text-ink/70">
            Sources : dépôts publics de la SEC
          </p>
        </div>
      </footer>
    </>
  );

  return (
    <html
      lang="fr"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-screen flex-col bg-canvas text-ink">
        {clerkConfigured && clerkPublishableKey ? (
          <ClerkProvider
            publishableKey={clerkPublishableKey}
            localization={frFR}
            appearance={{
              variables: {
                colorPrimary: "#176b70",
                borderRadius: "0.75rem",
              },
            }}
          >
            {application}
          </ClerkProvider>
        ) : (
          application
        )}
      </body>
    </html>
  );
}
