"""Classifies the issue and writes a short summary from the Intercom chat."""
import json
import re

import requests

SYSTEM = """You triage support conversations for Aftershoot, an AI photo culling and editing app.
Classify the customer's main problem into exactly one category and summarise it.

Categories:
{categories}

Rules:
- Pick the category for the customer's main complaint, not side questions.
- If colours look right in Aftershoot but different in Lightroom or Capture One, use "color_rendering".
  If the edit already looks wrong inside Aftershoot, use the category for what is wrong (usually
  "profile_quality"), even if it also looks wrong in Lightroom.
- The summary is 1 to 3 short lines in plain English: what is wrong, where it shows up, and anything
  the customer already tried. No greetings, no names, no email addresses.

Reply with JSON only, no markdown fences:
{{"category": "<one of: {keys}>", "summary": "<1-3 lines>", "confidence": "high|medium|low"}}"""


def build_prompt(ticket: dict, transcript: str | None, plan: str | None, last_edit: dict | None) -> str:
    edit = last_edit or {}
    context = [
        f"Jira title: {ticket['summary']}",
        f"Jira description: {ticket['description'][:2000]}",
        f"Plan at ticket: {plan or 'unknown'}",
        f"Last edit before ticket: profile type {edit.get('profile_type') or 'unknown'}, "
        f"profile '{edit.get('profile_name') or 'unknown'}', crop {edit.get('crop_on')}, "
        f"straighten {edit.get('straighten_on')}, masking {edit.get('masking_on')}",
        "",
        "Conversation:",
        transcript or "(no Intercom conversation available; use the Jira title and description)",
    ]
    return "\n".join(context)


def parse_reply(text: str, valid: set[str]) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    data = json.loads(cleaned)
    if data.get("category") not in valid:
        data["category"] = "others"
        data["confidence"] = "low"
    return data


class Classifier:
    def __init__(self, api_key: str, cfg: dict):
        self.model = cfg["classify"]["model"]
        cats = cfg["classify"]["categories"]
        self.valid = set(cats)
        self.system = SYSTEM.format(
            categories="\n".join(f"- {k}: {v}" for k, v in cats.items()),
            keys=", ".join(cats),
        )
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })

    def classify(self, ticket: dict, transcript: str | None, plan: str | None, last_edit: dict | None) -> dict:
        r = self.session.post("https://api.anthropic.com/v1/messages", timeout=120, json={
            "model": self.model,
            "max_tokens": 400,
            "system": self.system,
            "messages": [{"role": "user", "content": build_prompt(ticket, transcript, plan, last_edit)}],
        })
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        try:
            return parse_reply(text, self.valid)
        except (json.JSONDecodeError, AttributeError):
            return {"category": "others", "summary": text[:300], "confidence": "low"}
