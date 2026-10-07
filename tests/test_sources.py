from datetime import datetime

from oncall.classify import build_prompt, parse_reply
from oncall.intercom import build_transcript, conversation_id
from oncall.jira import parse_issue
from oncall.posthog import q

FIELDS = {"user_id": "customfield_10616", "intercom_url": "customfield_10816", "ai_issue": "customfield_11405"}


def issue(user=None, description=None):
    return {"key": "ONCL-1", "fields": {
        "summary": "Bad edits", "created": "2026-09-14T11:27:59.081+0530",
        "status": {"name": "Canceled"}, "assignee": {"displayName": "Abinash Pegu"},
        "description": description, "customfield_10616": user,
        "customfield_10816": "https://app.intercom.com/a/inbox/g156861r/inbox/shared/mentions/conversation/215475920604379?view=List",
        "customfield_11405": {"value": "No"}}}


def test_ist_to_utc():
    assert parse_issue(issue("abc"), FIELDS)["created_at"] == datetime(2026, 9, 14, 5, 57, 59, 81000)


def test_email_in_user_field():  # ONCL-12386
    t = parse_issue(issue("info@morbyphotography.com"), FIELDS)
    assert t["user_id"] is None and t["email_hint"] == "info@morbyphotography.com"


def test_email_from_description():  # ONCL-13038
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "Email of the user - charrie.stambaugh@icloud.com"}]}]}
    t = parse_issue(issue(None, adf), FIELDS)
    assert t["user_id"] is None and t["email_hint"] == "charrie.stambaugh@icloud.com"


def test_conversation_id_variants():
    assert conversation_id("https://app.intercom.com/a/inbox/g156861r/inbox/admin/10880515/conversation/215475152742966?view=List") == "215475152742966"
    assert conversation_id("https://app.intercom.com/a/inbox/g156861r/inbox/shared/all/conversation/215476014203697") == "215476014203697"
    assert conversation_id(None) is None


def test_transcript_skips_notes():
    conv = {"source": {"body": "<p>My edits look orange</p>"}, "conversation_parts": {"conversation_parts": [
        {"part_type": "comment", "body": "<p>Can you share RAWs?</p>", "author": {"type": "admin"}},
        {"part_type": "note", "body": "escalating", "author": {"type": "admin"}},
        {"part_type": "comment", "body": "Sent", "author": {"type": "user"}}]}}
    assert build_transcript(conv, False, 1000) == "Customer: My edits look orange\nSupport: Can you share RAWs?\nCustomer: Sent"
    assert "Internal note: escalating" in build_transcript(conv, True, 1000)


def test_parse_reply():
    valid = {"profile_quality", "others"}
    assert parse_reply('```json\n{"category":"profile_quality","summary":"x","confidence":"high"}\n```', valid)["category"] == "profile_quality"
    assert parse_reply('{"category":"nonsense","summary":"x","confidence":"high"}', valid)["category"] == "others"


def test_prompt_has_context():
    t = {"summary": "Crop not applied", "description": "4:5 not applied"}
    out = build_prompt(t, None, "Complete", {"profile_type": "instant", "crop_on": True})
    assert "Plan at ticket: Complete" in out and "profile type instant" in out and "use the Jira title" in out


def test_hogql_quoting():
    assert q("o'brien@x.com") == "'o\\'brien@x.com'"


def test_same_user_two_tickets_split_into_separate_batches():
    from oncall.posthog import batched_unique
    a, b = datetime(2026, 9, 1), datetime(2026, 9, 20)
    chunks = list(batched_unique([("u1", a), ("u2", a), ("u1", b)], 25))
    assert chunks == [[("u1", a), ("u2", a)], [("u1", b)]]
    assert sum(len(c) for c in batched_unique([(f"u{i}", a) for i in range(60)], 25)) == 60


def test_profile_id_from_text():
    from oncall.jira import find_profile_id
    pid = "e6aec8a3-5809-4cb4-8c48-e101b70ccd2d"
    assert find_profile_id(f"Profile ID: {pid}") == pid
    assert find_profile_id(f"profile_cloud_id={pid.upper()}") == pid
    # an unlabelled UUID (a project ID, say) is not taken as the profile
    assert find_profile_id(f"Project 5438f7fd ... {pid}") is None


def test_profile_field_wins_over_text():
    fields = {**FIELDS, "profile_id": "customfield_99999"}
    i = issue("abc", {"type": "doc", "content": [{"type": "text", "text": "Profile ID: e6aec8a3-5809-4cb4-8c48-e101b70ccd2d"}]})
    i["fields"]["customfield_99999"] = "081f9f30-9e6c-49ed-8e7f-fba4259ac75d"
    assert parse_issue(i, fields)["ticket_profile_id"] == "081f9f30-9e6c-49ed-8e7f-fba4259ac75d"
    assert parse_issue(i, FIELDS)["ticket_profile_id"] == "e6aec8a3-5809-4cb4-8c48-e101b70ccd2d"


def test_color_rendering_is_a_category():
    from oncall.classify import Classifier
    from oncall.config import load_config
    c = Classifier("k", load_config())
    assert "color_rendering" in c.valid and "Lightroom" in c.system
    assert parse_reply('{"category":"color_rendering","summary":"x","confidence":"high"}', c.valid)["category"] == "color_rendering"
