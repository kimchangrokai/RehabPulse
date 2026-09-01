"""회사·프로젝트 경로와 sidecar YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_LOOKUP_TIME = "04:00"
DEFAULT_MAIL_TIME = "07:00"
DEFAULT_MAILING = ["sonaba79@gmail.com", "kimchangrok.ai@gmail.com"]
INITIAL_COMPANIES = ("대신증권", "삼성증권")
INITIAL_PROJECT = "2608계약건"


@dataclass(frozen=True)
class ProjectRef:
    company: str
    project: str
    workbook: Path
    sidecar: Path

    def load_schedule(self) -> dict:
        if not self.sidecar.exists():
            return {
                "lookup_time": DEFAULT_LOOKUP_TIME,
                "mail_time": DEFAULT_MAIL_TIME,
            }
        with open(self.sidecar, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {
            "lookup_time": data.get("lookup_time") or DEFAULT_LOOKUP_TIME,
            "mail_time": data.get("mail_time") or DEFAULT_MAIL_TIME,
        }


def data_root(settings: dict) -> Path:
    return Path(settings.get("paths", {}).get("data", "data"))


def project_ref(settings: dict, company: str, project: str) -> ProjectRef:
    root = data_root(settings)
    folder = root / company
    return ProjectRef(
        company=company,
        project=project,
        workbook=folder / f"{project}.xlsx",
        sidecar=folder / f"{project}.yaml",
    )


def list_projects(settings: dict, company: Optional[str] = None) -> list[ProjectRef]:
    root = data_root(settings)
    if not root.exists():
        return []
    companies = [company] if company else sorted(p.name for p in root.iterdir() if p.is_dir())
    found: list[ProjectRef] = []
    for co in companies:
        folder = root / co
        if not folder.is_dir():
            continue
        for yaml_path in sorted(folder.glob("*.yaml")):
            found.append(project_ref(settings, co, yaml_path.stem))
    return found


def resolve_scope(
    settings: dict,
    company: Optional[str],
    project: Optional[str],
) -> list[ProjectRef]:
    """--company/--project 필수. 회사만 있으면 그 회사의 모든 프로젝트."""
    if not company and not project:
        raise ValueError("--company 또는 --project 가 필요합니다")
    if project and not company:
        raise ValueError("--project 는 --company 와 함께 지정하세요")
    if company and project:
        ref = project_ref(settings, company, project)
        if not ref.sidecar.exists() and not ref.workbook.exists():
            raise FileNotFoundError(f"프로젝트 없음: {company}/{project}")
        return [ref]
    found = list_projects(settings, company=company)
    if not found:
        raise FileNotFoundError(f"회사 프로젝트 없음: {company}")
    return found


def write_sidecar(ref: ProjectRef, lookup_time: str = DEFAULT_LOOKUP_TIME,
                  mail_time: str = DEFAULT_MAIL_TIME) -> None:
    ref.sidecar.parent.mkdir(parents=True, exist_ok=True)
    payload = {"lookup_time": lookup_time, "mail_time": mail_time}
    with open(ref.sidecar, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def is_weekday(now=None) -> bool:
    from datetime import datetime
    dt = now or datetime.now()
    return dt.weekday() < 5
