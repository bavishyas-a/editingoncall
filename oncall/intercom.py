"""Reads the Intercom conversation linked from a ticket."""
import html
import re

import requests

CONV_RE = re.compile(r"conversation/(\d+)")
TAG_RE = re.compile(r"<[^>]+>")
SPEAKERS = {"user": "Customer", "lead": "Customer", "contact": "Customer", "admin": "Support", "bot": "Bot"}


def conversation_id(url: str | None) -> str | None:
    m = CONV_RE.search(url or "")
    return m.group(1) if m else None


def clean(body: str | None) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", body or "")).split())


def build_transcript(conv: dict, include_notes: bool, max_chars: int) -> str:
    """Customer and support messages in order, labelled by speaker."""
    lines = []
    src = conv.get("source") or {}
    if src.get("body"):
        lines.append(f"Customer: {clean(src['body'])}")
    for part in (conv.get("conversation_parts") or {}).get("conversation_parts", []):
        body = clean(part.get("body"))
        if not body:
            continue
        if part.get("part_type") == "note":
            if not include_notes:
                continue
            who = "Internal note"
        else:
            author = (part.get("author") or {}).get("type")
            who = SPEAKERS.get(author, author or "Unknown")
        lines.append(f"{who}: {body}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n[truncated]"


class IntercomClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Intercom-Version": "2.11",
        })

    def _get(self, path: str, **params) -> dict:
        r = self.session.get(f"https://api.intercom.io/{path}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def fetch(self, url: str | None, cfg: dict) -> dict:
        """Transcript plus the contact's email and external_id, when available."""
        empty = {"transcript": None, "email": None, "external_id": None}
        conv_id = conversation_id(url)
        if not conv_id:
            return empty
        conv = self._get(f"conversations/{conv_id}", display_as="plaintext")
        email = external_id = None
        contacts = (conv.get("contacts") or {}).get("contacts", [])
        if contacts:
            c = self._get(f"contacts/{contacts[0]['id']}")
            email, external_id = c.get("email"), c.get("external_id")
        icfg = cfg["intercom"]
        return {
            "transcript": build_transcript(conv, icfg["include_internal_notes"], icfg["max_transcript_chars"]),
            "email": email,
            "external_id": external_id,
        }
