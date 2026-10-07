from datetime import date, datetime

from oncall.export_html import write_page
from oncall.store import Store


def row(**kw):
    base = {"ticket_key": "ONCL-1", "created_at": datetime(2026, 9, 1), "user_id": "u1",
            "plan_at_ticket": "Complete", "status_at_ticket": "Active", "plan_now": "Complete",
            "status_now": "Active", "change_kind": "same", "category": "cropping", "issue_summary": "first"}
    return {**base, **kw}


def test_frozen_fields_survive_and_current_plan_updates(tmp_path):
    s = Store(f"sqlite:///{tmp_path/'t.db'}")
    s.upsert([row()])
    s.upsert([row(plan_at_ticket=None, category=None, issue_summary=None, plan_now="Select", change_kind="lost_edit")])
    r = s.all_tickets()[0]
    assert (r["plan_at_ticket"], r["category"], r["plan_now"], r["change_kind"]) == ("Complete", "cropping", "Select", "lost_edit")


def test_reclassify_overwrites(tmp_path):
    s = Store(f"sqlite:///{tmp_path/'t.db'}")
    s.upsert([row()])
    s.upsert([row(category="others", issue_summary="second")], overwrite=("category", "issue_summary"))
    assert s.all_tickets()[0]["category"] == "others"


def test_snapshots_one_per_day(tmp_path):
    s = Store(f"sqlite:///{tmp_path/'t.db'}")
    s.snapshot([row()], date(2026, 10, 6))
    s.snapshot([row(plan_now="Select")], date(2026, 10, 6))
    s.snapshot([row(plan_now="Select")], date(2026, 10, 7))
    with s.engine.connect() as c:
        assert c.exec_driver_sql("select count(*) from plan_snapshots").scalar() == 2


def test_page_renders(tmp_path):
    s = Store(f"sqlite:///{tmp_path/'t.db'}")
    s.upsert([row(summary="</script><b>x</b>")])
    out = tmp_path / "index.html"
    write_page(s.all_tickets(), str(out))
    html = out.read_text()
    assert "ONCL-1" in html and "</script><b>" not in html
