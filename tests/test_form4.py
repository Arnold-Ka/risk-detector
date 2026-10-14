# Tests du parseur Form 4 (XML ownership) — fixture = vrai dépôt Apple.
import sys
from datetime import date
from pathlib import Path

from app.edgar.form4 import parse_form4, raw_doc_url

FIXTURE = Path("tests/fixtures/form4_apple_sale.xml")

FILING = {
    "accession": "0001140361-26-039158",
    "filed_at": "2026-10-08",
}


def test_parse_real_apple_sale():
    txs = parse_form4(FIXTURE.read_bytes(), FILING)
    assert len(txs) == 1
    tx = txs[0]
    assert tx["code"] == "S"
    assert tx["transaction_date"] == date(2026, 10, 6)
    assert tx["shares"] == 2399.0
    assert tx["price"] == 332.01
    assert tx["acquired_disposed"] == "D"
    assert tx["owner_name"] == "Newstead Jennifer"
    assert tx["is_officer"] is True and tx["is_director"] is False
    assert tx["officer_title"] == "SVP, GC and Government Affairs"
    assert tx["plan_10b5_1"] is True
    assert tx["accession"] == FILING["accession"]


def test_raw_doc_url_strips_xsl_and_rejects_html():
    url = raw_doc_url(
        320193, "0001140361-26-039158", "xslF345X06/form4.xml"
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000114036126039158/form4.xml"
    )
    # Depots pre-2003 (.htm) et primaryDocument vide : non exploitables.
    assert raw_doc_url(320193, "0001-26-0001", "j8739_4.htm") is None
    assert raw_doc_url(320193, "0001-26-0001", "") is None


def test_joint_filing_cross_product():
    # Depot conjoint (2 proprietaires) : chaque transaction x chaque owner.
    xml = b"""<?xml version="1.0"?>
    <ownershipDocument>
      <reportingOwner>
        <reportingOwnerId><rptOwnerName>Alice</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>true</isDirector><isOfficer>false</isOfficer>
        </reportingOwnerRelationship>
      </reportingOwner>
      <reportingOwner>
        <reportingOwnerId><rptOwnerName>Bob</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship>
          <isDirector>false</isDirector><isOfficer>true</isOfficer>
          <officerTitle>CFO</officerTitle>
        </reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionDate><value>2024-01-15</value></transactionDate>
          <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>100</value></transactionShares>
            <transactionPricePerShare><value></value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""
    txs = parse_form4(xml, FILING)
    assert len(txs) == 2
    assert {t["owner_name"] for t in txs} == {"Alice", "Bob"}
    # Prix vide -> None (jamais 0 invente).
    assert all(t["price"] is None for t in txs)
    assert all(t["shares"] == 100.0 for t in txs)
