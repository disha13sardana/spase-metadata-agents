---
name: spase-affiliation-enricher
description: >
  Procedure for enriching the author candidates produced by the spase-author-finder
  agent with ORCID identifiers and institutional affiliations. Takes the finder's
  JSON output, fills the `orcid` and `affiliation` fields for INCLUDED candidates
  with CONFIRMED identities using dedicated ORCID and Crossref lookups, validates
  any values the finder pre-filled, and writes an enriched JSON file.
  Confirm-or-leave-null: never guess an ORCID or affiliation. Does NOT find new
  people, assign roles, or build the Contacts table.
user-invocable: false
---

# SPASE Affiliation & ORCID Enricher

This skill takes the candidate list produced by the `spase-author-finder` agent and fills in two fields the finder handled only opportunistically: `orcid` and `affiliation`. This skill does the dedicated lookups the finder deliberately avoided, and validates any values the finder happened to capture.

**Scope — read this first.** This skill ONLY enriches ORCID and affiliation for people the finder already identified. It does NOT:
- find new candidate people (that is the finder's job)
- assign SPASE roles (downstream agent)
- build the Contacts table or format PublicationInfo
- create or edit Person records

**Critical principle — confirm or leave null.** Never guess an ORCID or an affiliation. A wrong ORCID misattributes a real person's identity; a wrong affiliation misrepresents their institution. Only fill a field when the value is confirmed by corroborating evidence (see below). When you cannot confirm, leave the field `null` and record why in the enrichment provenance. An honest `null` is correct; a confident wrong answer is a serious error.

**Corollary — enrichment confidence is capped by identity confidence.** A Crossref-deposited ORCID proves "this ORCID belongs to the person who authored this paper." It does NOT prove "the paper's author is your candidate." If the finder's link between the candidate and the evidence is weak (e.g. a name inferred from initials only), no lookup can launder that into a confirmed identity. Such candidates are not enriched — see the Identity Gate below.

---

## Input

The JSON file produced by the `spase-author-finder` agent, typically at
`spase_records/<record-name>/author_candidates.json`.

Also obtain the record's **operating span** (start/stop dates of the resource),
from the finder output if present or by re-reading the source SPASE record.
It is required for era-matched affiliation. An open-ended span (no stop date,
still operating) is normal — handle it per the overlap rules below.

---

## Which candidates to process — the Identity Gate

Process a candidate only if BOTH hold:

1. **`status: "included"`.** Leave `excluded` candidates' objects entirely untouched.
2. **Identity is confirmed.** The finder's evidence establishes the person's full
   name from at least one source — not a name reconstructed from initials, and not
   an identity the finder itself flagged as inferred or uncertain. Check the
   candidate's confidence level and evidence notes.

For included candidates that FAIL the identity check (e.g. a record contact
"I.E. Dammasch" whose full name was only inferred by matching initials against a
paper's author list):
- Leave `orcid` and `affiliation` null.
- Set `enrichment.lookup_status: "skipped-unconfirmed-identity"`.
- In `enrichment.notes`, state why the identity is unconfirmed. You MAY record a
  possible match there for the reviewer (e.g. "paper author 'Ingolf E. Dammasch',
  ORCID 0000-000X-…, is plausibly this contact, but the link rests on initials
  only") — but never place an unconfirmed value in the `orcid` or `affiliation`
  field itself. The field is either confirmed or empty.

Do not attempt to "upgrade" a weak identity through lookups. Identity confirmation
is the finder's job; if it becomes clear the finder should have found stronger
evidence, note that for the human reviewer rather than acting on it.

---

## Output

Write an enriched JSON file to
`spase_records/<record-name>/author_candidates_enriched.json`.
**Do not overwrite the finder's output** — keep both files for traceability.
Also return a brief inline summary: which fields were filled, which stayed null
and why, and anything flagged for review.

The enriched file preserves the finder's schema and adds, per included candidate,
an `enrichment` object:

```json
"enrichment": {
  "orcid_source": "Crossref (paper DOI) | ORCID name-search (corroborated) | finder (pre-existing, verified) | null",
  "orcid_confidence": "Confirmed | null",
  "affiliation_source": "ORCID employment | Crossref (paper DOI) | finder (pre-existing, verified) | null",
  "affiliation_type": "era-matched | current | as-deposited | null",
  "lookup_status": "complete | partial-api-error | skipped-unconfirmed-identity",
  "notes": "free text — ambiguity, multiple matches, discrepancies, why a field is null"
}
```

Field semantics:
- `orcid_confidence` is binary: `Confirmed` or `null`. There is no "probable" tier —
  unconfirmed possibilities live in `notes` only.
- `affiliation_type`:
  - `era-matched` — held during the record's operating span, from dated ORCID employment.
  - `current` — the person's current/most-recent affiliation (no era overlap found, or no dated history).
  - `as-deposited` — the affiliation string a publisher deposited with the paper in
    Crossref. This is affiliation-at-publication-date; it may or may not fall inside
    the operating span. Do not relabel it era-matched even if the publication date
    falls in the span — the label records the evidence type, not an inference.
- `lookup_status` separates the two very different kinds of "nothing found":
  - `complete` — all intended lookups ran; nulls mean "looked and could not confirm."
  - `partial-api-error` — one or more lookups failed (timeout, HTTP error, malformed
    response). Name the failed lookup(s) in `notes`. On a re-run, only these
    candidates need retrying.
  - `skipped-unconfirmed-identity` — gated out; no lookups attempted (see Identity Gate).

---

## Lookup Procedure (per gated-in candidate)

Work in this order. Stop querying a field as soon as it is confirmed.

### Step 1 — Validate anything the finder pre-filled

Do not skip pre-filled fields; validate them so every candidate leaves this skill
with consistent provenance. Never silently overwrite a finder value — when a
lookup disagrees with a pre-filled value, record both and flag for review.

**Pre-filled ORCID:**
1. Check format (`XXXX-XXXX-XXXX-XXX[0-9X]`) and the ISO 7064 mod 11-2 checksum
   of the final character.
2. Fetch the ORCID record and corroborate: does it show a work or employment
   consistent with the instrument, observatory, or data provider institution?
3. If valid and corroborated → keep it; `orcid_source: "finder (pre-existing, verified)"`,
   `orcid_confidence: "Confirmed"`.
4. If the checksum fails or corroboration fails → set `orcid` to null in the
   enriched file, record the finder's value and the failure in `notes`, and
   proceed to Step 2 as if the field were empty. (The finder's file still holds
   the original value; nothing is lost.)

**Pre-filled affiliation:** keep it as a data point, but still run Step 3 — the
finder's opportunistic value is almost certainly a current or as-deposited
affiliation, and the whole point of era-matching is that those can differ
(original vs. current PI institution). If the era-matched lookup:
- agrees with the finder's value → keep it, set `affiliation_type` accordingly,
  `affiliation_source: "finder (pre-existing, verified)"`.
- disagrees → put the era-matched value in `affiliation` (it is dated,
  evidence-backed), keep the finder's value in `notes` with an explicit
  "differs from finder value" flag for the reviewer.
- yields nothing → keep the finder's value, `affiliation_type: "current"` or
  `"as-deposited"` per its origin if known, else note the type is unknown.

### Step 2 — Resolve ORCID

**Route A — paper DOI via Crossref (preferred; identity anchored to authorship):**
1. Take the paper DOI(s) from the candidate's `evidence` links. If several, try
   each in the finder's evidence order; stop at the first confirmation.
2. `GET https://api.crossref.org/works/<DOI>` and read the `author` array.
3. Identify the matching author. "Matching" means: family name matches exactly
   after normalizing case and diacritics, AND the given name is full-name
   compatible with the candidate's known full name. Initials-compatibility alone
   is NOT a match for confirmation purposes (it may only be recorded in `notes`).
4. If the matching author carries an `ORCID` field, treat it as **Confirmed** —
   the publisher tied that iD to that author on that paper.

**Route B — ORCID name search (only with corroboration):**
1. `GET https://pub.orcid.org/v3.0/expanded-search/?q=family-name:<name>+AND+given-names:<name>`
   (header `Accept: application/json`).
2. A name search may return multiple people. NEVER accept a match on name alone.
3. Accept an iD only if the record itself corroborates identity: a listed work
   or dated employment consistent with the instrument, observatory, or data
   provider institution.
4. If multiple plausible matches remain, or the only match cannot be
   corroborated, leave `orcid` null and describe the ambiguity in `notes`
   (including candidate iDs, so the reviewer can resolve it in one click).

### Step 3 — Resolve affiliation (era-matched, then current, then Crossref)

With a confirmed ORCID:
1. `GET https://pub.orcid.org/v3.0/<orcid-id>/employments` (header
   `Accept: application/json`).
2. **Era-matched (preferred):** select the employment whose date range overlaps
   the record's operating span, using the overlap rules below.
   `affiliation_type: "era-matched"`.
3. **Current (fallback):** if no dated employment overlaps (or none is dated),
   use the current/most-recent affiliation. `affiliation_type: "current"`.

Without a usable ORCID employment history (or without a confirmed ORCID at all,
when identity was confirmed some other way):
4. **Crossref fallback:** use the affiliation string deposited for that author on
   the paper, if any. `affiliation_type: "as-deposited"`.
5. If nothing yields a value, leave `affiliation` null with `lookup_status`
   reflecting whether lookups completed.

**Date-overlap rules (era-matching):**
- A missing employment end date means the position is ongoing (extends to today).
- ORCID dates are often year-only. Treat a year as spanning Jan 1–Dec 31; any
  calendar overlap with the operating span counts.
- An open-ended operating span (resource still producing data) overlaps every
  employment that did not end before the span's start.
- **Multiple overlapping employments** (mid-span move, or concurrent positions):
  prefer the one matching the data provider's institution; if none matches or
  several do, take the longest-overlapping one and list the others in `notes`.
  A mid-span institutional change is itself useful signal (original vs. current
  PI generation) — note it explicitly, e.g. "affiliation changed during operating
  span: Institution X (2010–2015), Institution Y (2015–present)."

---

## Tools / APIs

Prefer raw API calls (curl via Bash, if available) over summarized web fetches
for the two structured APIs — exact dates and author-array contents matter and
must not be paraphrased away. Use WebFetch only for ordinary web pages.

- **Crossref**: `https://api.crossref.org/works/<DOI>` — author lists with ORCIDs
  and affiliations as deposited by publishers. Include a `mailto:` contact in the
  `User-Agent` header (Crossref "polite pool"). Primary route for ORCID
  resolution because it anchors identity to a specific authorship.
- **ORCID public API** (`https://pub.orcid.org/v3.0/`, header
  `Accept: application/json`):
  - `/<orcid-id>/record` — full public record (works, employments) for corroboration.
  - `/<orcid-id>/employments` — dated employment history for era-matching.
  - `/expanded-search/?q=...` — name search (Route B only, with corroboration).

Unlike the finder, this skill IS permitted to make dedicated per-candidate
lookups — that is its purpose. If an API call fails, retry once; on repeated
failure set `lookup_status: "partial-api-error"` and name the failed call in
`notes` rather than treating the absence of data as "could not confirm."

---

## Disambiguation

This skill is where same-name disambiguation comes due (the finder deferred it).
- Never accept an identity on name match alone.
- Corroborate against: the paper-DOI authorship, an ORCID work/employment
  consistent with the instrument or provider institution, or an affiliation
  matching the data provider.
- When you cannot confirm, leave the field null and explain in `enrichment.notes`.
  Do not pick the "most likely" ORCID to avoid an empty field.

---

## Human-Approval Gate

This skill produces an enriched candidate list for human review. It does not
write to any SPASE record, does not assign roles, and does not create Person
records. A human reviews the enriched candidates — paying particular attention to
`enrichment.notes` entries flagging ambiguity, finder/lookup discrepancies, or
mid-span affiliation changes, and to any candidate with
`lookup_status: "skipped-unconfirmed-identity"` — before anything downstream
acts on them.