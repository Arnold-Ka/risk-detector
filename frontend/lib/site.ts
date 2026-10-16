// URL publique absolue du site — utilisée par metadataBase (Open Graph),
// sitemap.xml et robots.txt. En production, poser NEXT_PUBLIC_SITE_URL
// (ex. https://detecteur-risque.fr) ; en dev, le fallback localhost suffit.

export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
