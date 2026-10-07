"""PostHog lookups: email to user, plan at ticket, current plan, last edit before ticket.

All queries go through the HogQL query API. Users are queried in batches because
results are capped at roughly 100 rows.
"""
from datetime import datetime, timedelta

import requests


def q(value: str) -> str:
    """Quotes a string literal for HogQL."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def ts(dt: datetime) -> str:
    return q(dt.strftime("%Y-%m-%d %H:%M:%S"))


def batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def batched_unique(users: list[tuple[str, datetime]], size: int):
    """Batches (user, time) pairs so no user appears twice in one batch. A user with
    several tickets gets one query per ticket, so their cut-off times don't merge."""
    pending = list(dict.fromkeys(users))
    while pending:
        chunk, seen, rest = [], set(), []
        for u, t in pending:
            if u in seen or len(chunk) >= size:
                rest.append((u, t))
            else:
                chunk.append((u, t))
                seen.add(u)
        yield chunk
        pending = rest


class PostHogClient:
    def __init__(self, host: str, project_id: str, api_key: str, batch_size: int = 25):
        self.url = f"{host.rstrip('/')}/api/projects/{project_id}/query/"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.batch_size = batch_size

    def query(self, hogql: str) -> list[dict]:
        r = self.session.post(self.url, json={"query": {"kind": "HogQLQuery", "query": hogql}}, timeout=120)
        r.raise_for_status()
        data = r.json()
        cols = data["columns"]
        return [dict(zip(cols, row)) for row in data["results"]]

    # --- identity -------------------------------------------------------------
    def user_ids_for_emails(self, emails: list[str]) -> dict[str, str]:
        """Maps email to app user ID, preferring persons that have a user_id set."""
        out = {}
        for chunk in batched(sorted(set(emails)), self.batch_size):
            rows = self.query(
                "SELECT properties.email AS email, properties.user_id AS user_id FROM persons "
                f"WHERE properties.email IN ({', '.join(q(e) for e in chunk)}) AND properties.user_id IS NOT NULL"
            )
            for r in rows:
                out.setdefault(r["email"], r["user_id"])
        return out

    # --- plans ----------------------------------------------------------------
    def plans_at(self, users: list[tuple[str, datetime]]) -> dict[tuple[str, datetime], dict]:
        """Plan on each user's last event at or before the given time (person-on-events).
        Keyed by (user_id, time)."""
        out = {}
        for chunk in batched_unique(users, self.batch_size):
            cutoff = dict(chunk)
            earliest = min(t for _, t in chunk) - timedelta(days=120)
            cond = " OR ".join(f"(distinct_id = {q(u)} AND timestamp <= {ts(t)})" for u, t in chunk)
            rows = self.query(
                "SELECT distinct_id, "
                "argMax(person.properties.Subscription, timestamp) AS subscription, "
                "argMax(person.properties.`Subscription Status`, timestamp) AS status, "
                "argMax(person.properties.`Type of Subscriber`, timestamp) AS cycle, "
                "max(timestamp) AS observed_at "
                f"FROM events WHERE timestamp > {ts(earliest)} AND ({cond}) GROUP BY distinct_id"
            )
            out.update({(r["distinct_id"], cutoff[r["distinct_id"]]): r for r in rows})
        return out

    def current_plans(self, user_ids: list[str]) -> dict[str, dict]:
        """Current person properties, resolved through the distinct-id mapping."""
        out = {}
        for chunk in batched(sorted(set(user_ids)), self.batch_size):
            rows = self.query(
                "SELECT pdi.distinct_id AS distinct_id, p.properties.email AS email, "
                "p.properties.Subscription AS subscription, p.properties.`Subscription Status` AS status, "
                "p.properties.`Type of Subscriber` AS cycle "
                "FROM person_distinct_ids pdi JOIN persons p ON p.id = pdi.person_id "
                f"WHERE pdi.distinct_id IN ({', '.join(q(u) for u in chunk)})"
            )
            out.update({r["distinct_id"]: r for r in rows})
        return out

    # --- profile --------------------------------------------------------------
    def last_edits(self, users: list[tuple[str, datetime]], event: str, lookback_days: int) -> dict[tuple[str, datetime], dict]:
        """Profile and AI settings from each user's last edit at or before the given time.
        Keyed by (user_id, time)."""
        out = {}
        for chunk in batched_unique(users, self.batch_size):
            cutoff = dict(chunk)
            earliest = min(t for _, t in chunk) - timedelta(days=lookback_days)
            cond = " OR ".join(f"(distinct_id = {q(u)} AND timestamp <= {ts(t)})" for u, t in chunk)
            rows = self.query(
                "SELECT distinct_id, "
                "argMax(properties.profile_type, timestamp) AS profile_type, "
                "argMax(coalesce(nullIf(toString(properties.`Profile ID`), ''), "
                "JSONExtractString(toString(properties.profile), 'cloud_id')), timestamp) AS profile_id, "
                "argMax(properties.`Profile Name`, timestamp) AS profile_name, "
                "argMax(properties.crop_toggle, timestamp) AS crop_on, "
                "argMax(properties.straighten_toggle, timestamp) AS straighten_on, "
                "argMax(properties.masking_toggle, timestamp) AS masking_on, "
                "max(timestamp) AS edited_at "
                f"FROM events WHERE event = {q(event)} AND timestamp > {ts(earliest)} AND ({cond}) "
                "GROUP BY distinct_id"
            )
            out.update({(r["distinct_id"], cutoff[r["distinct_id"]]): r for r in rows})
        return out

    def profile_details(self, profile_ids: list[str], lookback_days: int) -> dict[str, dict]:
        """Name and type for each profile ID, from the latest edit or profile-selection event that used it."""
        out = {}
        for chunk in batched(sorted(set(profile_ids)), self.batch_size):
            ids = ", ".join(q(i) for i in chunk)
            since = f"now() - INTERVAL {int(lookback_days)} DAY"
            rows = self.query(
                "SELECT pid AS profile_id, argMax(ptype, ts) AS profile_type, argMax(pname, ts) AS profile_name "
                "FROM ("
                "SELECT coalesce(nullIf(toString(properties.`Profile ID`), ''), "
                "JSONExtractString(toString(properties.profile), 'cloud_id')) AS pid, "
                "properties.profile_type AS ptype, properties.`Profile Name` AS pname, timestamp AS ts "
                f"FROM events WHERE event = 'Edit Completed' AND timestamp > {since} "
                "UNION ALL "
                "SELECT toString(properties.profile_cloud_id) AS pid, properties.profile_type AS ptype, "
                "properties.`Profile Name` AS pname, timestamp AS ts "
                f"FROM events WHERE event = 'chooseProfile' AND timestamp > {since}"
                f") WHERE pid IN ({ids}) GROUP BY pid"
            )
            out.update({r["profile_id"]: r for r in rows})
        return out

    def recent_profiles(self, users: list[tuple[str, datetime]], event: str, lookback_days: int) -> dict[tuple[str, datetime], list[dict]]:
        """Every profile each user edited with in the window before the given time, newest first."""
        out = {}
        for chunk in batched_unique(users, self.batch_size):
            cutoff = dict(chunk)
            earliest = min(t for _, t in chunk) - timedelta(days=lookback_days)
            cond = " OR ".join(f"(distinct_id = {q(u)} AND timestamp <= {ts(t)} "
                               f"AND timestamp > {ts(t - timedelta(days=lookback_days))})" for u, t in chunk)
            rows = self.query(
                "SELECT distinct_id, coalesce(nullIf(toString(properties.`Profile ID`), ''), "
                "JSONExtractString(toString(properties.profile), 'cloud_id')) AS profile_id, "
                "argMax(properties.`Profile Name`, timestamp) AS profile_name, "
                "argMax(properties.profile_type, timestamp) AS profile_type, "
                "max(timestamp) AS last_used "
                f"FROM events WHERE event = {q(event)} AND timestamp > {ts(earliest)} AND ({cond}) "
                "GROUP BY distinct_id, profile_id HAVING profile_id != '' "
                "ORDER BY distinct_id, last_used DESC LIMIT 5000"
            )
            for r in rows:
                out.setdefault((r["distinct_id"], cutoff[r["distinct_id"]]), []).append(r)
        return out
