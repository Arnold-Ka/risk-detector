# Tests du modele LSTM : AUC rangs + collate (pas d'entrainement ici).
from datetime import date

import torch

from app.dl.dataset import INPUT_DIM, Sample
from app.dl.model import LstmScorer, auc_rank, collate, predict, seed_everything


def _sample(cik, year, label):
    # Vecteur de la bonne dimension (36 ratios + 4 evenements v2).
    vec = (0.1, 0.0) * 18 + (0.0,) * 4
    return Sample(
        cik=cik,
        period_end=date(year, 12, 31),
        availability=date(year + 1, 3, 1),
        sequence=(vec, vec),
        label=label,
    )


def test_auc_rank_perfect_and_inverted():
    assert auc_rank([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auc_rank([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert auc_rank([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5  # egalites
    assert auc_rank([0, 0], [0.1, 0.2]) == 0.5  # une seule classe


def test_collate_and_forward_shapes():
    seed_everything(0)
    samples = [_sample(1, 2018, 0), _sample(2, 2019, 1), _sample(3, 2020, 0)]
    samples[0] = Sample(
        cik=1,
        period_end=date(2018, 12, 31),
        availability=date(2019, 3, 1),
        # 3 ans de vecteurs v2 (36 + 4) pour forcer un pad inegal.
        sequence=(
            (0.1, 0.0) * 18 + (0.0,) * 4,
            (0.2, 0.0) * 18 + (0.0,) * 4,
            (0.3, 0.0) * 18 + (0.0,) * 4,
        ),
        label=0,
    )
    x, lengths, y = collate(samples)
    assert x.shape == (3, 3, INPUT_DIM)  # pad a la longueur max = 3
    assert lengths.tolist() == [3, 2, 2]
    assert y.tolist() == [0.0, 1.0, 0.0]
    model = LstmScorer(input_dim=INPUT_DIM, hidden=8)
    logits = model(x, lengths)
    assert logits.shape == (3,)
    probs = predict(model, samples)
    assert len(probs) == 3 and all(0.0 <= p <= 1.0 for p in probs)
    # Eval mode verrouille le dropout/rng : deux passes identiques.
    assert predict(model, samples) == probs
    assert isinstance(model.lstm, torch.nn.LSTM)
