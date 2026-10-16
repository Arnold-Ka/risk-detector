// robots.txt — indique aux robots d'indexation l'URL du sitemap (feuille de
// route §7). Tout est indexable : les fiches sont le contenu public ; la
// watchlist (placeholder) se protège elle-même via un meta noindex.

import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
