// Liste de suivi — placeholder jusqu'à la phase 2 (comptes utilisateurs +
// table watchlists, feuille de route §7). Page server component statique.

export default function WatchlistPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">Ma liste de suivi</h1>
      <p className="mt-4 text-gray-600">
        Fonctionnalité prévue en <strong>phase 2</strong> : compte utilisateur
        et jusqu&apos;à 10 entreprises suivies en gratuit, avec alertes par
        e-mail quand un nouveau signal apparaît.
      </p>
      <p className="mt-2 text-gray-500 text-sm">
        En attendant, aucune donnée à afficher.
      </p>
    </main>
  );
}
