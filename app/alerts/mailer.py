"""Envoi des alertes par e-mail (SMTP de la bibliothèque standard).

Pourquoi SMTP plutôt que le SDK d'un fournisseur : aucune dépendance
ajoutée, et tous les services d'envoi (Brevo, Resend, Mailgun, SES, Gmail…)
exposent un relais SMTP. Changer de fournisseur = changer 4 variables
d'environnement, pas le code.

Envoi DÉSACTIVÉ tant que SMTP_HOST ou ALERT_FROM_EMAIL est vide : le
nightly journalise alors les changements détectés sans rien envoyer. C'est
le comportement en local, en CI et sur toute installation non configurée.

Confidentialité des journaux : le nightly tourne sur GitHub Actions, dont
les journaux sont publics si le dépôt l'est. On n'y écrit JAMAIS d'adresse
e-mail — seulement des comptes et des tickers (données publiques).
"""

import smtplib
from email.message import EmailMessage

from app.alerts.changes import LevelChange, build_digest
from app.config import Settings, settings


def alerts_enabled(config: Settings = settings) -> bool:
    return bool(config.smtp_host and config.alert_from_email)


def _connect(config: Settings) -> smtplib.SMTP:
    """Connexion authentifiée au relais. 465 = TLS implicite, sinon STARTTLS."""
    if config.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            config.smtp_host, config.smtp_port, timeout=30
        )
    else:
        server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
        server.starttls()
    if config.smtp_username:
        server.login(config.smtp_username, config.smtp_password)
    return server


def send_digests(
    digests: dict[str, list[LevelChange]], config: Settings = settings
) -> dict[str, int]:
    """Envoie un e-mail par destinataire ; renvoie {"sent", "failed", "skipped"}.

    Un échec sur un destinataire n'empêche pas les suivants (même esprit
    que le nightly : on journalise et on continue). Une connexion unique
    pour tout le lot : les relais limitent souvent le nombre de connexions.
    """
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    if not digests:
        return stats
    if not alerts_enabled(config):
        stats["skipped"] = len(digests)
        return stats

    try:
        server = _connect(config)
    except (OSError, smtplib.SMTPException) as exc:
        # Relais injoignable ou identifiants refusés : tout le lot échoue.
        print(f"  !! alertes : connexion SMTP impossible ({type(exc).__name__})")
        stats["failed"] = len(digests)
        return stats

    try:
        for recipient, changes in digests.items():
            subject, body = build_digest(changes, config.site_url)
            message = EmailMessage()
            message["From"] = config.alert_from_email
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(body)
            try:
                server.send_message(message)
                stats["sent"] += 1
            except smtplib.SMTPException as exc:
                stats["failed"] += 1
                print(f"  !! alertes : envoi refusé ({type(exc).__name__})")
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            pass
    return stats
