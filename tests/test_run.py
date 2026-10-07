"""End-to-end run with fake API clients, built from ONCL-12216 (lost editing),
ONCL-12386 (email only) and ONCL-12750 (no user ID)."""
from datetime import datetime

import oncall.run as run_mod


class FakeJira:
    def __init__(self, *a): pass
    def fetch_tickets(self, cfg, since):
        base = {"description": "", "jira_status": "On user", "assignee": "Pratyush Sharma", "ai_issue_flag": "No",
                "intercom_url": "https://app.intercom.com/a/inbox/x/inbox/shared/all/conversation/111"}
        return [
            {**base, "ticket_key": "ONCL-12216", "created_at": datetime(2026, 9, 9, 7, 36), "summary": "Unhappy with edits",
             "user_id": "Ho9C", "email_hint": None},
            {**base, "ticket_key": "ONCL-12386", "created_at": datetime(2026, 9, 14, 5, 57), "summary": "Moved to ImagenAI",
             "user_id": None, "email_hint": "info@morbyphotography.com",
             "ticket_profile_id": "e6aec8a3-5809-4cb4-8c48-e101b70ccd2d"},
            {**base, "ticket_key": "ONCL-12750", "created_at": datetime(2026, 9, 23, 10, 21), "summary": "Velvet tint",
             "user_id": None, "email_hint": None, "intercom_url": None},
        ]


class FakeIntercom:
    def __init__(self, *a): pass
    def fetch(self, url, cfg):
        return {"transcript": "Customer: edits are too warm" if url else None, "email": None, "external_id": None}


class FakePostHog:
    calls = []
    def __init__(self, *a): pass
    def user_ids_for_emails(self, emails): return {"info@morbyphotography.com": "morby"}
    def plans_at(self, users):
        FakePostHog.calls.append(("plans_at", [u for u, _ in users]))
        return {(u, ts): {"subscription": "Complete", "status": "Active", "cycle": "Monthly", "observed_at": "2026-08-15T18:18:42Z"}
                for u, ts in users if u == "Ho9C"}
    def current_plans(self, ids):
        return {"Ho9C": {"subscription": "Select", "status": "Active", "cycle": "Monthly", "email": "kris@example.com"},
                "morby": {"subscription": "Max", "status": "Active", "cycle": "Yearly", "email": "info@morbyphotography.com"}}
    def last_edits(self, users, event, days):
        return {(u, ts): {"profile_type": "custom", "profile_id": "p1", "profile_name": "My Profile", "edited_at": "2026-09-08T10:00:00Z"}
                for u, ts in users if u == "Ho9C"}


    def profile_details(self, ids, days):
        FakePostHog.calls.append(("profile_details", list(ids)))
        known = {"p1": {"profile_type": "custom", "profile_name": "My Profile"},
                 "e6aec8a3-5809-4cb4-8c48-e101b70ccd2d": {"profile_type": "custom", "profile_name": "My Personal Profile #2"}}
        return {i: {"profile_id": i, **known[i]} for i in ids if i in known}


    def recent_profiles(self, users, event, days):
        return {}


class FakeClassifier:
    def __init__(self, *a): pass
    def classify(self, ticket, transcript, plan, edit):
        return {"category": "profile_quality", "summary": "Edits too warm.", "confidence": "high"}


def test_end_to_end(tmp_path, monkeypatch):
    for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "INTERCOM_TOKEN", "POSTHOG_HOST",
              "POSTHOG_PROJECT_ID", "POSTHOG_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setattr(run_mod, "JiraClient", FakeJira)
    monkeypatch.setattr(run_mod, "IntercomClient", FakeIntercom)
    monkeypatch.setattr(run_mod, "PostHogClient", FakePostHog)
    monkeypatch.setattr(run_mod, "Classifier", FakeClassifier)

    html = tmp_path / "index.html"
    rows = {r["ticket_key"]: r for r in run_mod.run(datetime(2026, 9, 1), str(html))}

    assert rows["ONCL-12216"]["change_kind"] == "lost_edit"
    assert rows["ONCL-12216"]["profile_type"] == "custom"
    assert rows["ONCL-12216"]["email"] == "kris@example.com"
    assert rows["ONCL-12216"]["profile_source"] == "last_edit"
    assert rows["ONCL-12386"]["profile_source"] == "ticket"
    assert rows["ONCL-12386"]["profile_name"] == "My Personal Profile #2"
    assert rows["ONCL-12386"]["user_id"] == "morby"
    assert rows["ONCL-12386"]["data_gap"] == "No PostHog events before the ticket"
    assert rows["ONCL-12750"]["data_gap"] == "No user ID on ticket or in Intercom"
    assert html.exists()

    # Second run: plan at ticket is already stored, so PostHog isn't asked again for Ho9C.
    FakePostHog.calls.clear()
    run_mod.run(datetime(2026, 9, 1))
    assert all("Ho9C" not in users for name, users in FakePostHog.calls if name == "plans_at")
    assert not any(name == "profile_details" for name, _ in FakePostHog.calls)  # names already stored


def test_profile_added_to_ticket_later_replaces_fallback(tmp_path, monkeypatch):
    for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "INTERCOM_TOKEN", "POSTHOG_HOST",
              "POSTHOG_PROJECT_ID", "POSTHOG_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setattr(run_mod, "IntercomClient", FakeIntercom)
    monkeypatch.setattr(run_mod, "PostHogClient", FakePostHog)
    monkeypatch.setattr(run_mod, "Classifier", FakeClassifier)

    class Jira1(FakeJira):
        def fetch_tickets(self, cfg, since):
            return [t for t in super().fetch_tickets(cfg, since) if t["ticket_key"] == "ONCL-12216"]

    class Jira2(Jira1):
        def fetch_tickets(self, cfg, since):
            return [{**t, "ticket_profile_id": "e6aec8a3-5809-4cb4-8c48-e101b70ccd2d"} for t in super().fetch_tickets(cfg, since)]

    monkeypatch.setattr(run_mod, "JiraClient", Jira1)
    run_mod.run(datetime(2026, 9, 1))
    monkeypatch.setattr(run_mod, "JiraClient", Jira2)
    run_mod.run(datetime(2026, 9, 1))
    from oncall.store import Store
    row = Store(f"sqlite:///{tmp_path/'t.db'}").all_tickets()[0]
    assert (row["profile_source"], row["profile_name"]) == ("ticket", "My Personal Profile #2")
