"""M3 — 백업, 스케줄러, 캡차 재시도 상수."""

import inspect
from pathlib import Path

from rehabpulse.fetch.ssgo import fetch_case
from rehabpulse.store.excel_store import ExcelStore


ROOT = Path(__file__).resolve().parents[1]


class TestSchedulerScripts:
    def test_register_task_is_weekday_0900(self):
        text = (ROOT / "scripts" / "register_task.ps1").read_text(encoding="utf-8")
        assert "WEEKLY" in text
        assert "MON,TUE,WED,THU,FRI" in text
        assert "09:00" in text
        assert "RehabPulse Daily Sync" in text

    def test_run_sync_cmd(self):
        text = (ROOT / "scripts" / "run_sync.cmd").read_text(encoding="utf-8")
        assert "rehabpulse sync" in text
        assert "scheduler.log" in text

    def test_run_report_cmd(self):
        text = (ROOT / "scripts" / "run_report.cmd").read_text(encoding="utf-8")
        assert "rehabpulse report --email" in text


class TestCaptchaRetry:
    def test_default_one_retry(self):
        default = inspect.signature(fetch_case).parameters["max_captcha_retries"].default
        assert default == 1


class TestBackupRetention:
    def test_prunes_old_backups(self, tmp_path):
        store = ExcelStore(
            tmp_path / "rehabpulse.xlsx",
            tmp_path / "backup",
            retention=2,
        )
        store.load()
        store.save()
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(exist_ok=True)
        for i in range(5):
            (backup_dir / f"rehabpulse_2026010{i}_120000.xlsx").write_bytes(b"x")
        store.save()
        backups = list(backup_dir.glob("rehabpulse_*.xlsx"))
        assert len(backups) == 2
