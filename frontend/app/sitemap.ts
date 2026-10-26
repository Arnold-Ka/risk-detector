// sitemap.xml — feuille de route §7 : « pages publiques par entreprise,
// indexables par Google (une source de visiteurs gratuite et durable) ».
//
// Conventions Next 16 : sitemap.(ts) = route handler spécial, renvoie un
// MetadataRoute.Sitemap. Le fetch API est NON mis en cache (cf. lib/api.ts)
// → la route est dynamique : le sitemap est régénéré à chaque requête de
// robot, donc une entreprise ingérée hier apparaît tout de suite (pas
// d'attente de redéploiement). ~875 lignes d'identité par appel : négligeable.
//
// Les espaces privés/utilitaires (liste de suivi et annuaire de couverture)
// restent noindex et n'entrent pas dans le sitemap public.

import type { MetadataRoute } from "next";
import { fetchCompanyList } from "@/lib/api";
import { SITE_URL } from "@/lib/site";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entry = (
    path: string,
    priority: number,
    changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"],
  ): MetadataRoute.Sitemap[number] => ({
    url: `${SITE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency,
    priority,
  });

  const staticPages: MetadataRoute.Sitemap = [entry("/", 1, "weekly")];

  // API injoignable au moment de la génération : on renvoie les pages
  // statiques plutôt que d'échouer — la prochaine requête réessaiera.
  const result = await fetchCompanyList();
  const companies = result.state === "ready" ? result.results : [];

  return [
    ...staticPages,
    ...companies.map((c) => entry(`/company/${c.cik}`, 0.6, "weekly")),
  ];
}
