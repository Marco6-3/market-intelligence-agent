from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..models import ReportData

SOURCE_COLUMNS = [
    "record_type",
    "ticker",
    "title",
    "source_name",
    "source_url",
    "final_url",
    "aggregator_url",
    "source_quality",
    "freshness",
    "cluster_id",
    "published_at",
    "fetched_at",
]


def write_sources_csv(report: ReportData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.model_dump(mode="json") for record in report.sources]
    frame = pd.DataFrame(rows, columns=SOURCE_COLUMNS)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
