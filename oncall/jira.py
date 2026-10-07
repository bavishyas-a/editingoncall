"""Fetches on-call tickets from Jira Cloud (REST v3)."""
import re
from datetime import datetime, timezone

import requests

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
PROFILE_ID_RE = re.compile(r"profile[\s_-]*(?:cloud[\s_-]*)?id\W{0,5}(" + UUID + ")", re.I)


def find_profile_id(text: str) -> str | None:
    """A profile ID written in the ticket text, e.g. "Profile ID: 1f2e…". Only UUIDs that are
    labelled as a profile ID count, so user IDs and project IDs aren't picked up by mistake."""
    m = PROFILE_ID_RE.search(text or "")
    return m.group(1).lower() if m else None


def adf_to_text(node) -> str:
    """Flattens an Atlassian Document Format description to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(t for t in (adf_to_text(n) for n in node) if t)
    text = node.get("text", "")
    children = adf_to_text(node.get("content"))
    return " ".join(t for t in (text, children) if t)


def parse_issue(issue: dict, fields_cfg: dict) -> dict:
    f = issue["fields"]
    description = adf_to_text(f.get("description"))
    raw_user = (f.get(fields_cfg["user_id"]) or "").strip()
    user_id, email_hint = raw_user or None, None
    if "@" in raw_user:
        user_id, email_hint = None, raw_user
    if not raw_user:
        found = EMAIL_RE.search(description)
        email_hint = found.group(0) if found else None
    ai_issue = f.get(fields_cfg["ai_issue"])
    profile_field = fields_cfg.get("profile_id")
    profile_id = (f.get(profile_field) or "").strip() if profile_field else ""
    profile_id = profile_id or find_profile_id(description)
    created = datetime.fromisoformat(f["created"]).astimezone(timezone.utc)
    return {
        "ticket_key": issue["key"],
        "created_at": created.replace(tzinfo=None),  # naive UTC
        "summary": f.get("summary") or "",
        "description": description,
        "jira_status": (f.get("status") or {}).get("name"),
        "assignee": (f.get("assignee") or {}).get("displayName"),
        "user_id": user_id,
        "email_hint": email_hint,
        "intercom_url": f.get(fields_cfg["intercom_url"]),
        "ai_issue_flag": ai_issue.get("value") if isinstance(ai_issue, dict) else ai_issue,
        "ticket_profile_id": profile_id or None,
    }


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers["Accept"] = "application/json"

    def search(self, jql: str, fields: list[str]) -> list[dict]:
        issues, token = [], None
        while True:
            body = {"jql": jql, "fields": fields, "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            r = self.session.post(f"{self.base_url}/rest/api/3/search/jql", json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            issues.extend(data.get("issues", []))
            token = data.get("nextPageToken")
            if data.get("isLast", True) or not token:
                return issues

    def fetch_tickets(self, cfg: dict, since: datetime) -> list[dict]:
        jcfg = cfg["jira"]
        jql = f'{jcfg["jql"]} AND created >= "{since:%Y-%m-%d}" ORDER BY created ASC'
        fields = ["summary", "description", "status", "assignee", "created", *(v for v in jcfg["fields"].values() if v)]
        tickets = [parse_issue(i, jcfg["fields"]) for i in self.search(jql, fields)]
        excluded = set(jcfg.get("exclude_user_ids", []))
        return [t for t in tickets if t["user_id"] not in excluded]
