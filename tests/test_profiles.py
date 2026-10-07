"""Real September cases: the ticket names a profile that wasn't the user's last edit."""
from oncall.profiles import match_named_profile

YUGO = [{"profile_id": "b17c", "profile_name": "Jeff", "last_used": "2026-09-18"},
        {"profile_id": "546d", "profile_name": "YUGO's Life", "last_used": "2026-09-02"},
        {"profile_id": "88be", "profile_name": "Lemon Zest", "last_used": "2026-08-28"}]
LAX = [{"profile_id": "e53c", "profile_name": "Underground Studio - Retrain{WB-v4}", "last_used": "2026-09-14T19"},
       {"profile_id": "0e3f", "profile_name": "Lux by Victor Lax", "last_used": "2026-09-14T18"},
       {"profile_id": "f71c", "profile_name": "Underground Studio", "last_used": "2026-09-08"}]
W2024 = [{"profile_id": "056e", "profile_name": "BYN", "last_used": "2026-09-29T22"},
         {"profile_id": "57de", "profile_name": "W_2024", "last_used": "2026-09-29T17"}]


def test_full_name():  # ONCL-12587
    assert match_named_profile("White balance in user's AI profile YUGO's Life is inaccurate", YUGO)["profile_id"] == "546d"


def test_distinctive_word():  # ONCL-12414
    assert match_named_profile("consistency issue with LAX profile", LAX)["profile_id"] == "0e3f"


def test_underscore_name():  # ONCL-12975
    assert match_named_profile("Wants to revert the last updates made to the profile 'W_2024'", W2024)["profile_id"] == "57de"


def test_generic_text_matches_nothing():
    assert match_named_profile("Bad edits, white balance inconsistent across the wedding", YUGO + LAX) is None
    assert match_named_profile("My personal profile looks wrong",
                               [{"profile_id": "x", "profile_name": "My Personal Profile #1"}]) is None


def test_full_name_beats_single_word():
    cands = [{"profile_id": "a", "profile_name": "Underground Studio", "last_used": "2026-09-08"},
             {"profile_id": "b", "profile_name": "Underground Studio - Retrain", "last_used": "2026-09-14"}]
    assert match_named_profile("issue with Underground Studio - Retrain", cands)["profile_id"] == "b"
    assert match_named_profile("issue with underground profile", cands)["profile_id"] == "b"  # tie → newest


def test_plan_words_dont_match_profiles():  # ONCL-12957
    cands = [{"profile_id": "f", "profile_name": "The Founder Profile", "last_used": "2026-09-28"}]
    assert match_named_profile("Founder user getting inaccurate color and blown out exposure with AI profile", cands) is None
