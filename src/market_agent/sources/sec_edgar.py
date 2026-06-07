from __future__ import annotations

from typing import Any

from ..cache import FileCache
from ..intelligence import classify_filing_materiality
from ..models import FilingItem
from ..utils.text import truncate
from ..utils.time import coerce_datetime_string, utc_now_iso

SEC_SOURCE = "SEC EDGAR"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class SECEdgarClient:
    def __init__(self, user_agent: str, cache: FileCache) -> None:
        self.cache = cache
        self.headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

    def fetch_recent_filings(self, ticker: str, limit: int = 6) -> list[FilingItem]:
        cik = self.lookup_cik(ticker)
        if not cik:
            return []

        padded_cik = str(cik).zfill(10)
        url = SEC_SUBMISSIONS_URL.format(cik=padded_cik)
        data = self.cache.get_json(SEC_SOURCE, url, headers=self.headers)
        recent = data.get("filings", {}).get("recent", {}) if isinstance(data, dict) else {}
        forms = recent.get("form", [])
        fetched_at = utc_now_iso()
        filings: list[FilingItem] = []

        for index, form in enumerate(forms[:limit]):
            filing_date = _array_value(recent, "filingDate", index)
            accession_number = _array_value(recent, "accessionNumber", index)
            primary_document = _array_value(recent, "primaryDocument", index)
            description = _array_value(recent, "primaryDocDescription", index)
            source_url = _filing_url(cik, accession_number, primary_document) or url
            document_text = (
                self._safe_primary_document_text(source_url)
                if _needs_primary_document_text(form, description)
                else None
            )
            materiality, why_it_matters, thesis_effect, confidence = classify_filing_materiality(
                form=form,
                description=description,
                document_text=document_text,
            )
            form_text = str(form)
            title = f"{form_text} filing"
            if description:
                title = f"{form_text} - {truncate(description, 180)}"

            filings.append(
                FilingItem(
                    ticker=ticker,
                    form=form_text,
                    title=title,
                    summary=_filing_summary(form_text, filing_date, description),
                    materiality=materiality,
                    why_it_matters=why_it_matters,
                    thesis_effect=thesis_effect,
                    confidence=confidence,
                    filing_date=filing_date,
                    accession_number=accession_number,
                    description=truncate(description, 240),
                    source_name=SEC_SOURCE,
                    source_url=source_url,
                    final_url=source_url,
                    canonical_url=source_url,
                    canonical_url_status="resolved",
                    published_at=coerce_datetime_string(filing_date),
                    fetched_at=fetched_at,
                )
            )
        return filings

    def lookup_cik(self, ticker: str) -> str | None:
        data = self.cache.get_json(SEC_SOURCE, SEC_TICKERS_URL, headers=self.headers)
        ticker_upper = ticker.upper()
        if isinstance(data, dict):
            rows = data.values()
        elif isinstance(data, list):
            rows = data
        else:
            return None

        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("ticker", "")).upper() == ticker_upper:
                cik = row.get("cik_str")
                return str(cik) if cik is not None else None
        return None

    def _safe_primary_document_text(self, source_url: str | None) -> str | None:
        if not source_url or not source_url.startswith("https://www.sec.gov/Archives/"):
            return None
        try:
            return self.cache.get_text(SEC_SOURCE, source_url, headers=self.headers)
        except Exception:
            return None


def _array_value(container: dict[str, list[Any]], key: str, index: int) -> str | None:
    values = container.get(key, [])
    if index >= len(values):
        return None
    value = values[index]
    return None if value in (None, "") else str(value)


def _filing_url(cik: str, accession_number: str | None, primary_document: str | None) -> str | None:
    if not accession_number or not primary_document:
        return None
    accession_path = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_document}"


def _filing_summary(form: str, filing_date: str | None, description: str | None) -> str:
    parts = [f"form={form}"]
    if filing_date:
        parts.append(f"filing_date={filing_date}")
    if description:
        parts.append(f"description={truncate(description, 240)}")
    return "; ".join(parts)


def _needs_primary_document_text(form: object, description: object) -> bool:
    form_upper = str(form or "").upper()
    description_text = str(description or "").casefold()
    if form_upper in {"4", "FORM 4", "144", "FORM 144", "SD"}:
        return True
    return "earnings release" in description_text or "results of operations" in description_text
