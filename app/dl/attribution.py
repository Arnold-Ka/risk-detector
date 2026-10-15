"""Attribution par variable des scores LSTM (phase 2 : « explication »).

Feuille de route : le signal deep learning s'affiche « avec son
explication par variable ». On utilise SHAP GradientExplainer :

  - DeepExplainer échoue sur pack_padded_sequence (mesuré : AssertionError
    « explanations do not sum up ») — le gradient traverse tout ;
  - baseline = vecteur ZÉROS (« aucune donnée » : ratios nuls + flags
    manquant à 1) : l'attribution mesure ce que chaque variable AJOUTE
    au logit par rapport à l'absence totale d'information ;
  - sortie expliquée = le LOGIT (avant sigmoïde) : échelle additive où
    somme(des attributions) ≈ logit(x) − logit(baseline) — plus lisible
    qu'une décomposition de probabilité ;
  - attributions agrégées SUR LE TEMPS (somme des 3 à 5 exercices de la
    fenêtre) -> une contribution par feature, exploitable sur la fiche ;
  - déterminisme : graines torch + numpy fixées avant l'explainer (SHAP
    échantillonne des interpolations) — le nightly recalcule toujours
    les mêmes valeurs.

L'import de shap est DÉFÉRÉ dans explain() : l'import charge
tensorflow (bruit oneDNN) et coûte ~2 s — inutile pour les chemins qui
n'expliquent jamais rien (tests, nightly sans artefact).
"""

import os

# Bruits C++ de tensorflow au chargement de shap (la voie TF de
# l'explainer est importée même si on n'utilise que la voie torch).
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np
import torch

from app.dl.dataset import EVENT_FEATURES, FEATURE_CONCEPTS

TOP_K = 8  # variables les plus contributives affichées sur la fiche


def feature_names() -> list[str]:
    """Noms des features dans l'ORDRE du vecteur (dataset.vectorize).

    Même interleaving que vectorize : ratio puis flag « manquant » pour
    chaque concept, puis les features d'événements (v2.1). Identifiants
    anglais (convention du projet) — la traduction FR est côté frontend
    (FEATURE_LABELS dans frontend/lib/signals.ts).
    """
    names: list[str] = []
    for concept in FEATURE_CONCEPTS:
        names.append(f"{concept}_ratio")
        names.append(f"{concept}_missing")
    names.extend(EVENT_FEATURES)
    return names


class _FixedLengthScorer(torch.nn.Module):
    """Adapte LstmScorer (x, lengths) -> signature unique x exigée par SHAP.

    Sortie (B, 1) : SHAP indexe la dimension de sortie (mesuré : un (B,)
    après squeeze provoque IndexError dans l'explainer).

    PIÈGE CORRIGÉ (mesuré) : pack_padded_sequence reçoit `lengths` comme
    tenseur — il doit avoir UNE ENTRÉE PAR LIGNE du batch. Une longueur
    fixe de taille 1 (buffer) ne va que pour un batch de 1 : avec les N
    points d'interpolation de SHAP, le LSTM ne traitait que la PREMIÈRE
    ligne (sortie (1,1) au lieu de (N,1)), SHAP divisait par N et les
    attributions sortaient 50× trop petites. On reconstruit donc les
    longueurs à chaque appel depuis la forme réelle de x : toutes les
    séquences de l'explainer ont la même longueur T (aucun remplissage).
    """

    def __init__(self, model: torch.nn.Module, length: int):
        super().__init__()
        self.model = model
        self.length = int(length)  # longueur fixe T de la fenêtre

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Une longueur par ligne : compatibles batches SHAP (N points)
        # et échantillon unitaire (production).
        lengths = torch.full((x.shape[0],), self.length, dtype=torch.long)
        return self.model(x, lengths).unsqueeze(-1)


def explain(model: torch.nn.Module, sample, seed: int = 42) -> list[tuple[str, float]]:
    """Échantillon -> attributions SHAP agrégées, une par feature (logit).

    Retourne [(nom, valeur)] dans l'ordre des features : valeur positive
    = la variable pousse le logit vers le haut (vers la faillite).
    """
    import shap  # import différé (voir docstring module)

    torch.manual_seed(seed)
    np.random.seed(seed)  # certaines voies SHAP tirent sur numpy
    wrapped = _FixedLengthScorer(model, len(sample.sequence))
    x = torch.tensor(sample.sequence, dtype=torch.float32).unsqueeze(0)
    background = torch.zeros(1, *x.shape[1:])
    explainer = shap.GradientExplainer(wrapped, background)
    values = explainer.shap_values(x)  # ndarray (1, T, D, 1)
    # Agrégation temporelle : somme des contributions de chaque exercice
    # de la fenêtre -> (D,).
    per_feature = values[0].sum(axis=0).squeeze(-1)
    return list(zip(feature_names(), per_feature.tolist()))


def top_contributors(
    attribution: list[tuple[str, float]], k: int = TOP_K
) -> list[tuple[str, float]]:
    """Les k plus fortes contributions par valeur absolue (tri stable)."""
    return sorted(attribution, key=lambda t: abs(t[1]), reverse=True)[:k]
