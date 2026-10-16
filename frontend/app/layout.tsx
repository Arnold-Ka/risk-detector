import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import { SITE_URL } from "@/lib/site";
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
    "Alertes précoces sur les entreprises cotées américaines, avec sources exactes. Information générale, pas un conseil en investissement.",
  openGraph: {
    siteName: "Détecteur de risque financier",
    locale: "fr_FR",
    type: "website",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="fr"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-white text-gray-900">
        {/* Navigation simple : la liste des pages publiques vit dans
            sitemap.ts (fiches indexables, phase 2). */}
        <header className="border-b border-gray-200">
          <nav className="mx-auto flex max-w-2xl items-center gap-6 px-4 py-3 text-sm font-medium">
            <Link href="/" className="hover:text-blue-600">
              Accueil
            </Link>
            <Link href="/watchlist" className="hover:text-blue-600">
              Ma liste de suivi
            </Link>
          </nav>
        </header>

        <div className="flex-1">{children}</div>

        {/* Mention légale obligatoire sur chaque page (feuille de route §11 :
            information générale, jamais un conseil d'achat/vente). */}
        <footer className="border-t border-gray-200">
          <p className="mx-auto max-w-2xl px-4 py-4 text-xs text-gray-500">
            Information générale — pas un conseil en investissement. Chaque
            signal sera relié à sa source exacte (dépôt SEC).
          </p>
        </footer>
      </body>
    </html>
  );
}
