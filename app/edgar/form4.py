"""Parseur Form 4 — transactions des dirigeants (feuille de route §2).

Un Form 4 est un petit XML « ownershipDocument » déposé par un dirigeant
(officer), administrateur (director) ou détenteur ≥10 % lors d'une
transaction sur les actions de l'émetteur. On n'en retient ici que le
tableau NON dérivé (actions directes) — les droits dérivés (options,
warrants) sont hors périmètre v1 (« ventes massives d'actions »).

Piège EDGAR : le champ `primaryDocument` des submissions pointe vers une
version rendue par XSL (`xslF345X06/form4.xml`) qui est du HTML ; le XML
brut se trouve au MÊME chemin sans le segment `xslF…/`. Les dépôts
d'avant 2003 sont des `.hors-XML` (`.htm`) : ignorés (mandat XML ~2003).

Amendements : les Form 4/A re-déposent souvent la transaction d'origine
→ doublon garanti ; le filtre `form == "4"` (exact) côté fetch les
exclut déjà, pas de travail ici.

Sortie : une dict par (transaction × reportingOwner) — un dépôt conjoint
(2 propriétaires) produit 2 lignes par transaction, chacune avec ses
drapeaux officer/directeur.
"""

import re
import xml.etree.ElementTree as ET
from datetime import date

# Segment de rendu XSL en tête du primaryDocument (ex. "xslF345X06/…" —
# chiffres, puis X, puis chiffres : un simple \d+ s'arrêterait avant le X).
_XSL_PREFIX = re.compile(r"^xslF[0-9X]+/", re.IGNORECASE)

ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{name}"


def raw_doc_url(cik: int, accession: str, primary_doc: str) -> str | None:
    """URL du XML brut d'un Form 4, ou None si document non exploitable.

    primary_doc : champ `primaryDocument` de la submissions API
    ("" ou ".htm" pour les dépôts pré-XML → None = ignoré).
    """
    name = _XSL_PREFIX.sub("", primary_doc or "").strip()
    if not name.lower().endswith(".xml"):
        return None
    return ARCHIVES_URL.format(cik=cik, accn=accession.replace("-", ""), name=name)


def _value_text(parent, path: str) -> str | None:
    """Texte d'un <value> via chemin relatif, ""/absent -> None."""
    el = parent.find(path)
    if el is None:
        return None
    value = el.find("value")
    text = (value if value is not None else el).text
    return text.strip() if text and text.strip() else None


def _decimal(text: str | None):
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _bool_text(parent, path: str) -> bool:
    return (_value_text(parent, path) or "").lower() == "true"


def parse_form4(xml_bytes: bytes, filing: dict) -> list[dict]:
    """ownershipDocument -> transactions normalisees (dicts JSON-friendly).

    `filing` = ligne submissions de ce dépôt ({accession, filed_at, ...}) ;
    accession/filed_at sont recopiés sur chaque transaction pour tracer
    la source exacte (règle produit : chaque signal pointe un dépôt).
    Une transaction sans date est sautée (inattaquable pour un signal
    annuel) ; un XML illévévable lève (le fetcheur compte l'erreur).
    """
    root = ET.fromstring(xml_bytes)

    owners = []
    for owner in root.findall("reportingOwner"):
        rel = owner.find("reportingOwnerRelationship")
        owners.append(
            {
                "owner_name": _value_text(owner, "reportingOwnerId/rptOwnerName"),
                "is_officer": _bool_text(rel, "isOfficer") if rel is not None else False,
                "is_director": _bool_text(rel, "isDirector") if rel is not None else False,
                "officer_title": _value_text(rel, "officerTitle") if rel is not None else None,
            }
        )
    if not owners:
        owners = [{"owner_name": None, "is_officer": False, "is_director": False, "officer_title": None}]

    plan_10b5 = _value_text(root, "aff10b5One") == "true"
    transactions: list[dict] = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        raw_date = _value_text(tx, "transactionDate")
        if not raw_date:
            continue  # sans date : inutilisable pour l'affectation annuelle
        base = {
            "accession": filing["accession"],
            "filed_at": filing["filed_at"],
            "transaction_date": date.fromisoformat(raw_date[:10]),
            "code": _value_text(tx, "transactionCoding/transactionCode"),
            "shares": _decimal(_value_text(tx, "transactionAmounts/transactionShares")),
            "price": _decimal(_value_text(tx, "transactionAmounts/transactionPricePerShare")),
            "acquired_disposed": _value_text(
                tx, "transactionAmounts/transactionAcquiredDisposedCode"
            ),
            "plan_10b5_1": plan_10b5,
        }
        for owner in owners:
            transactions.append({**base, **owner})
    return transactions
