"""LSTM PyTorch pour le signal de risque (§6, gate 2) — sans sklearn.

Le cohort est déséquilibré (~700 positifs / ~12 000 négatifs) :
perte BCEWithLogits pondérée (pos_weight = nég/pos) + early stopping sur
l'AUC de validation. AUC calculée à la main (rang de Mann-Whitney) —
scikit-learn n'est pas dans le projet et une AUC de tri est 20 lignes.
"""

import random

import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence

from app.dl.dataset import Sample


class LstmScorer(nn.Module):
    """Séquence de vecteurs annuels -> logit de faillite à 12 mois."""

    def __init__(self, input_dim: int, hidden: int = 64, layers: int = 1):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden, num_layers=layers, batch_first=True)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        # Séquences de longueur variable (3..5) : on emballe pour que le
        # dernier état LSTM soit celui du vrai dernier exercice.
        packed = pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        _, (h_n, _) = self.lstm(packed)
        return self.head(h_n[-1]).squeeze(-1)  # (B,)


def seed_everything(seed: int = 42) -> None:
    """Graines torch/python : run reproductible (CPU, pas de CUDA ici)."""
    random.seed(seed)
    torch.manual_seed(seed)


def collate(samples: list[Sample]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Échantillons -> (X padé, longueurs, labels)."""
    lengths = torch.tensor([len(s.sequence) for s in samples])
    max_len = int(lengths.max())
    dim = len(samples[0].sequence[0])
    x = torch.zeros(len(samples), max_len, dim)
    for i, s in enumerate(samples):
        for t, vec in enumerate(s.sequence):
            x[i, t] = torch.tensor(vec)
    y = torch.tensor([s.label for s in samples], dtype=torch.float32)
    return x, lengths, y


def auc_rank(y_true: list[int], scores: list[float]) -> float:
    """AUC = P(score+ > score-) via les rangs (Mann-Whitney U).

    Tirage des rangs stable (les égalités partagent le rang moyen).
    Retourne 0.5 si une seule classe est présente.
    """
    pos = [s for s, y in zip(scores, y_true) if y == 1]
    neg = [s for s, y in zip(scores, y_true) if y == 0]
    if not pos or not neg:
        return 0.5
    ranked = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(ranked):  # blocs d'égalités -> rang moyen
        j = i
        while j + 1 < len(ranked) and scores[ranked[j + 1]] == scores[ranked[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1  # rangs 1..n
        for k in range(i, j + 1):
            ranks[ranked[k]] = mean_rank
        i = j + 1
    rank_pos_sum = sum(r for r, y in zip(ranks, y_true) if y == 1)
    u = rank_pos_sum - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


@torch.no_grad()
def predict(model: nn.Module, samples: list[Sample]) -> list[float]:
    """Probas (sigmoïde) pour chaque échantillon."""
    model.eval()
    probs: list[float] = []
    for start in range(0, len(samples), 256):  # mini-batches de 256
        batch = samples[start : start + 256]
        x, lengths, _ = collate(batch)
        logits = model(x, lengths)
        probs.extend(torch.sigmoid(logits).tolist())
    return probs


def train_model(
    train: list[Sample],
    val: list[Sample],
    input_dim: int,
    max_epochs: int = 60,
    patience: int = 10,
    lr: float = 1e-3,
    batch_size: int = 64,
    seed: int = 42,
) -> tuple[LstmScorer, float]:
    """Entraîne avec early stopping sur l'AUC de validation -> (modèle, AUC max).

    pos_weight = nég/pos du train : sans ça, le déséquilibre (≈5% de
    positifs) ferait prédire « toujours sain » avec une loss très basse.
    """
    seed_everything(seed)
    n_pos = sum(s.label for s in train)
    n_neg = len(train) - n_pos
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)])
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    model = LstmScorer(input_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    best_auc, best_state, bad = -1.0, None, 0
    for _epoch in range(max_epochs):
        model.train()
        order = list(range(len(train)))
        random.shuffle(order)  # mini-batches mélangés à chaque époque
        for start in range(0, len(order), batch_size):
            batch = [train[i] for i in order[start : start + batch_size]]
            x, lengths, y = collate(batch)
            optimizer.zero_grad()
            loss = criterion(model(x, lengths), y)
            loss.backward()
            optimizer.step()

        val_scores = predict(model, val)
        auc = auc_rank([s.label for s in val], val_scores)
        if auc > best_auc + 1e-4:
            best_auc, bad = auc, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_auc
