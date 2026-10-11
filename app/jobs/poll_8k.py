"""Polling incrémental des dépôts chauds — événements 8-K et transactions
des dirigeants (Formulaire 4), à exécuter toutes les 10 minutes (feuille de
route §4, composant 1), contrairement au job massif nocturne.

Pourquoi séparé : les 8-K et Form 4 alimentent des alertes *promptes* (l'offre
payante promet « dans les 15 minutes »), elles ne peuvent donc pas attendre
le job de nuit.

TODO(phase 1) : interroger le flux data.sec.gov/submissions pour les nouveaux
dépôts des entreprises suivies, analyser les items 8-K (1.03, 2.04, 4.01,
4.02, 5.02) et le XML des Form 4, puis écrire les lignes dans `filings` +
`signals`.
"""
