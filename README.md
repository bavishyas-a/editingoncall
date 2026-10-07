# AI editing on-call dashboard

A daily job that collects every Editing-pod on-call ticket tagged `editing-ai-quality`, works out what plan
the user was on when they raised it and what they're on now, classifies the issue from the Intercom chat,
and writes it all to a database. The dashboard (Omni, or the HTML page this job generates) reads from there.

## What each field comes from

| Field | Source | How |
|---|---|---|
| Ticket, created, status, assignee | Jira | Filter in `config.yaml` (`project = ONCL`, Pod = Editing, Issue topic = editing-ai-quality). All statuses included. |
| Intercom link | Jira `customfield_10816` | Conversation ID parsed from the URL. |
| User ID | Jira `customfield_10616` | Falls back to the Intercom contact's `external_id`, then to an email on the ticket (in the field or the description) looked up in PostHog. |
| Email | Intercom contact | Falls back to the email on the ticket, then PostHog. |
| Plan at ticket | PostHog events | Plan on the user's **last event at or before the ticket was created** (`person.properties` on events). Stored once, never overwritten. |
| Plan now | PostHog persons | Refreshed every run, and saved daily in `plan_snapshots`. |
| What changed | Computed | Compares plan features from the mapping in `config.yaml`: lost editing, downgrade, upgrade, canceled, payment past due, trial. |
| Profile ID | Jira, then PostHog | In order: (1) an ID on the ticket, from the Jira field in `jira.fields.profile_id` or labelled "Profile ID" in the description; (2) a profile the ticket names (title, description or Intercom chat), matched against the profiles the user edited with in the 90 days before the ticket; (3) the profile from the user's last `Edit Completed` before the ticket. The dashboard shows which source was used. |
| Profile name, type | PostHog | Looked up from the profile ID (latest `Edit Completed` or `chooseProfile` event using it). Type is custom, marketplace or instant. |
| Feature, summary | Claude, from the Intercom chat | One of profile quality, colour rendering, masking, straightening, cropping, others, plus a 1–3 line summary. Plan and last-edit settings are given as context. Done once per ticket. |
| Plan mismatch | Computed | Flags things like a cropping complaint from an Essentials user, who doesn't have cropping. |

## Setup

1. **Database.** Create a Postgres (or any SQLAlchemy-supported) database the job can write to and Omni can
   read. The job creates two tables on first run: `oncall_tickets` and `plan_snapshots`.
2. **Credentials.** Copy `.env.example` to `.env` and fill it in for local runs:
   - Jira: an Atlassian API token for an account that can see the ONCL project.
   - Intercom: an access token from a Developer Hub app with read access to conversations and contacts.
   - PostHog: a personal API key with `query:read`, plus the project ID.
   - Anthropic: an API key for classification.
3. **Try it locally.**
   ```bash
   pip install -r requirements.txt
   python -m pytest                                   # offline tests, built from real September tickets
   python -m oncall.run --since 2026-09-01 --dry-run  # prints rows, writes nothing
   python -m oncall.run --since 2026-09-01 --html site/index.html
   ```
4. **Schedule it.** Push to a private GitHub repo and add the same values as repository secrets
   (`JIRA_EMAIL`, `JIRA_API_TOKEN`, `INTERCOM_TOKEN`, `POSTHOG_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`)
   and variables (`POSTHOG_HOST`, `POSTHOG_PROJECT_ID`). The workflow runs daily at 08:00 IST and can be
   started by hand with a backfill date. Any other scheduler works too: it's one command.

## The dashboard

The simplest option is an **Omni dashboard on `oncall_tickets`**: it stays behind your existing login, and
`plan_snapshots` gives you history charts for free. The job also writes `site/index.html`, a self-contained
page with filters (downgraded or lost, trial or payment issue, data gaps, category) that you can host on
any internal, login-protected site. **Don't put it on a public URL**: it contains customer emails.

## How a run works

The job runs once a day at 8 AM IST. Each run adds new tickets and updates existing ones from the last
`lookback_days` (120 by default), so plan changes keep being tracked for four months after a ticket.
Plan at ticket, profile and classification are filled once and kept; current plan, change and Jira status
are refreshed. If a profile ID is added to a ticket after its first run, it replaces the last-edit fallback.

Known inefficiency, deliberately left for later: every run re-fetches all tickets in the window from Jira
and re-queries current plans for all of them. Stored fields (plan at ticket, profile, classification) are
not re-queried, so the cost is a few small PostHog queries per 25 users. Incremental fetching (only tickets
updated since the last run) is the obvious next step if this gets slow. Use `--reclassify` after changing the categories or
prompt. Failures on one ticket (an Intercom error, say) are recorded in `data_gap` and don't stop the run.

## To confirm with Aakansha and Dhruv

- **Where the profile ID lives on the ticket.** The ONCL Bug issue type has no profile field (36 fields
  checked), and none of September's tickets contain a profile ID in their text or Intercom attributes.
  If Dhruv meant a field that's being added, set `jira.fields.profile_id` in `config.yaml`.
  Until then profiles come from PostHog: in September, 73 of 77 users with a user ID had one.
- **Source of truth for plans.** PostHog is app-reported. Two September users said they'd left
  (ONCL-12386, ONCL-13038) while PostHog still showed them as active. If billing data in Omni is
  authoritative, swap `current_plans` in `oncall/posthog.py` for a billing query and keep the rest.
- **Plan mapping.** Custom-profile limits and crop/straighten access for the new plans (Edit, Select + Edit,
  Complete…) are `null` in `config.yaml` until confirmed. Unmapped names show as "unknown plan".
- **What counts as lost.** Currently: losing editing, losing any feature, fewer custom profiles, or canceling.
  Yearly users won't show a change until renewal; consider adding renewal date from billing.
- **Stale trials.** Several users read as "Trialing" a month after their ticket.
- **Which flag defines an AI issue.** The filter uses Issue topic = editing-ai-quality; the "AI Issue?" field
  (`customfield_11405`) says "No" on most of these tickets. It's stored as `ai_issue_flag` for comparison.
- **Internal notes.** Intercom internal notes are left out of the classifier's input by default
  (`intercom.include_internal_notes`).

## Files

```
config.yaml            filter, field IDs, categories, plan mapping
oncall/run.py          the job
oncall/jira.py         ticket fetch and parsing
oncall/intercom.py     conversation transcript and contact
oncall/posthog.py      user, plan and last-edit queries (HogQL)
oncall/plans.py        plan normalisation and change rules
oncall/classify.py     category and summary
oncall/store.py        database tables and upserts
oncall/export_html.py  dashboard page
tests/                 offline tests
```
