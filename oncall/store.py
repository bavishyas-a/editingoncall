"""Writes results to any SQLAlchemy database.

oncall_tickets: one row per ticket. Plan at ticket, profile and classification are
filled once; current plan and change are refreshed on every run.
plan_snapshots: one row per ticket per day, so plan history survives even if PostHog
later overwrites it.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (Column, Date, DateTime, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, delete, select)

meta = MetaData()

tickets = Table(
    "oncall_tickets", meta,
    Column("ticket_key", String(32), primary_key=True),
    Column("created_at", DateTime, nullable=False),
    Column("summary", Text),
    Column("jira_status", String(64)),
    Column("assignee", String(128)),
    Column("intercom_url", Text),
    Column("ai_issue_flag", String(16)),
    Column("user_id", String(128)),
    Column("email", String(256)),
    Column("plan_at_ticket", String(128)),
    Column("status_at_ticket", String(32)),
    Column("cycle_at_ticket", String(32)),
    Column("plan_observed_at", DateTime),
    Column("plan_now", String(128)),
    Column("status_now", String(32)),
    Column("cycle_now", String(32)),
    Column("change_kind", String(32)),
    Column("change_note", Text),
    Column("profile_type", String(32)),
    Column("profile_id", String(128)),
    Column("profile_name", String(256)),
    Column("profile_source", String(16)),  # "ticket", "named" or "last_edit"
    Column("last_edit_at", DateTime),
    Column("category", String(32)),
    Column("issue_summary", Text),
    Column("classify_confidence", String(16)),
    Column("plan_mismatch", Text),
    Column("data_gap", Text),
    Column("updated_at", DateTime, nullable=False),
)

snapshots = Table(
    "plan_snapshots", meta,
    Column("ticket_key", String(32), nullable=False),
    Column("snapshot_date", Date, nullable=False),
    Column("user_id", String(128)),
    Column("plan", String(128)),
    Column("status", String(32)),
    Column("cycle", String(32)),
    UniqueConstraint("ticket_key", "snapshot_date"),
)

# Fields that are set once and never overwritten by later runs.
FROZEN = ("user_id", "email", "plan_at_ticket", "status_at_ticket", "cycle_at_ticket", "plan_observed_at",
          "profile_type", "profile_id", "profile_name", "profile_source", "last_edit_at",
          "category", "issue_summary", "classify_confidence")


class Store:
    def __init__(self, url: str):
        self.engine = create_engine(url, future=True)
        meta.create_all(self.engine)

    def existing(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        with self.engine.connect() as c:
            rows = c.execute(select(tickets).where(tickets.c.ticket_key.in_(keys))).mappings()
            return {r["ticket_key"]: dict(r) for r in rows}

    def upsert(self, rows: list[dict], overwrite: tuple[str, ...] = ()):
        """Replaces each ticket row, keeping FROZEN fields unless listed in `overwrite`."""
        prior = self.existing([r["ticket_key"] for r in rows])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.engine.begin() as c:
            for row in rows:
                old = prior.get(row["ticket_key"], {})
                keep_new = set(overwrite) | set(row.get("_overwrite", ()))
                merged = {col.name: row.get(col.name) for col in tickets.columns}
                for f in FROZEN:
                    if f in keep_new and merged.get(f) is not None:
                        continue
                    if old.get(f) is not None:
                        merged[f] = old[f]
                merged["updated_at"] = now
                c.execute(delete(tickets).where(tickets.c.ticket_key == row["ticket_key"]))
                c.execute(tickets.insert().values(**merged))

    def snapshot(self, rows: list[dict], day: date | None = None):
        day = day or date.today()
        with self.engine.begin() as c:
            for row in rows:
                if not row.get("user_id"):
                    continue
                c.execute(delete(snapshots).where(
                    (snapshots.c.ticket_key == row["ticket_key"]) & (snapshots.c.snapshot_date == day)))
                c.execute(snapshots.insert().values(
                    ticket_key=row["ticket_key"], snapshot_date=day, user_id=row["user_id"],
                    plan=row.get("plan_now"), status=row.get("status_now"), cycle=row.get("cycle_now")))

    def all_tickets(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(tickets).order_by(tickets.c.created_at)).mappings()]
