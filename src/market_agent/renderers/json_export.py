from __future__ import annotations

import json
from pathlib import Path

from ..models import ReportData


def write_json_report(report: ReportData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
