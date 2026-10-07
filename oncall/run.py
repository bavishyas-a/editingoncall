"""Daily job: Jira → Intercom → PostHog → classifier → database (→ optional HTML page).

    python -m oncall.run                     # tickets from the last `lookback_days`
    python -m oncall.run --since 2026-09-01  # backfill
    python -m oncall.run --html out/index.html
    python -m oncall.run --dry-run           # print rows, write nothing
"""
import argparse
import logging
from datetime import datetime, timedelta, timezone

from .classify import Classifier
from .config import env, load_config
from .intercom import IntercomClient
from .jira import JiraClient
from .plans import PlanBook, classify_change, plan_mismatch
from .profiles import match_named_profile
from .posthog import PostHogClient
from .store import Store

log = logging.getLogger("oncall")


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def run(since: datetime, html_path: str | None = None, dry_run: bool = False, reclassify: bool = False):
    cfg = load_config()
    book = PlanBook(cfg["plans"])
    jira = JiraClient(env("JIRA_BASE_URL"), env("JIRA_EMAIL"), env("JIRA_API_TOKEN"))
    intercom = IntercomClient(env("INTERCOM_TOKEN"))
    ph = PostHogClient(env("POSTHOG_HOST"), env("POSTHOG_PROJECT_ID"), env("POSTHOG_API_KEY"),
                       cfg["posthog"]["batch_size"])
    classifier = Classifier(env("ANTHROPIC_API_KEY"), cfg)
    store = Store(env("DATABASE_URL"))

    tickets = jira.fetch_tickets(cfg, since)
    log.info("Fetched %d tickets since %s", len(tickets), since.date())
    prior = store.existing([t["ticket_key"] for t in tickets])

    # 1. Intercom, only for tickets not yet classified.
    chats = {}
    for t in tickets:
        old = prior.get(t["ticket_key"], {})
        if old.get("category") and not reclassify:
            continue
        try:
            chats[t["ticket_key"]] = intercom.fetch(t["intercom_url"], cfg)
        except Exception as e:  # keep going; record the gap
            log.warning("Intercom failed for %s: %s", t["ticket_key"], e)
            chats[t["ticket_key"]] = {"transcript": None, "email": None, "external_id": None, "error": str(e)}

    # 2. Resolve user IDs: Jira field → frozen value → Intercom external_id → email lookup.
    for t in tickets:
        old, chat = prior.get(t["ticket_key"], {}), chats.get(t["ticket_key"], {})
        t["user_id"] = t["user_id"] or old.get("user_id") or chat.get("external_id")
        t["email"] = old.get("email") or chat.get("email") or t["email_hint"]
    need_email = [t["email"] for t in tickets if not t["user_id"] and t["email"]]
    by_email = ph.user_ids_for_emails(need_email) if need_email else {}
    for t in tickets:
        if not t["user_id"] and t["email"]:
            t["user_id"] = by_email.get(t["email"])

    # 3. PostHog: plan at ticket and last edit (only when not already stored), current plan (always).
    with_user = [t for t in tickets if t["user_id"]]
    fresh = [(t["user_id"], t["created_at"]) for t in with_user
             if not prior.get(t["ticket_key"], {}).get("plan_at_ticket")]
    at = ph.plans_at(fresh) if fresh else {}
    edits = ph.last_edits(fresh, cfg["posthog"]["edit_event"], cfg["posthog"]["edit_lookback_days"]) if fresh else {}
    now = ph.current_plans([t["user_id"] for t in with_user]) if with_user else {}

    # 4. Profile, in order: an ID on the ticket; a profile the ticket names, among those the user edited
    #    with in the lookback window; the profile from the user's last edit before the ticket.
    #    Name and type are then looked up from the ID, so they're consistent whichever way it was found.
    need_recent = [(t["user_id"], t["created_at"]) for t in with_user
                   if not t.get("ticket_profile_id") and not prior.get(t["ticket_key"], {}).get("profile_id")]
    recent = (ph.recent_profiles(need_recent, cfg["posthog"]["edit_event"], cfg["posthog"]["edit_lookback_days"])
              if need_recent else {})

    def profile_for(t):
        old = prior.get(t["ticket_key"], {})
        if t.get("ticket_profile_id"):
            return t["ticket_profile_id"], "ticket"
        if old.get("profile_id"):
            return old["profile_id"], old.get("profile_source")
        text = " ".join([t["summary"], t["description"], (chats.get(t["ticket_key"]) or {}).get("transcript") or ""])
        named = match_named_profile(text, recent.get((t["user_id"], t["created_at"]), []))
        if named:
            return named["profile_id"], "named"
        e = edits.get((t["user_id"], t["created_at"])) or {}
        return (e.get("profile_id"), "last_edit") if e.get("profile_id") else (None, None)

    chosen = {t["ticket_key"]: profile_for(t) for t in tickets}
    to_lookup = []
    for t in tickets:
        pid, _ = chosen[t["ticket_key"]]
        old = prior.get(t["ticket_key"], {})
        if pid and not (old.get("profile_id") == pid and old.get("profile_type")):
            to_lookup.append(pid)
    profiles = ph.profile_details(to_lookup, cfg["posthog"]["profile_lookback_days"]) if to_lookup else {}

    rows = []
    for t in tickets:
        key, uid, old = t["ticket_key"], t["user_id"], prior.get(t["ticket_key"], {})
        a = at.get((uid, t["created_at"])) or ({"subscription": old.get("plan_at_ticket"), "status": old.get("status_at_ticket"),
                             "cycle": old.get("cycle_at_ticket"), "observed_at": old.get("plan_observed_at")}
                            if old.get("plan_at_ticket") else None)
        n = now.get(uid)
        e = edits.get((uid, t["created_at"])) or {}
        kind, note = classify_change(book, a, n)
        prof = profiles.get(chosen[key][0]) or {}
        fallback = e if chosen[key][1] == "last_edit" else {}  # never borrow another profile's name

        gap = None
        if not uid:
            gap = "No user ID on ticket or in Intercom"
        elif not a and not n:
            gap = "User ID not found in PostHog"
        elif not a:
            gap = "No PostHog events before the ticket"

        row = {
            **{k: t.get(k) for k in ("ticket_key", "created_at", "summary", "jira_status", "assignee",
                                      "intercom_url", "ai_issue_flag", "user_id")},
            "email": t["email"] or (n or {}).get("email"),
            "plan_at_ticket": (a or {}).get("subscription"),
            "status_at_ticket": (a or {}).get("status"),
            "cycle_at_ticket": (a or {}).get("cycle"),
            "plan_observed_at": parse_ts((a or {}).get("observed_at")),
            "plan_now": (n or {}).get("subscription"),
            "status_now": (n or {}).get("status"),
            "cycle_now": (n or {}).get("cycle"),
            "change_kind": kind,
            "change_note": note,
            "profile_id": chosen[key][0],
            "profile_source": chosen[key][1],
            "profile_type": prof.get("profile_type") or fallback.get("profile_type"),
            "profile_name": prof.get("profile_name") or fallback.get("profile_name"),
            "last_edit_at": parse_ts(e.get("edited_at")),
            "data_gap": gap,
        }
        # A profile ID added to the ticket after the first run replaces the last-edit fallback.
        if chosen[key][1] == "ticket" and old.get("profile_source") != "ticket":
            row["_overwrite"] = ("profile_id", "profile_source", "profile_type", "profile_name")

        # 5. Classification for new tickets.
        if key in chats:
            chat = chats[key]
            try:
                c = classifier.classify(t, chat.get("transcript"), row["plan_at_ticket"], e)
                row.update(category=c["category"], issue_summary=c["summary"], classify_confidence=c["confidence"])
            except Exception as err:
                log.warning("Classification failed for %s: %s", key, err)
            if chat.get("error"):
                row["data_gap"] = (row["data_gap"] + "; " if row["data_gap"] else "") + "Intercom unavailable"
        row["plan_mismatch"] = plan_mismatch(
            book, row["plan_at_ticket"] or old.get("plan_at_ticket"),
            row.get("category") or old.get("category"),
            row["profile_type"] or old.get("profile_type"))
        rows.append(row)

    if dry_run:
        for r in rows:
            print(r)
        return rows

    store.upsert(rows, overwrite=("category", "issue_summary", "classify_confidence") if reclassify else ())
    store.snapshot(rows)
    log.info("Wrote %d tickets", len(rows))

    if html_path:
        from .export_html import write_page
        write_page(store.all_tickets(), html_path)
        log.info("Wrote dashboard page to %s", html_path)
    return rows


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", help="YYYY-MM-DD; defaults to today minus jira.lookback_days")
    p.add_argument("--html", help="also write the dashboard page to this path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reclassify", action="store_true", help="re-run classification for every ticket")
    args = p.parse_args()
    since = (datetime.strptime(args.since, "%Y-%m-%d") if args.since
             else datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=cfg["jira"]["lookback_days"]))
    run(since, args.html, args.dry_run, args.reclassify)


if __name__ == "__main__":
    main()
