"""회사·프로젝트 경로와 스코프."""

import pytest

from rehabpulse.projects import (
    resolve_scope, list_projects, write_sidecar, project_ref,
    is_weekday, DEFAULT_LOOKUP_TIME, DEFAULT_MAIL_TIME,
)
from rehabpulse.cli import cmd_init, cmd_add, cmd_sync, cmd_report
from rehabpulse.health import collect_issues, report_file
from rehabpulse.models import CaseRecord
from rehabpulse.store.excel_store import ExcelStore


def _settings(tmp_path):
    return {
        "paths": {
            "data": str(tmp_path / "data"),
            "backup": str(tmp_path / "backup"),
            "reports": str(tmp_path / "reports"),
        },
        "backup": {"retention": 3},
        "email": {
            "enabled": False,
            "operator": "realtyscope.ai@gmail.com",
        },
    }


class TestScope:
    def test_missing_scope_raises(self, tmp_path):
        with pytest.raises(ValueError, match="--company 또는 --project"):
            resolve_scope(_settings(tmp_path), None, None)

    def test_project_without_company_raises(self, tmp_path):
        with pytest.raises(ValueError, match="--company"):
            resolve_scope(_settings(tmp_path), None, "2608계약건")

    def test_sync_without_scope_errors(self, tmp_path, capsys):
        code = cmd_sync(_settings(tmp_path))
        assert code == 1
        assert "필요합니다" in capsys.readouterr().out


class TestInitAndWorkbook:
    def test_init_creates_two_projects_and_mailing(self, tmp_path):
        settings = _settings(tmp_path)
        assert cmd_init(settings) == 0
        refs = list_projects(settings)
        assert {(r.company, r.project) for r in refs} == {
            ("대신증권", "2608계약건"),
            ("삼성증권", "2608계약건"),
        }
        for ref in refs:
            assert ref.workbook.exists()
            assert ref.sidecar.exists()
            sched = ref.load_schedule()
            assert sched["lookup_time"] == DEFAULT_LOOKUP_TIME
            assert sched["mail_time"] == DEFAULT_MAIL_TIME
            store = ExcelStore(ref.workbook, tmp_path / "backup")
            store.load()
            mailing = store.list_mailing()
            assert "sonaba79@gmail.com" in mailing
            assert "kimchangrok.ai@gmail.com" in mailing
            store.add_assignee("김담당", "owner@example.com")
            store.save()
            store.load()
            assert ("김담당", "owner@example.com") in store.list_assignees()
            assert "owner@example.com" not in store.list_mailing()

    def test_same_case_in_two_projects(self, tmp_path):
        settings = _settings(tmp_path)
        cmd_init(settings)
        case = "인천지방법원 2024개회176313"
        assert cmd_add(case, "박미리", settings, "대신증권", "2608계약건") == 0
        assert cmd_add(case, "박미리", settings, "삼성증권", "2608계약건") == 0
        assert cmd_add(case, "박미리", settings, "대신증권", "2608계약건") == 1

    def test_report_writes_file(self, tmp_path):
        settings = _settings(tmp_path)
        cmd_init(settings)
        assert cmd_report(settings, company="대신증권", project="2608계약건") == 0
        ref = project_ref(settings, "대신증권", "2608계약건")
        assert report_file(settings, ref).exists()

    def test_write_status_report_from_excel(self, tmp_path):
        from rehabpulse.cli import _write_status_report
        settings = _settings(tmp_path)
        cmd_init(settings)
        cmd_add(
            "인천지방법원 2024개회176313", "박미리",
            settings, "대신증권", "2608계약건",
        )
        ref = project_ref(settings, "대신증권", "2608계약건")
        store = ExcelStore(ref.workbook, tmp_path / "backup")
        store.load()
        text = _write_status_report(settings, ref, store)
        assert report_file(settings, ref).exists()
        assert "박미리" in text

    def test_mail_missing_report_does_not_resync(self, tmp_path, monkeypatch):
        from rehabpulse.cli import cmd_mail
        settings = _settings(tmp_path)
        settings["email"]["enabled"] = True
        cmd_init(settings)
        sync_calls = []
        monkeypatch.setattr(
            "rehabpulse.cli.cmd_sync",
            lambda *a, **k: sync_calls.append(1) or 0,
        )
        monkeypatch.setattr("rehabpulse.cli.send_mail", lambda *a, **k: True)
        monkeypatch.setattr("rehabpulse.cli.is_weekday", lambda: True)
        assert cmd_mail(settings, "대신증권", "2608계약건") == 0
        assert sync_calls == []
        ref = project_ref(settings, "대신증권", "2608계약건")
        assert report_file(settings, ref).exists()


class TestAssigneesAndMailing:
    def test_duplicate_mailing_rejected(self, tmp_path):
        store = ExcelStore(tmp_path / "p.xlsx", tmp_path / "b")
        store.load()
        assert store.add_mailing("a@b.c") is True
        assert store.add_mailing("a@b.c") is False


class TestChangeNotify:
    def test_mail_sends_history_to_mailing_list(self, tmp_path, monkeypatch):
        from rehabpulse.cli import cmd_mail
        from rehabpulse.models import ChangeEvent
        from datetime import datetime as dt

        settings = _settings(tmp_path)
        settings["email"]["enabled"] = True
        cmd_init(settings)
        ref = project_ref(settings, "대신증권", "2608계약건")
        store = ExcelStore(ref.workbook, tmp_path / "backup")
        store.load()
        store.append_history(ChangeEvent(
            court="인천지방법원", case_no="2024개회176313",
            party="박미리", event="PLAN_APPROVED", detail="인가",
        ))
        store.save()
        (tmp_path / "reports" / "대신증권" / "2608계약건").mkdir(parents=True)
        day = dt.now().strftime("%Y-%m-%d")
        (tmp_path / "reports" / "대신증권" / "2608계약건" / f"{day}.md").write_text("ok", encoding="utf-8")

        sent = []

        def fake_send(subject, body, config, html=None, recipients=None, retries=0, attachments=None):
            sent.append({"subject": subject, "recipients": recipients})
            return True

        monkeypatch.setattr("rehabpulse.cli.send_mail", fake_send)
        monkeypatch.setattr("rehabpulse.cli.is_weekday", lambda: True)
        assert cmd_mail(settings, "대신증권", "2608계약건") == 0
        change_mails = [s for s in sent if "변제계획인가" in s["subject"] or "PLAN" in s["subject"] or "박미리" in s["subject"]]
        assert change_mails
        assert change_mails[0]["recipients"] == [
            "sonaba79@gmail.com", "kimchangrok.ai@gmail.com",
        ]
        assert all(s["recipients"] != ["owner@example.com"] for s in sent)
    def test_collects_error_and_miss(self, tmp_path):
        store = ExcelStore(tmp_path / "p.xlsx", tmp_path / "b")
        store.load()
        store.add_case(CaseRecord(
            court="인천지방법원", case_no="2024개회1",
            year="2024", case_type="개회", serial="1", party="갑",
            last_result="error", last_error="captcha",
        ))
        store.add_case(CaseRecord(
            court="인천지방법원", case_no="2024개회2",
            year="2024", case_type="개회", serial="2", party="을",
            last_result="not_found",
        ))
        issues = collect_issues(store)
        assert any("error" in i for i in issues)
        assert any("miss" in i for i in issues)


class TestWeekday:
    def test_monday_is_weekday(self):
        from datetime import datetime
        assert is_weekday(datetime(2026, 8, 31)) is True  # Monday
        assert is_weekday(datetime(2026, 9, 5)) is False  # Saturday


class TestParallelSpawn:
    def test_spawn_starts_independent_processes(self, tmp_path, monkeypatch):
        from rehabpulse.cli import _spawn_projects
        settings = _settings(tmp_path)
        cmd_init(settings)
        refs = list_projects(settings)
        calls = []

        class FakeProc:
            def __init__(self, cmd):
                calls.append(cmd)

            def wait(self):
                return 0

        monkeypatch.setattr("rehabpulse.cli.subprocess.Popen", FakeProc)
        assert _spawn_projects("sync", refs) == 0
        assert len(calls) == 2
        for cmd in calls:
            assert "--company" in cmd
            assert "--project" in cmd
            assert cmd[cmd.index("-m") + 1] == "rehabpulse"
