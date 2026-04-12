from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "vei" / "whatif" / "fixtures" / "enron_public_context"
RAW_ROOT = FIXTURE_ROOT / "raw"
PACKAGE_PATH = FIXTURE_ROOT / "package.json"
DATASET_PATH = FIXTURE_ROOT / "enron_public_context_v1.json"
README_PATH = FIXTURE_ROOT / "README.md"
USER_AGENT = "Mozilla/5.0 vei-enron-public-context-builder contact@example.com"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    filename: str
    url: str
    file_type: str
    description: str
    topics: tuple[str, ...]


SOURCE_DOCUMENTS: tuple[SourceDocument, ...] = (
    SourceDocument(
        source_id="enron_2000_financial_highlights",
        filename="2000_financial_highlights.pdf",
        url="https://enroncorp.com/src/doc/investors/2000_Financial_Highlights2.pdf",
        file_type="pdf",
        description="Archived Enron financial highlights with selected multi-year figures.",
        topics=("financials", "annual"),
    ),
    SourceDocument(
        source_id="enron_2000_form_10k",
        filename="2000_form_10k.pdf",
        url="https://enroncorp.com/src/doc/investors/2001-04-02-10-k.pdf",
        file_type="pdf",
        description="Enron Form 10-K for the fiscal year ended December 31, 2000.",
        topics=("financials", "annual", "filing"),
    ),
    SourceDocument(
        source_id="enron_2001_press_chronology",
        filename="2001_press_chronology.html",
        url="https://enroncorp.com/corp/pressroom/releases/2001/press_chron2001",
        file_type="html",
        description="Archived 2001 Enron press release chronology.",
        topics=("news", "timeline"),
    ),
    SourceDocument(
        source_id="enron_2001_q1_release",
        filename="2001_q1_earnings_release.html",
        url="https://enroncorp.com/corp/pressroom/releases/2001/ene/ene-q1-01-ltr",
        file_type="html",
        description="Archived first-quarter 2001 Enron earnings release.",
        topics=("financials", "quarterly"),
    ),
    SourceDocument(
        source_id="enron_2001_q2_release",
        filename="2001_q2_earnings_release.html",
        url=(
            "https://enroncorp.com/corp/pressroom/releases/2001/ene/"
            "51-enronsecondquarterrelease-07-12-01-ltr"
        ),
        file_type="html",
        description="Archived second-quarter 2001 Enron earnings release.",
        topics=("financials", "quarterly"),
    ),
    SourceDocument(
        source_id="pge_2001_q3_10q_note",
        filename="pge_2001_q3_10q.html",
        url=(
            "https://www.sec.gov/Archives/edgar/data/784977/"
            "000078497701500017/q10qtr3.htm"
        ),
        file_type="html",
        description=(
            "SEC-filed Portland General Electric 10-Q with dated notes on Enron's "
            "October and November 2001 disclosures."
        ),
        topics=("news", "financials", "regulatory"),
    ),
    SourceDocument(
        source_id="sec_enron_chapter11_record",
        filename="sec_enron_chapter11_record.html",
        url="https://www.sec.gov/file/35-27810",
        file_type="html",
        description="SEC proceeding record for the Enron Chapter 11 case.",
        topics=("news", "bankruptcy"),
    ),
)


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)

    collected_at = _timestamp_now()
    downloaded_files = _download_sources()
    _write_package_manifest(
        collected_at=collected_at, downloaded_files=downloaded_files
    )
    _write_dataset(collected_at=collected_at)
    _write_readme()

    print(f"wrote fixture: {FIXTURE_ROOT}")
    print(f"wrote manifest: {PACKAGE_PATH}")
    print(f"wrote dataset: {DATASET_PATH}")


def _download_sources() -> dict[str, dict[str, Any]]:
    downloads: dict[str, dict[str, Any]] = {}
    for source in SOURCE_DOCUMENTS:
        target = RAW_ROOT / source.filename
        payload = _fetch_bytes(source.url)
        target.write_bytes(payload)
        downloads[source.source_id] = {
            "relative_path": str(target.relative_to(FIXTURE_ROOT)),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
    return downloads


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def _write_package_manifest(
    *,
    collected_at: str,
    downloaded_files: dict[str, dict[str, Any]],
) -> None:
    sources: list[dict[str, Any]] = []
    for source in SOURCE_DOCUMENTS:
        downloaded = downloaded_files[source.source_id]
        sources.append(
            {
                "source_id": source.source_id,
                "source_system": "public_archive",
                "file_type": source.file_type,
                "relative_path": downloaded["relative_path"],
                "collected_at": collected_at,
                "redaction_status": "public_source",
                "source_url": source.url,
                "description": source.description,
                "topics": list(source.topics),
                "sha256": downloaded["sha256"],
                "size_bytes": downloaded["size_bytes"],
            }
        )

    package_payload = {
        "version": "1",
        "name": "enron_public_context",
        "title": "Enron Public Context Pack",
        "description": (
            "Archived public financial checkpoints and public-news timeline data for "
            "Enron. Intended to be filtered against the oldest and latest email dates "
            "in an Enron historical world."
        ),
        "organization_name": "Enron Corporation",
        "organization_domain": "enron.com",
        "timezone": "America/Chicago",
        "sources": sources,
        "artifacts": [
            {
                "artifact_id": "enron_public_context_v1",
                "file_type": "json",
                "relative_path": DATASET_PATH.name,
                "description": (
                    "Normalized dated financial checkpoints and public-news events for "
                    "later slicing by email time window."
                ),
            }
        ],
        "metadata": {
            "fixture": True,
            "prepared_at": collected_at,
            "notes": [
                (
                    "This pack keeps raw downloaded source files beside a normalized "
                    "JSON bundle so later integration can stay deterministic."
                )
            ],
        },
    }
    PACKAGE_PATH.write_text(
        json.dumps(package_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _write_dataset(*, collected_at: str) -> None:
    dataset_payload = {
        "version": "1",
        "pack_name": "enron_public_context",
        "organization_name": "Enron Corporation",
        "organization_domain": "enron.com",
        "prepared_at": collected_at,
        "integration_hint": (
            "At integration time, compute the oldest and latest email timestamps from "
            "the active Enron slice and keep only financial_snapshots and "
            "public_news_events whose dates overlap that email window."
        ),
        "financial_snapshots": _financial_snapshots(),
        "public_news_events": _public_news_events(),
    }
    DATASET_PATH.write_text(
        json.dumps(dataset_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _financial_snapshots() -> list[dict[str, Any]]:
    return [
        {
            "snapshot_id": "fy1998_selected_financial_data",
            "as_of": "1998-12-31T00:00:00Z",
            "kind": "annual",
            "label": "FY1998 selected financial data",
            "source_ids": ["enron_2000_financial_highlights"],
            "summary": (
                "Operating revenue was $31.26B, net income was $703M, total assets "
                "were $29.35B, shareholders' equity was $7.05B, and diluted EPS was "
                "$1.01."
            ),
            "metrics": {
                "operating_revenue_usd_millions": 31260,
                "net_income_usd_millions": 703,
                "total_assets_usd_millions": 29350,
                "shareholders_equity_usd_millions": 7048,
                "diluted_eps": 1.01,
            },
        },
        {
            "snapshot_id": "fy1999_selected_financial_data",
            "as_of": "1999-12-31T00:00:00Z",
            "kind": "annual",
            "label": "FY1999 selected financial data",
            "source_ids": ["enron_2000_financial_highlights"],
            "summary": (
                "Operating revenue was $40.11B, net income was $893M, total assets "
                "were $33.38B, shareholders' equity was $9.57B, and diluted EPS was "
                "$1.10."
            ),
            "metrics": {
                "operating_revenue_usd_millions": 40112,
                "net_income_usd_millions": 893,
                "total_assets_usd_millions": 33381,
                "shareholders_equity_usd_millions": 9570,
                "diluted_eps": 1.10,
            },
        },
        {
            "snapshot_id": "fy2000_10k",
            "as_of": "2000-12-31T00:00:00Z",
            "kind": "annual",
            "label": "FY2000 Form 10-K",
            "source_ids": [
                "enron_2000_financial_highlights",
                "enron_2000_form_10k",
            ],
            "summary": (
                "Operating revenue was $100.79B, net income was $979M, total assets "
                "were $65.50B, shareholders' equity was $11.47B, and diluted EPS was "
                "$1.12."
            ),
            "metrics": {
                "operating_revenue_usd_millions": 100789,
                "net_income_usd_millions": 979,
                "total_assets_usd_millions": 65503,
                "shareholders_equity_usd_millions": 11470,
                "diluted_eps": 1.12,
            },
        },
        {
            "snapshot_id": "q4_2000_annual_release",
            "as_of": "2001-01-22T00:00:00Z",
            "kind": "quarterly_release",
            "label": "Q4 2000 annual earnings release",
            "source_ids": ["enron_2001_press_chronology"],
            "summary": (
                "Enron publicly reported recurring annual diluted EPS of $1.47 for "
                "2000 and fourth-quarter diluted EPS of $0.41."
            ),
            "metrics": {
                "recurring_annual_diluted_eps": 1.47,
                "fourth_quarter_diluted_eps": 0.41,
            },
        },
        {
            "snapshot_id": "q1_2001_earnings_release",
            "as_of": "2001-04-17T00:00:00Z",
            "kind": "quarterly_release",
            "label": "Q1 2001 earnings release",
            "source_ids": ["enron_2001_q1_release"],
            "summary": (
                "Enron publicly reported first-quarter diluted EPS of $0.47, "
                "revenues of $50.1B, and net income of $406M."
            ),
            "metrics": {
                "revenue_usd_millions": 50100,
                "net_income_usd_millions": 406,
                "diluted_eps": 0.47,
            },
        },
        {
            "snapshot_id": "q2_2001_earnings_release",
            "as_of": "2001-07-12T00:00:00Z",
            "kind": "quarterly_release",
            "label": "Q2 2001 earnings release",
            "source_ids": ["enron_2001_q2_release"],
            "summary": (
                "Enron publicly reported second-quarter diluted EPS of $0.45 and net "
                "income of $404M."
            ),
            "metrics": {
                "net_income_usd_millions": 404,
                "diluted_eps": 0.45,
            },
        },
        {
            "snapshot_id": "q3_2001_loss_announcement",
            "as_of": "2001-10-16T00:00:00Z",
            "kind": "event_checkpoint",
            "label": "Q3 2001 loss announcement",
            "source_ids": ["pge_2001_q3_10q_note"],
            "summary": (
                "Enron announced $1.01B of after-tax non-recurring charges, which "
                "resulted in a net loss for the quarter."
            ),
            "metrics": {
                "after_tax_non_recurring_charges_usd_millions": 1010,
            },
        },
    ]


def _public_news_events() -> list[dict[str, Any]]:
    return [
        {
            "event_id": "cliff_baxter_resignation",
            "timestamp": "2001-05-02T00:00:00Z",
            "category": "governance",
            "headline": "Vice chairman Cliff Baxter resigned",
            "summary": (
                "Enron's archived 2001 press chronology records Cliff Baxter's "
                "resignation on May 2, 2001."
            ),
            "source_ids": ["enron_2001_press_chronology"],
        },
        {
            "event_id": "third_quarter_loss",
            "timestamp": "2001-10-16T00:00:00Z",
            "category": "financial_disclosure",
            "headline": "Enron announced a third-quarter loss",
            "summary": (
                "The company disclosed $1.01B in after-tax non-recurring charges and "
                "said the quarter ended in a net loss."
            ),
            "source_ids": ["pge_2001_q3_10q_note"],
        },
        {
            "event_id": "sec_information_request",
            "timestamp": "2001-10-22T00:00:00Z",
            "category": "regulatory",
            "headline": "SEC requested information about related-party transactions",
            "summary": (
                "Enron said the SEC had asked it to voluntarily provide information "
                "about certain related-party transactions."
            ),
            "source_ids": ["pge_2001_q3_10q_note"],
        },
        {
            "event_id": "special_committee_and_formal_investigation",
            "timestamp": "2001-10-31T00:00:00Z",
            "category": "regulatory",
            "headline": "Board formed a special committee and the SEC opened a formal investigation",
            "summary": (
                "Enron said its board appointed a special committee and that the SEC "
                "had opened a formal investigation into the matters under review."
            ),
            "source_ids": ["pge_2001_q3_10q_note"],
        },
        {
            "event_id": "restatement_of_prior_financials",
            "timestamp": "2001-11-08T00:00:00Z",
            "category": "restatement",
            "headline": "Enron said it would restate prior financial statements",
            "summary": (
                "Enron said it would restate results from 1997 through 2000 and the "
                "first two quarters of 2001 and reflect a $1.2B reduction in "
                "shareholders' equity."
            ),
            "source_ids": ["pge_2001_q3_10q_note"],
        },
        {
            "event_id": "dynegy_merger_announcement",
            "timestamp": "2001-11-09T00:00:00Z",
            "category": "merger",
            "headline": "Enron announced a proposed sale to Dynegy",
            "summary": (
                "Enron reported that Dynegy would acquire the company, subject to "
                "shareholder approval and other closing conditions."
            ),
            "source_ids": ["pge_2001_q3_10q_note"],
        },
        {
            "event_id": "chapter_11_filing",
            "timestamp": "2001-12-02T00:00:00Z",
            "category": "bankruptcy",
            "headline": "Enron entered Chapter 11 proceedings",
            "summary": (
                "The SEC proceeding record is used as the official source reference "
                "for Enron's Chapter 11 case."
            ),
            "source_ids": ["sec_enron_chapter11_record"],
        },
    ]


def _write_readme() -> None:
    README_PATH.write_text(
        "\n".join(
            [
                "# Enron Public Context",
                "",
                "This fixture stores public-source material that can be joined to an Enron mail slice later.",
                "",
                "Contents:",
                "- `raw/`: downloaded public-source HTML and PDF files.",
                "- `package.json`: manifest describing the raw sources and normalized artifact.",
                "- `enron_public_context_v1.json`: normalized dated financial checkpoints and public-news checkpoints.",
                "",
                "Regenerate with:",
                "- `python scripts/prepare_enron_public_context.py`",
                "",
                "Integration rule:",
                "- Read the oldest and latest email timestamps from the active Enron dataset.",
                "- Keep only the public rows whose dates overlap that email window.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _timestamp_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


if __name__ == "__main__":
    main()
