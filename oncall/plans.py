"""Normalises plan names and describes what changed between two plans."""


class PlanBook:
    def __init__(self, plans_cfg: list[dict]):
        self.by_alias = {}
        for p in plans_cfg:
            for alias in p["aliases"]:
                self.by_alias[alias.strip().lower()] = p

    def lookup(self, raw: str | None) -> dict | None:
        return self.by_alias.get((raw or "").strip().lower())

    def canonical(self, raw: str | None) -> str | None:
        p = self.lookup(raw)
        return p["name"] if p else (raw or None)


PAID = {"active", "trialing", "past_due"}
FEATURES = ("cull", "edit", "retouch")


def classify_change(book: PlanBook, before: dict | None, after: dict | None) -> tuple[str, str]:
    """Returns (kind, note). Kinds: same, lost_edit, downgrade, upgrade, changed,
    canceled, payment_issue, trial, unknown_plan, no_data."""
    if not before or not after:
        return "no_data", "Plan missing at ticket or now"
    b_status = (before.get("status") or "").lower()
    a_status = (after.get("status") or "").lower()
    b_name, a_name = before.get("subscription"), after.get("subscription")

    if b_status in PAID and a_status not in PAID:
        return "canceled", f"{book.canonical(b_name)} → canceled"
    if b_status not in PAID and a_status not in PAID:
        return "canceled", "Not on a paid plan at ticket time"
    if a_status == "past_due" and b_status != "past_due":
        return "payment_issue", f"Payment past due ({book.canonical(a_name)})"

    bp, ap = book.lookup(b_name), book.lookup(a_name)
    if not bp or not ap:
        missing = b_name if not bp else a_name
        return "unknown_plan", f"Plan name not in mapping: {missing or '(blank)'}"

    lost = [f for f in FEATURES if bp[f] and not ap[f]]
    gained = [f for f in FEATURES if ap[f] and not bp[f]]
    fewer_profiles = (bp["custom_profiles"] is not None and ap["custom_profiles"] is not None
                      and ap["custom_profiles"] < bp["custom_profiles"])

    if "edit" in lost:
        return "lost_edit", f"Lost editing: {bp['name']} → {ap['name']}"
    if lost or (fewer_profiles and not gained):
        return "downgrade", f"{bp['name']} → {ap['name']}"
    if gained and not lost:
        return "upgrade", f"{bp['name']} → {ap['name']}"
    if bp["name"] != ap["name"]:
        return "changed", f"{bp['name']} → {ap['name']} (same features)"
    if b_status == "trialing" and a_status == "trialing":
        return "trial", "Still on trial"
    if b_status == "trialing" and a_status == "active":
        return "same", "Trial converted to paid"
    return "same", ""


def plan_mismatch(book: PlanBook, raw_plan: str | None, category: str | None, profile_type: str | None) -> str | None:
    """Flags tickets that can't be what they claim given the user's plan."""
    p = book.lookup(raw_plan)
    if not p:
        return None
    if category in ("cropping", "straightening") and p.get("crop_straighten") is False:
        return f"{p['name']} doesn't include {category}"
    if profile_type == "custom" and p.get("custom_profiles") == 0:
        return f"{p['name']} doesn't include custom profiles"
    if not p["edit"] and category:
        return f"{p['name']} doesn't include editing"
    return None
