"""Tests des alertes de changement de palier (pur + SMTP simulé, sans réseau)."""

import smtplib

import pytest

from app.alerts import mailer
from app.alerts.changes import (
    LevelChange,
    build_digest,
    detect_level_change,
    latest_composite_of,
)
from app.config import settings
from app.signals.common import SignalResult

COMPANY = {"cik": 1411579, "name": "AMC Entertainment", "ticker": "AMC",
           "sector_group": "other"}


def _composite(severity: str, period_end: str = "2024-12-31", **components) -> dict:
    return {"period_end": period_end, "severity": severity, "components": components}


def test_level_change_lists_only_components_that_moved():
    before = _composite("modéré", runway="saine", altman="défaillance")
    after = _composite("élevé", runway="défaillance", altman="défaillance",
                       late_filing="vigilance")

    change = detect_level_change(COMPANY, before, after)

    assert change is not None
    assert (change.before, change.after, change.is_increase) == ("modéré", "élevé", True)
    # Ordre des libellés (runway avant late_filing), altman inchangé exclu,
    # composante apparue = None avant.
    assert change.components == (
        ("runway", "saine", "défaillance"),
        ("late_filing", None, "vigilance"),
    )


@pytest.mark.parametrize(
    ("company", "before", "after"),
    [
        # Même palier : rien à dire, même si une composante a bougé.
        (COMPANY, _composite("modéré", runway="saine"),
         _composite("modéré", runway="vigilance")),
        # Première fois calculée : pas d'alerte « nouveau » à l'amorçage.
        (COMPANY, None, _composite("critique")),
        # Plus de composite : une donnée manquante n'est pas une baisse.
        (COMPANY, _composite("élevé"), None),
        # Banques/assurances/REIT : scores filtrés à l'affichage.
        ({**COMPANY, "sector_group": "bank"}, _composite("faible"),
         _composite("critique")),
        # Niveau hors vocabulaire : se taire plutôt qu'alerter à tort.
        (COMPANY, _composite("inconnu"), _composite("critique")),
    ],
)
def test_no_alert_cases(company, before, after):
    assert detect_level_change(company, before, after) is None


def test_latest_composite_of_picks_most_recent_fiscal_year():
    results = [
        SignalResult("composite", "2023-12-31", 0.4, "faible",
                     {"components": {"runway": "saine"}}),
        SignalResult("composite", "2024-12-31", 1.2, "élevé",
                     {"components": {"runway": "défaillance"}}),
        SignalResult("runway", "2024-12-31", 8.0, "défaillance", {}, "f1"),
    ]

    assert latest_composite_of(results) == _composite(
        "élevé", runway="défaillance"
    )
    assert latest_composite_of([results[2]]) is None


def _change(name="AMC Entertainment", ticker="AMC", cik=1411579,
            before="modéré", after="élevé", before_period="2024-12-31",
            after_period="2024-12-31", components=()):
    return LevelChange(cik, name, ticker, before, after, before_period,
                       after_period, components)


def test_digest_single_change_has_direction_links_and_disclaimer():
    subject, body = build_digest(
        [_change(components=(("runway", "saine", "défaillance"),))],
        "https://risque.example/",
    )

    assert subject == "Risque en hausse : AMC (modéré → élevé)"
    assert "▲ AMC — AMC Entertainment" in body
    assert "Autonomie de trésorerie : saine → défaillance" in body
    # Pas de double « / » malgré la barre finale de site_url.
    assert "https://risque.example/company/1411579" in body
    assert "https://risque.example/watchlist" in body
    assert "pas des prévisions de faillite" in body


def test_digest_groups_increases_first_and_flags_new_fiscal_year():
    down = _change(name="Apple", ticker="AAPL", cik=320193,
                   before="modéré", after="faible")
    up = _change(name="Zeta", ticker=None, cik=1, before="faible",
                 after="critique", before_period="2023-12-31",
                 after_period="2024-12-31")

    subject, body = build_digest([down, up], "https://risque.example")

    assert subject == "Risque : 2 changements sur votre liste de suivi"
    # Hausse (Zeta) avant baisse (Apple), malgré l'ordre alphabétique.
    assert body.index("▲ Zeta") < body.index("▼ AAPL — Apple")
    assert "nouvel exercice clos le 2024-12-31 (précédent : 2023-12-31)" in body


class FakeSMTP:
    """Relais SMTP en mémoire : enregistre les messages, peut refuser un destinataire."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port
        self.sent, self.calls = [], []
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, message):
        if message["To"] == "refuse@example.com":
            raise smtplib.SMTPRecipientsRefused({})
        self.sent.append(message)

    def quit(self):
        self.calls.append("quit")


def _config(**overrides):
    return settings.model_copy(update={
        "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_username": "user", "smtp_password": "pw",
        "alert_from_email": "alertes@example.com",
        "site_url": "https://risque.example", **overrides,
    })


def test_send_digests_one_message_per_recipient_and_continues_on_failure(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)

    stats = mailer.send_digests(
        {"a@example.com": [_change()], "refuse@example.com": [_change()]},
        _config(),
    )

    assert stats == {"sent": 1, "failed": 1, "skipped": 0}
    server = FakeSMTP.instances[0]
    assert server.calls == ["starttls", ("login", "user"), "quit"]
    assert server.sent[0]["From"] == "alertes@example.com"
    assert server.sent[0]["Subject"].startswith("Risque en hausse")


def test_send_digests_is_disabled_without_smtp_host(monkeypatch):
    def _no_network(*args, **kwargs):
        raise AssertionError("aucune connexion SMTP attendue")

    monkeypatch.setattr(mailer.smtplib, "SMTP", _no_network)

    stats = mailer.send_digests({"a@example.com": [_change()]},
                                _config(smtp_host=""))

    assert stats == {"sent": 0, "failed": 0, "skipped": 1}
