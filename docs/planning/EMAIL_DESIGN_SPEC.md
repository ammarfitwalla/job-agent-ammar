# JobAwn Email Design Spec — Colors & Content Standard

Status: IMPLEMENTED (local, awaiting deploy approval)
Owner: Ammar
Related work: Scheduled mail queue (welcome, referral-requested, referral-accepted, company-joined)

Purpose: Every automated email from JobAwn must share ONE visual identity and ONE
content structure. This spec defines the single source of truth for colors,
layout components, and copy so that all future templates (and the existing
verification email) stay consistent.

---

## 1. Palette (single source of truth)

A fixed, non-configurable set. Semantic roles — never pick ad-hoc hex values.

| Token               | Hex       | Usage |
|---------------------|-----------|-------|
| `--brand-primary`   | `#4f46e5` | Header gradient start, primary CTA, strong links |
| `--brand-primary-2` | `#6366f1` | Header gradient end, secondary hover |
| `--brand-ink`       | `#1e293b` | Main headings / body emphasis (`<p>` title) |
| `--brand-body`      | `#475569` | Paragraph text |
| `--brand-muted`     | `#64748b` | Secondary text, footnotes, meta |
| `--brand-faint`     | `#94a3b8` | Legal/copyright line |
| `--brand-elevate`   | `#eef2ff` | Boxed content background (code, alert, score) |
| `--brand-border`    | `#c7d2fe` | Dashed box borders, dividers accent |
| `--brand-page`      | `#f8fafc` | Outer email background |
| `--brand-card`      | `#ffffff` | Inner card background |
| `--brand-divider`   | `#e2e8f0` | Card footer top border, hairline rules |
| `--brand-success`   | `#059669` | Positive state (accepted, credits added) |
| `--brand-warning`   | `#d97706` | Attention (limit reached, expires soon) |
| `--brand-danger`    | `#dc2626` | Error/negative state (declined — reserved) |

Rules:
- Only the tokens above appear in any email HTML.
- Accent tints are derived by opacity on white, never new hex values.
- Only CTA buttons and links may use `--brand-primary`. Text body never is colored primary.
- Success/warning/danger only appear as small status chips, NOT as headlines.

---

## 2. Layout skeleton (shared across all emails)

Every email = one outer wrapper + one inner card + 5 zones:

```
[ outer : #f8fafc, padding 32px 16px ]
  card : #ffffff, max-width 480px, radius 16px, border 1px #e2e8f0
  ├─ ZONE A — Header       gradient 135deg #4f46e5→#6366f1
  │    product name (26-28px bold white) + subtitle (13px #c7d2fe)
  ├─ ZONE B — Body         padding 28px
  │    H1 heading 17-18px bold #1e293b
  │    intro line 15px #1e293b (HELLO_LINE)
  │    body paragraphs 14px #475569, line-height 1.5
  │    optional content box (dashed #c7d2fe, bg #eef2ff, radius 12px)
  ├─ ZONE C — CTA          single centered button
  │    bg #4f46e5, text #ffffff, radius 10px, padding 12px 24px,
  │    href https://jobawn.com with utm_campaign tag (see CTAs)
  ├─ ZONE D — Meta         "why you got this" line 13px #64748b
  └─ ZONE E — Footer       bg #f8fafc, top border #e2e8f0,
       brand line 12px #94a3b8 + jobawn.com link #6366f1
```

Constraints:
- max-width 480px always.
- Dark-mode-agnostic: inline styles only; rely on card/contrast, no `@media`.
- All styles INLINE (email clients strip `<style>`).
- Text version must mirror zones B–E with plain-text equivalents.

---

## 3. Content structure (shared copy blocks)

Standardized in this order on every email:

1. `subject` — one of the exact patterns in §5. Never free-form.
2. `greeting` — always `Hi <first-name>,` (fallback `Hi there,` if no name).
3. `who-why` — one sentence stating the trigger (no theatrics).
4. `body` — 1–3 short paragraphs, 14px, one idea each.
5. `info box` (optional) — the only place for code/score/company/job data.
6. `cta` — exactly ONE primary action (see §4). Never zero, never two primary.
7. `unsubscribe-note` — "This email was sent because <one-line reason>. Log in to
   JobAwn to manage notifications. If you didn't expect this, ignore this email."
8. `signoff` — signature block, see Tone.

Tone rules (all templates):
- Second person, short sentences, no exclamation marketing-speak.
- Refer to product as **JobAwn**; URLs render as `https://jobawn.com` in text,
  `<a href="...">jobawn.com</a>` in HTML.
- Escape ALL user-generated content (names, company, job title, message) with
  `html.escape` — this is a hard requirement, not a suggestion.
- Never include raw secrets, tokens, or one-time codes except in the dedicated
  code box (verification email only).

---

## 4. CTA conventions

- Exactly one primary button per email.
- URL format: `https://jobawn.com/{page}?utm_campaign={campaign}&utm_source=email`
  where `{campaign}` = the dedup-key family (e.g. `referral_requested`,
  `welcome`, `company_joined`, `referral_accepted`).
- Button label: verb + object, ≤3 words (`Review referral`, `Get started`,
  `Open JobAwn`).
- Secondary/tertiary actions are PLAIN text links in Zone D, never a second button.

---

## 5. Per-email template map

| Email | Campaign | Subject (exact pattern) | Greeting target | Top CTA |
|---|---|---|---|---|
| Verification (existing) | `verify` | `JobAwn — Your Verification Code` | n/a (keep as-is) | code box; `Open JobAwn` |
| Signup / Welcome | `welcome` | `JobAwn — Welcome to JobAwn` | new user | `Start searching jobs` → /app |
| Referral requested (→referrer) | `referral_requested` | `JobAwn — Referral request: <job_title>` | referrer (to_email) | `Review request` → /app#referrals |
| Referral accepted (→seeker) | `referral_accepted` | `JobAwn — <First name> accepted your referral request` | seeker (from_email) | `View contact & next steps` → /app#referrals |
| Company joined alert (→watcher) | `company_joined` | `JobAwn — Someone from <company> just joined` | watcher(s) | `Find a referrer at <company>` → /app |
| Confirm reminder (→referrer) | `confirm_reminder` | `JobAwn — Did you refer <seek_first> at <company>?` | referrer (to_email) | `Confirm referral` → /app#referrals |
| Confirm reminder (→seeker) | `confirm_reminder` | `JobAwn — Did <ref_first> refer you at <company>?` | seeker (from_email) | `Confirm referral` → /app#referrals |
| Weekly re-engagement (fresh jobs) | `engage_weekly` | `JobAwn — <count> fresh <role> jobs near <location>` | dormant user | `See fresh jobs` → /app |
| Weekly re-engagement (fallback) | `engage_weekly` | `JobAwn — Fresh roles are waiting for you` | dormant user | `See fresh roles` → /app |

Per-type variable payloads:

- **Welcome**: name; `info box` = "quick-start" checklist (set company + position,
  opt in to referrals, add resume).
- **Referral requested**: job_title, company, match_score (0–100 badge in info box),
  sender's personal message (escaped), monthly-limit remaining (only when it
  reaches ≤2).
- **Referral accepted**: seeker sees referrer first/last name, company, position,
  and LinkedIn URL in the info box + next-step: "Review the résumé, then confirm
  the referral in your dashboard to release your credits." No false promise of
  credits to the seeker (credits go to the referrer).
- **Company joined**: company name + "A new opted-in professional from <company>
  joined JobAwn and is open to referrals." CTA lands on the referrer directory
  filtered to that company.
- **Confirm reminder (→referrer)**: seeker name + company. Fired once when the
  post-accept cooldown (48h, prod) elapses and the referral is still awaiting
  confirmation. Copy asks "did you actually refer them?" and mentions the
  referrer earns **+10 credits** once both sides confirm.
- **Confirm reminder (→seeker)**: referrer name + company. Same trigger/timing;
  neutral copy ("did they actually refer you?") — no credit promises to the
  seeker. Only un-confirmed parties are emailed (per-party dedup key
  `confirm_reminder:{req_id}:receiver|sender`, one reminder each).
- **Weekly re-engagement**: weekly nudge to users with no app visit in
  `ENGAGEMENT_DORMANT_DAYS` (7, prod) and joined ≥ `ENGAGEMENT_MIN_AGE_DAYS` (3)
  days ago, excluding `users.email_opt_out = 1`. Content is real cache data: the
  anchor role+location comes from the newest saved search, else profile
  position + city/state, with the free-text role resolved onto a cached role
  (exact → case → qualifier → typo). Job highlights come from `job_cache`
  (no LLM, no scraping), read tightest-scope-first — city/state, then state,
  then country — and the copy names **only** the scope that produced the jobs;
  when that's country-wide the subject carries no location at all (no "your
  area"). Dedup key `engage:{YYYY-WW}:{email}` → exactly one per user/week.
  Footnote has a signed unsubscribe link (`/api/email/unsubscribe`). **Strictly
  generic fallback** — if there is no anchor or no cached jobs, send
  `build_engagement_fallback` ("Fresh roles are waiting for you"); never invent
  counts or numbers in the subject/copy.

---

## 6. Success / warning / danger chips (reserved)

Used only inside the info box, as a 12px uppercase chip before detail lines:
- Success `#059669` — "MATCH SCORE 87/100", "REFERRAL COMPLETED"
- Warning `#d97706` — "2 OF 5 REFERRALS LEFT THIS MONTH"
- Danger `#dc2626` — reserved; not wired for any current email.

---

## 7. Implementation mapping (future build must follow)

- Token constants live in ONE place: `backend/emails/tokens.py`
  (`PALETTE`, `LAYOUT`, `BUTTON_HTML`), imported by every template builder.
- Template builders in `backend/emails/templates.py`; each returns
  `(subject, html, text, utm_campaign)` and MUST call `html.escape` on inputs.
- `text_body` mirrors sections §3.1–3.8 with plain-text equivalents.
- New email types require: a spec row in §5, a builder, a test asserting
  (a) subject pattern, (b) presence of exactly one CTA, (c) all hex values
  resolving to palette tokens, (d) escaped user input.
- The existing verification email remains the visual reference; refactor to
  tokens on its next touch.

---

## 8. Acceptance checklist (for the build phase)

- [x] No hex value outside the palette table appears in generated HTML.
- [x] Every email renders the 5-zone layout in §2.
- [x] Every email has exactly one primary CTA with a `utm_campaign`.
- [x] All dynamic fields HTML-escaped (test-proven).
- [x] `subject` matches its §5 pattern verbatim.
- [x] Plain-text body provided for every HTML template.
- [x] Tests assert palette/single-CTA/escaping for each new template.

Notes from the build (deliberate, matches earlier scope decisions):
- Emails are delivered by a dedicated mail worker (`start_mail_worker`, 5-min
  cadence, gated on `MAIL_QUEUE_ENABLED`) — independent of the prewarm
  scheduler, so it runs even when `SCHEDULER_ENABLED=False`.
- NOT wired (chosen out of scope): declined-referral email, credits-awarded
  email. Spec rows for those are intentionally absent/reserved.
- Not yet wired: the "monthly-limit remaining (≤2)" warning chip in
  `referral_requested`. Reserved for a later pass.
- `email_queue` rows are never pruned (sent/failed accumulate). A GC pass can be
  added to `gc_sessions`/`gc_job_cache` on the next maintenance window.
- Cooldown-end confirmation reminders (`confirm_reminder`, one per party, gated
  on `MAIL_QUEUE_ENABLED`) are enqueued from `scheduler.enqueue_confirm_reminders`
  at the top of every mail-worker pass + at boot; the cooldown constant lives in
  `db.referral_confirm_cooldown_seconds()` (shared with `confirm_referral`).