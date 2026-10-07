"""Picks the profile a ticket is about, from the profiles the user edited with recently."""
import re

# Words too common in profile names and ticket text to identify a profile on their own.
COMMON = {
    "a", "an", "the", "by", "of", "and", "my", "me", "new", "old", "test", "copy", "v1", "v2", "v3", "v4",
    "profile", "profiles", "personal", "style", "instant", "custom", "marketplace", "preset", "ai",
    "edit", "edits", "editing", "color", "colour", "colors", "raw", "jpeg", "jpg", "wb", "updated", "update",
    "retrain", "retrained", "wedding", "weddings", "portrait", "portraits", "studio", "photography",
    "photo", "photos", "general", "natural", "classic", "warm", "manual", "light", "dark", "bold",
    # plan words: "Founder user" is about the plan, not "The Founder Profile"
    "founder", "founders", "pro", "max", "essentials", "complete", "select", "selects", "unlimited",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", (text or "").lower())


def _phrase_in(name: str, text: str) -> bool:
    words = _words(name)
    if not words or (len(words) == 1 and words[0] in COMMON):
        return False
    return re.search(r"(?<![a-z0-9])" + r"\W+".join(map(re.escape, words)) + r"(?![a-z0-9])", text) is not None


def match_named_profile(text: str, candidates: list[dict]) -> dict | None:
    """Returns the candidate profile the ticket text names, or None.

    A full-name match beats a match on a single distinctive word ("LAX" for "Lux by Victor Lax").
    Ties go to the most recently used profile. Generic words like "wedding" or "profile" never
    count on their own, so ordinary ticket text doesn't pick a profile by accident."""
    low = (text or "").lower()
    text_words = set(_words(low))
    best, best_score = None, 0
    for c in candidates:
        name = c.get("profile_name") or ""
        if _phrase_in(name, low):
            score = 2
        elif any(w in text_words for w in _words(name) if w not in COMMON and len(w) >= 3):
            score = 1
        else:
            continue
        newer = best is not None and str(c.get("last_used") or "") > str(best.get("last_used") or "")
        if score > best_score or (score == best_score and newer):
            best, best_score = c, score
    return best
