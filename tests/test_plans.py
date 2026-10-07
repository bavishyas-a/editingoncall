"""Cases taken from real September tickets."""
import pytest

from oncall.config import load_config
from oncall.plans import PlanBook, classify_change, plan_mismatch


@pytest.fixture(scope="module")
def book():
    return PlanBook(load_config()["plans"])


def p(sub, status="Active", cycle="Yearly"):
    return {"subscription": sub, "status": status, "cycle": cycle}


def test_alias_order_is_same_plan(book):  # ONCL-12013 style: name order differs between snapshots
    assert classify_change(book, p("Edit + Select"), p("Select + Edit"))[0] == "same"


def test_legacy_renamed(book):  # "Essentials" became "Aftershoot Essentials" in June
    assert classify_change(book, p("Essentials"), p("Aftershoot Essentials"))[0] == "same"


def test_lost_editing(book):  # ONCL-12216, ONCL-12635
    assert classify_change(book, p("Complete", cycle="Monthly"), p("Select", cycle="Monthly"))[0] == "lost_edit"
    assert classify_change(book, p("Edit + Select"), p("Select"))[0] == "lost_edit"


def test_upgrade(book):  # ONCL-12797
    assert classify_change(book, p("Edit"), p("Edit + Select"))[0] == "upgrade"


def test_past_due(book):  # ONCL-12132
    kind, _ = classify_change(book, p("Aftershoot Unlimited Founders Plan"), p("Complete", "Past_due", "Monthly"))
    assert kind == "payment_issue"


def test_already_canceled(book):  # ONCL-12141
    assert classify_change(book, p("Complete", "Canceled", "Free"), p("Complete", "Canceled", "Free"))[0] == "canceled"


def test_cancel_after_ticket(book):
    assert classify_change(book, p("Pro"), p("Pro", "Canceled", "Free"))[0] == "canceled"


def test_blank_plan_name(book):  # ONCL-12975
    assert classify_change(book, p("Edit + Select"), p(""))[0] == "unknown_plan"


def test_legacy_pro_to_essentials_is_downgrade(book):  # user from the first lookup: Pro → Essentials
    assert classify_change(book, p("Pro"), p("Aftershoot Essentials"))[0] == "downgrade"


def test_trial(book):
    assert classify_change(book, p("Complete", "Trialing"), p("Complete", "Trialing"))[0] == "trial"
    assert classify_change(book, p("Complete", "Trialing"), p("Complete"))[1] == "Trial converted to paid"


def test_missing(book):
    assert classify_change(book, None, p("Max"))[0] == "no_data"


def test_mismatch(book):
    assert plan_mismatch(book, "Aftershoot Essentials", "cropping", None) == "Essentials doesn't include cropping"
    assert plan_mismatch(book, "Aftershoot Essentials", "profile_quality", "custom") == "Essentials doesn't include custom profiles"
    assert plan_mismatch(book, "Complete", "cropping", "custom") is None
