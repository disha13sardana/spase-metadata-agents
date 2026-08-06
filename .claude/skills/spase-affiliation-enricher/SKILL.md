---
name: spase-affiliation-enricher
description: >
  Procedure for enriching the author candidates produced by the spase-author-finder
  agent with ORCID identifiers, institutional affiliations, and ROR identifiers for
  those affiliations. Takes the finder's JSON output, fills the `orcid`,
  `affiliation`, and `affiliation_ror` fields for INCLUDED candidates with CONFIRMED
  identities using dedicated ORCID, Crossref, and ROR lookups, validates any values
  the finder pre-filled, and writes an enriched JSON file.
  Confirm-or-leave-null: never guess an ORCID, an affiliation, or a ROR ID. Does NOT
  find new people, assign roles, or build the Contacts table.
user-invocable: false
---

# SPASE Affiliation, ORCID & ROR Enricher

This skill takes the candidate list produced by the `spase-author-finder` agent and fills in three fields the finder did not handle or handled only opportunistically: `orcid`, `affiliation`, and `affiliation_ror`. This skill does the dedicated lookups the finder deliberately avoided, and validates any values the finder happened to capture.

**Scope — read this first.** This skill ONLY enriches ORCID, affiliation, and the affiliation's ROR ID for people the finder already identified. It does NOT:
- find new candidate people (that is the finder's job)
- assign SPASE roles (downstream agent)
- build the Contacts table or format PublicationInfo
- create or edit Person records

**Critical principle — confirm or leave null.** Never guess an ORCID, an affiliation, or a ROR ID. A wrong ORCID misattributes a real person's identity; a wrong affiliation misrepresents their institution; a wrong ROR ID misattributes their institution to a different organization in a public registry. Only fill a field when the value is confirmed by corroborating evidence (see below). When you cannot confirm, leave the field `null` and record why in the enrichment provenance. An honest `null` is correct; a confident wrong answer is a serious error.

**Corollary — enrichment confidence is capped by identity confidence.** A Crossref-deposited ORCID proves "this ORCID belongs to the person who authored this paper." It does NOT prove "the paper's author is your candidate." If the finder's link between the candidate and the evidence is weak (e.g. a name inferred from initials only), no lookup can launder that into a confirmed identity. Such candidates are not enriched — see the Identity Gate below.

**Corollary — ROR confidence is capped by affiliation confidence.** A ROR ID is the registry's identifier for the institution named in `affiliation`. It is a normalization of a field this skill already resolved, not independent evidence. No `affiliation` means no `affiliation_ror`; a shaky affiliation cannot be firmed up by finding a confident ROR match for the string.

---

## Input

The JSON file produced by the `spase-author-finder` agent, typically at
`spase_records/<record-name>/author_candidates.json`.

Read the record's **operating span** from the finder output's top-level
`operating_span` field (preferred — it guarantees both agents era-match against
the same dates the finder used). Only if that field is absent (output from an
older finder version), fall back to re-reading the source SPASE record. The span
is required for era-matched affiliation. An open-ended span (`stop: null`, still
operating) is normal — handle it per the overlap rules below.

---

## Which candidates to process — the Identity Gate

Process a candidate only if BOTH hold:

1. **`status: "included"`.** Leave `excluded` candidates' objects entirely untouched.
2. **Identity is confirmed.** The finder's evidence establishes the person's full
   name from at least one source — not a name reconstructed from initials, and not
   an identity the finder itself flagged as inferred or uncertain. Judge this from
   the **evidence entries and notes** (source descriptions, "initials-inferred"
   flags, ambiguity notes), NOT from the candidate's `confidence` field — the
   finder's confidence measures evidence strength for authorship, not certainty
   about who the person is, and the two can differ in either direction.

For included candidates that FAIL the identity check (e.g. a record contact
"I.E. Dammasch" whose full name was only inferred by matching initials against a
paper's author list):
- Leave `orcid`, `affiliation`, and `affiliation_ror` null.
- Set `enrichment.lookup_status: "skipped-unconfirmed-identity"`.
- In `enrichment.notes`, state why the identity is unconfirmed. You MAY record a
  possible match there for the reviewer (e.g. "paper author 'Ingolf E. Dammasch',
  ORCID 0000-000X-…, is plausibly this contact, but the link rests on initials
  only") — but never place an unconfirmed value in the `orcid`, `affiliation`, or
  `affiliation_ror` field itself. The field is either confirmed or empty.

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

**Preserve the finder's file in full.** Copy every top-level field the finder
wrote — `record`, `date`, `cmad`, `instrument_coverage`, `notes`, and any field
you do not recognize — through to the enriched file unchanged. The finder's
schema evolves; never drop a field just because this skill predates it. The ONLY
modifications this skill makes are: filling `orcid`/`affiliation`/`affiliation_ror`
on processed candidates, and adding the per-candidate `enrichment` object:

```json
"enrichment": {
  "orcid_origin": "finder | enricher | null",
  "orcid_source": "Crossref (paper DOI) | ORCID name-search (corroborated) | uncorroborated | null",
  "orcid_evidence": "DOI, ORCID URL, or page URL — null only when source is uncorroborated",
  "orcid_confidence": "Confirmed | null",
  "affiliation_origin": "finder | enricher | null",
  "affiliation_source": "Crossref (paper DOI) | ORCID employment | SPASE record | provider documentation | uncorroborated | null",
  "affiliation_evidence": "DOI, ORCID URL, ROR URL, or page URL — null only when source is uncorroborated",
  "affiliation_type": "era-matched | current | as-deposited | null",
  "ror_origin": "finder | enricher | null",
  "ror_source": "ORCID disambiguated-organization | ROR affiliation-match (chosen) | ROR query (corroborated) | uncorroborated | null",
  "ror_evidence": "ROR URL, or the ORCID URL whose employment asserted it — null only when source is uncorroborated",
  "ror_confidence": "Confirmed | null",
  "lookup_status": "complete | partial-api-error | skipped-unconfirmed-identity",
  "notes": "free text — ambiguity, multiple matches, discrepancies, why a field is null"
}
```

**Provenance fields must name evidence, not pipeline stages.** A `*_source`
field records what corroborates the value. It must never name a stage of this
pipeline. "The finder proposed it" is not evidence — it is bookkeeping, and it
belongs in `*_origin`. A curator reading a SPASE record sees only these values,
and "pre-existing" reads to them as "already in this record", which is often
false.

**Never emit `finder (pre-existing, verified)` or `finder (pre-existing)`** in
any `*_source` field. Both collapse origin and evidence into one string, and the
first hides which evidence was used — Crossref for some candidates, ORCID
employment for others. Those are different provenance and must not share a label.

- When a finder value was verified → `origin: "finder"`, `source:` whatever
  verified it, `evidence:` that identifier.
- When a finder value could not be verified → `origin: "finder"`,
  `source: "uncorroborated"`, `evidence: null`. Say so plainly rather than
  implying support that was not found. `uncorroborated` is a legitimate value,
  not a failure state; it is how the record stays honest about a value it
  carries but could not confirm.
- When this skill found the value itself → `origin: "enricher"`, plus source and
  evidence as usual.

Worked examples:

```json
// Bethge — finder value, verified against a Crossref deposit
{"affiliation_origin": "finder", "affiliation_source": "Crossref (paper DOI)",
 "affiliation_evidence": "10.1029/2022SW003044", "affiliation_type": "as-deposited"}

// Singer — finder value, verified against dated ORCID employment
{"affiliation_origin": "finder", "affiliation_source": "ORCID employment",
 "affiliation_evidence": "https://orcid.org/0000-0002-5364-6505", "affiliation_type": "era-matched"}

// Rodriguez — enricher found it directly, from dated ORCID employment
{"affiliation_origin": "enricher", "affiliation_source": "ORCID employment",
 "affiliation_evidence": "https://orcid.org/0000-0002-6847-4136", "affiliation_type": "era-matched"}

// Shape of a finder value that no lookup could verify (schematic, not a real candidate)
{"affiliation_origin": "finder", "affiliation_source": "uncorroborated",
 "affiliation_evidence": null, "affiliation_type": "current"}
```

The `affiliation_ror` field itself holds the full ROR URL form (e.g.
`https://ror.org/02wcxbg22`), not the bare ID — that is the form ROR itself
treats as canonical.

Field semantics:
- `*_origin` is bookkeeping only: `finder` if the finder proposed the value,
  `enricher` if this skill found it. It never carries evidential weight and must
  never appear in a `*_source` field.
- `*_source` names the evidence that corroborates the value, drawn from the closed
  vocabulary above. `uncorroborated` means the value is carried but nothing
  verified it.
- `*_evidence` is the specific identifier behind the source — a DOI, an ORCID URL,
  a ROR URL, or a page URL. It is `null` only when the source is `uncorroborated`.
  A source without an evidence identifier is a spec violation: if you cannot name
  what corroborated the value, the source is `uncorroborated`.
- `orcid_confidence` and `ror_confidence` are binary: `Confirmed` or `null`. There
  is no "probable" tier — unconfirmed possibilities live in `notes` only.
- `affiliation_type`:
  - `era-matched` — held during the record's operating span, from dated ORCID employment.
  - `current` — the person's current/most-recent affiliation (no era overlap found, or no dated history).
  - `as-deposited` — the affiliation string a publisher deposited with the paper in
    Crossref. This is affiliation-at-publication-date; it may or may not fall inside
    the operating span. Do not relabel it era-matched even if the publication date
    falls in the span — the label records the evidence type, not an inference.
- **`affiliation_type` does not apply to `affiliation_ror`.** A ROR ID identifies an
  organization, not a point in time. An era-matched affiliation and a current
  affiliation that name the same institution resolve to the same ROR ID. Never read
  a ROR ID as dated evidence, and never let a ROR match influence the
  `affiliation_type` label — the ROR describes the institution the affiliation
  already named, nothing more.
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
   consistent with the instrument, observatory/mission, or data provider
   institution?
3. If valid and corroborated → keep it; `orcid_origin: "finder"`, `orcid_source:`
   whatever corroborated it (`Crossref (paper DOI)` or `ORCID name-search
   (corroborated)`), `orcid_evidence:` that DOI or ORCID URL,
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
  `affiliation_origin: "finder"`, `affiliation_source: "ORCID employment"` (or
  whatever actually verified it), `affiliation_evidence:` that identifier.
- disagrees → put the era-matched value in `affiliation` (it is dated,
  evidence-backed), keep the finder's value in `notes` with an explicit
  "differs from finder value" flag for the reviewer.
- yields nothing → keep the finder's value with `affiliation_origin: "finder"`,
  `affiliation_source: "uncorroborated"`, `affiliation_evidence: null`, and
  `affiliation_type: "current"` or `"as-deposited"` per its origin if known, else
  note the type is unknown. Do not label it verified; nothing verified it.

**Pre-filled ROR:** validate the same way as an ORCID.
1. Check the form (`https://ror.org/` + 9 characters: `0` + 6 alphanumerics +
   2 check digits) and the ISO 7064 mod 97-10 checksum.
2. `GET https://api.ror.org/v2/organizations/<id>` and confirm the returned
   organization actually matches the resolved `affiliation` string (name, alias,
   or label; plus country/location if known).
3. If valid and matching → keep it; `ror_origin: "finder"`, `ror_source:`
   whatever confirmed it (`ROR affiliation-match (chosen)` or `ORCID
   disambiguated-organization`), `ror_evidence:` that ROR or ORCID URL,
   `ror_confidence: "Confirmed"`.
4. If the checksum fails, the ID does not resolve, or the organization does not
   match the affiliation → set `affiliation_ror` to null, record the finder's value
   and the failure in `notes`, and proceed to Step 4 as if the field were empty.
5. Whatever the finder pre-filled, the ROR must match the affiliation **this skill
   resolved**, not the one the finder had. If Step 3 replaced the affiliation with
   an era-matched value, a finder ROR that pointed at the old institution is now
   wrong — null it and re-resolve.

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
   the publisher tied that iD to that author on that paper. Emit
   `orcid_origin: "enricher"`, `orcid_source: "Crossref (paper DOI)"`,
   `orcid_evidence:` the DOI.

**Route A′ — Crossref author query beyond the evidence DOIs (same-instrument corroboration):**

Route A is limited to the DOIs the finder recorded as evidence. Those are often
book chapters, SPIE proceedings, or older journal records that deposit no iDs at
all — so a candidate with a perfectly good publisher-deposited ORCID on a
*different* paper gets nulled for a reason that has nothing to do with their
identity. This route recovers those cases without weakening the standard.

1. Use only when no evidence DOI carries an iD for the candidate.
2. Query Crossref by author name, restricted to the instrument, mission,
   observatory, or data provider domain (e.g. `query.author` plus
   `query.bibliographic` naming the instrument). Do not sweep the author's whole
   publication history looking for any iD.
3. Accept a deposit as **Confirmed** only if BOTH hold:
   - the deposited given name is **full-name compatible** with the candidate's
     known full name — initials-only deposits (`given: "C."`) never confirm, even
     when everything else matches; and
   - the paper is on the **same instrument, mission, or observatory** as the
     candidate's evidence, or is deposited under the data provider institution.
   A paper merely in the same field is not enough. "Space physics" is not a
   corroborating domain; "GOES-R SUVI" is.
4. Record the DOI in `orcid_evidence` and state in `notes` that it lies outside
   the finder's evidence list, naming it explicitly so a reviewer can check the
   inference you made. Set `orcid_origin: "enricher"`,
   `orcid_source: "Crossref (paper DOI)"`.
5. This route is **not optional when it applies.** If you use it for one
   candidate you must attempt it for every candidate whose evidence DOIs carry no
   iD. Applying it to some and not others produces a file where a null means
   "no iD exists" for one person and "I did not look as hard" for another, and
   nothing in the output distinguishes the two.

The same route supplies affiliations: when a Route A′ DOI deposits an affiliation
string for the confirmed author, it is usable as `affiliation_source: "Crossref
(paper DOI)"`, `affiliation_type: "as-deposited"`, with that DOI as
`affiliation_evidence`. The identity must be confirmed first — either by the
deposit itself or independently.

**Route B — ORCID name search (only with corroboration):**
1. `GET https://pub.orcid.org/v3.0/expanded-search/?q=family-name:<name>+AND+given-names:<name>`
   (header `Accept: application/json`).
2. A name search may return multiple people. NEVER accept a match on name alone.
3. Accept an iD only if the record itself corroborates identity: a listed work
   or dated employment consistent with the instrument, observatory/mission, or
   data provider institution. Emit `orcid_origin: "enricher"`,
   `orcid_source: "ORCID name-search (corroborated)"`, `orcid_evidence:` the
   ORCID URL.
4. If multiple plausible matches remain, or the only match cannot be
   corroborated, leave `orcid` null and describe the ambiguity in `notes`
   (including candidate iDs, so the reviewer can resolve it in one click).

### Step 3 — Resolve affiliation (era-matched, then current, then Crossref)

With a confirmed ORCID:
1. `GET https://pub.orcid.org/v3.0/<orcid-id>/employments` (header
   `Accept: application/json`).
2. **Era-matched (preferred):** select the employment whose date range overlaps
   the record's operating span, using the overlap rules below.
   `affiliation_source: "ORCID employment"`, `affiliation_evidence:` the ORCID
   URL, `affiliation_type: "era-matched"`.
3. **Current (fallback):** if no dated employment overlaps, use the
   current/most-recent affiliation. `affiliation_source: "ORCID
   employment"`, `affiliation_evidence:` the ORCID URL,
   `affiliation_type: "current"`.
   - **One undated employment** → it is usable, but it does not automatically
     win. Apply the evidence-strength rule below before recording it.
     `affiliation_type: "current"`.
   - **Several employments, all undated** → there is no "most recent" to pick.
     ORCID does not order employments meaningfully, so choosing among them is a
     guess dressed as a lookup. Do NOT pick one. Fall through to the Crossref
     fallback (step 4), which at least carries a publication date. If that also
     yields nothing, leave `affiliation` null and list every undated employment
     in `notes` so the reviewer can choose. State the situation explicitly —
     "N ORCID employments, none dated, no basis for selection" — because in the
     output it is indistinguishable from "no employment history at all", and the
     two call for different reviewer action.
   - **Some dated, some undated** → era-match against the dated ones only. If
     none overlaps, prefer the most recent dated entry over any undated one, and
     list the undated entries in `notes`.

Without a usable ORCID employment history (or without a confirmed ORCID at all,
when identity was confirmed some other way):
4. **Crossref fallback:** use the affiliation string deposited for that author on
   the paper, if any. `affiliation_source: "Crossref (paper DOI)"`,
   `affiliation_evidence:` the DOI, `affiliation_type: "as-deposited"`.
5. If nothing yields a value, leave `affiliation` null with `lookup_status`
   reflecting whether lookups completed.

**Evidence strength — dated beats undated, and this outranks source order.**
The route order above (ORCID employment before Crossref) assumes the employment
is dated. It is not a claim that ORCID always wins. When the only ORCID
employment is undated, compare it against the Crossref deposit on the merits:

| Evidence | Rank |
|---|---|
| Dated ORCID employment overlapping the span (`era-matched`) | 1 |
| Crossref deposit whose publication date falls inside the span (`as-deposited`) | 2 |
| Undated ORCID employment (`current`) | 3 |

An undated employment carries no date at all; an as-deposited affiliation is at
least pinned to a publication date you can check against the operating span. So
a bare undated `University of Colorado Boulder` does **not** displace a deposited
`Laboratory for Atmospheric and Space Physics, University of Colorado Boulder`
from a paper published inside the span — the deposit is both dated and more
specific. Record the deposit, and list the undated employment in `notes`.

Prefer the undated employment over a Crossref deposit only when the deposit falls
outside the operating span, or when the employment names an institution the
deposit does not.

**Choosing among several in-span deposits.** Rank 2 can have more than one member:
the same person may have several papers inside the span, each depositing a
different affiliation string. Prefer, in order:
1. the deposit that also carried the confirmed ORCID, if one did — the identity
   and the affiliation then rest on the same record;
2. the string that names the person's unit most specifically, provided it is
   well-formed;
3. the most recent deposit.

**Never silently correct a deposited string.** Publisher deposits contain typos —
a misplaced article, a misspelled institute, a truncated department. You have two
honest options and one dishonest one. You may record the string verbatim, typo
included, noting the error. You may prefer a different, well-formed in-span
deposit and note why the more specific one was passed over. You may NOT retype
the string with the error fixed: `affiliation` is a transcription of what the
evidence said, and an emended string is no longer that — it is your reconstruction
wearing a citation. Whichever you choose, name the rejected string and the reason
in `notes` so the reviewer can overrule you.

**This ranking applies identically whether or not the finder pre-filled the
field.** Step 1 governs *provenance* — whether `affiliation_origin` reads
`finder` or `enricher`, and whether you must flag a disagreement — not which
value wins. Two candidates with the same evidence must end with the same
affiliation; if one had a finder value and the other did not, that changes only
the `origin` label. A file where the finder's incidental coverage decides how
specific an affiliation is has smuggled bookkeeping back into the data, which is
exactly what the `*_origin` / `*_source` split exists to prevent.

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
- When the affiliation you select comes from an employment entry, carry that
  entry's ROR (if present) forward to Step 4 — you must not later resolve a ROR
  for a *different* employment than the one you chose.

### Step 4 — Resolve ROR for the affiliation

Run this only when `affiliation` is non-null. The ROR identifies the institution
named in `affiliation` — no affiliation, no ROR, no lookup attempted.

**Never let ROR resolvability influence which affiliation you chose.** If two
candidate affiliation strings are in play and one happens to resolve to a ROR
while the other does not, that is not a reason to prefer it. Step 3 is settled on
its own evidence before Step 4 runs. A string that resolves cleanly is not better
evidence about where someone worked — it is better formatted. Choosing on that
basis lets a formatting property masquerade as a factual one, and it is invisible
in the output because both fields end up populated and plausible. If you notice
that the affiliation you correctly selected leaves the ROR null, that is the right
outcome: record the null and note it.

**Route A — ORCID's own disambiguated organization (preferred; pre-corroborated):**
1. Re-read the employment entry you selected in Step 3. ORCID stores a
   `disambiguated-organization` object on employment entries:
   ```
   "disambiguated-organization": {
     "disambiguated-organization-identifier": "https://ror.org/02wcxbg22",
     "disambiguation-source": "ROR"
   }
   ```
2. If `disambiguation-source` is `ROR`, take the identifier as **Confirmed**.
   ORCID's registry integration already tied that employer to that ROR ID; this
   is the strongest route and costs no extra call. `ror_origin: "enricher"`,
   `ror_source: "ORCID disambiguated-organization"`, `ror_evidence:` the ORCID
   URL whose employment asserted it.
3. If `disambiguation-source` is something else (`GRID`, `RINGGOLD`, `LEI`,
   `FUNDREF`), do NOT treat it as a ROR. GRID IDs in particular map to ROR
   one-to-one for legacy records and are tempting to convert — do not convert them
   by hand. Fall through to Route B and confirm against the registry.
4. Only Route A applies when the affiliation came from ORCID employment. If the
   affiliation is `as-deposited` (Crossref) or a finder value, skip to Route B.

**Route B — ROR affiliation matching (for affiliation strings):**
1. `GET https://api.ror.org/v2/organizations?affiliation=<url-encoded affiliation string>`
   This is ROR's purpose-built endpoint for exactly this problem: resolving a raw
   institutional affiliation string (the kind publishers deposit, often with
   department prefixes and postal addresses) to a registry record. Prefer it over
   the plain `query=` search for any string longer than a bare institution name.
2. The response returns matches with a `score` (0–1), a `chosen` boolean, and a
   `matching_type` (`PHRASE`, `COMMON TERMS`, `FUZZY`, `HEURISTICS`, `ACRONYM`,
   `EXACT`), sorted by descending score.
3. Accept the match **only** if ROR set `chosen: true`. At most one result carries
   that flag and it is always listed first. `ror_origin: "enricher"`,
   `ror_source: "ROR affiliation-match (chosen)"`, `ror_evidence:` the returned
   ROR URL.
4. If no match is `chosen`, do NOT take the top-scoring match. Before leaving the
   field null, you MAY retry the match once on a **normalized form of the same
   string**, and only in this narrow case: the affiliation names a parent agency
   and one of its sub-units together (`National Oceanic and Atmospheric
   Administration - Space Weather Prediction Center`), and the agency prefix is
   pulling the parent and its siblings to the top. Strip the redundant agency
   prefix and re-match (`NOAA Space Weather Prediction Center`). Accept the result
   only if ROR sets `chosen: true` AND the returned organization is the sub-unit
   the original string named. Record in `notes` that the match came from a
   normalized string, quoting both forms. This is not rewriting the affiliation —
   `affiliation` keeps the deposited string; only the query is normalized.
   If the retry still yields nothing chosen, leave `affiliation_ror` null and list
   the top candidates with their scores and matching types in `notes`.
5. **Never select by `score`.** ROR explicitly advises against it, and `chosen`
   already encodes the discipline this skill wants: ROR sets it true only when a
   single result is a highly probable match, and sets it false on *every* result
   when several score highly, because that pattern means ambiguity. A high score
   with `chosen: false` is therefore evidence *against* the match, not weak
   evidence for it. Do not second-guess the flag in either direction.
6. `matching_type: "ACRONYM"` never yields `chosen: true` — ROR disabled that
   after acronym matching produced too many false positives. Acronyms collide
   badly in this domain ("MPS", "IAP", "NRL", "ROB"), so if an acronym-only
   affiliation returns nothing chosen, that is the correct result: leave null and
   note it. Do not hand-resolve the acronym yourself.

**Route C — plain ROR query (bare institution names only, with corroboration):**
1. `GET https://api.ror.org/v2/organizations?query=<url-encoded name>` when the
   affiliation is already a clean institution name with no address.
2. Accept a result only if it is unambiguous: exactly one plausible organization,
   whose name/alias/label matches the affiliation and whose country matches what
   you know from the ORCID employment, the Crossref affiliation string, or the
   data provider. Emit `ror_origin: "enricher"`,
   `ror_source: "ROR query (corroborated)"`, `ror_evidence:` the ROR URL.
3. Multiple plausible organizations → leave null, list them in `notes`.

**ROR-specific traps:**
- **Department strings.** Affiliations frequently name a department or lab that has
  no ROR record of its own ("Solar-Terrestrial Centre of Excellence, Royal
  Observatory of Belgium"). Resolve to the ROR of the **parent organization that
  the registry actually lists**, and note in `notes` that the affiliation named a
  sub-unit. Never invent a ROR for an unlisted sub-unit; never silently drop the
  sub-unit from the `affiliation` string itself — `affiliation` keeps what the
  evidence said, `affiliation_ror` points at what ROR lists.
- **Successor and renamed organizations.** ROR records carry status
  (`active`, `inactive`, `withdrawn`) and successor relationships. An era-matched
  affiliation from the 1990s may name an institution that has since merged or been
  renamed. Record the ROR of the organization **as named in the affiliation** —
  including an `inactive` record if that is what the affiliation names — and note
  the successor in `notes`. Do not silently substitute the successor's ROR; that
  would misrepresent where the person actually worked at the time.
- **Multi-affiliation strings.** Crossref sometimes deposits several institutions
  in one affiliation string. Resolve the ROR for the primary/first institution,
  and note the others. If you cannot tell which is primary, leave null and note it.
- Do not construct a ROR URL from a GRID ID, an ISNI, a Ringgold number, or an
  organization name. A ROR ID comes from the registry or it does not exist.

**Cross-candidate consistency check (run once, after all candidates).** Routes A
and B can resolve the *same* institution to different granularities: ORCID's
`disambiguated-organization` may assert a laboratory's own ROR while ROR's
`chosen` flag picks the parent university for the same laboratory named in a
deposited string. Both are correct by their own route, and neither should be
overridden — but a file that carries both without saying so looks like an error.

Before writing the file, group candidates by the institution their `affiliation`
names. Where two or more candidates at the same institution carry different
`affiliation_ror` values:
- Leave every value as its route produced it. Do NOT align them by picking one
  and rewriting the others; that would override either ORCID's own assertion or
  ROR's `chosen` flag, and the skill defers to both.
- Add a note on **each** affected candidate naming the other ID, the route that
  produced it, and the fact that the two are the same institution at different
  granularities.
- Say plainly that this is a curation-policy choice — parent organization vs.
  sub-unit — and that a reviewer wanting internal consistency must pick one.

The check costs nothing (it is local to the file you already assembled) and it
converts a silent inconsistency into a flagged decision. Without it, whether the
discrepancy gets noticed depends on whether the same institution happened to come
up twice by different routes.

---

## Tools / APIs

Prefer raw API calls (curl via Bash, if available) over summarized web fetches
for the three structured APIs — exact dates, author-array contents, and ROR match
scores/flags matter and must not be paraphrased away. Use WebFetch only for
ordinary web pages.

- **Crossref**: `https://api.crossref.org/works/<DOI>` — author lists with ORCIDs
  and affiliations as deposited by publishers. Include a `mailto:` contact in the
  `User-Agent` header (Crossref "polite pool"). Primary route for ORCID
  resolution because it anchors identity to a specific authorship.
- **ORCID public API** (`https://pub.orcid.org/v3.0/`, header
  `Accept: application/json`):
  - `/<orcid-id>/record` — full public record (works, employments) for corroboration.
  - `/<orcid-id>/employments` — dated employment history for era-matching, and the
    `disambiguated-organization` block that often carries a ROR ID directly.
  - `/expanded-search/?q=...` — name search (Route B only, with corroboration).
- **ROR API** (`https://api.ror.org/v2/`) — no key or registration required; be
  polite (the public API is rate-limited, roughly 2000 requests per 5 minutes;
  serialize calls rather than firing them in parallel).
  - `?affiliation=<string>` — affiliation-string matching, purpose-built by ROR and
    Crossref for exactly the messy strings publishers deposit. Returns `chosen`/
    `score`/`matching_type`. Select on `chosen`, never on `score`. Preferred for
    real-world affiliation strings.
  - `?query=<name>` — general search. For bare institution names.
  - `/organizations/<id>` — fetch a single record to validate a pre-filled ROR.
  - Registry access options (data dumps via Zenodo, the REST API, the search UI)
    are documented at `https://ror.org/registry/#accessing-the-registry`. This
    skill uses the REST API — per-candidate lookups are few, and the API always
    reflects the current registry, whereas a dump goes stale between releases.

Unlike the finder, this skill IS permitted to make dedicated per-candidate
lookups — that is its purpose. If an API call fails, retry once; on repeated
failure set `lookup_status: "partial-api-error"` and name the failed call in
`notes` rather than treating the absence of data as "could not confirm."

---

## Disambiguation

This skill is where same-name disambiguation comes due (the finder deferred it).
- Never accept an identity on name match alone.
- Corroborate against: the paper-DOI authorship, an ORCID work/employment
  consistent with the instrument, observatory/mission, or data provider
  institution, or an affiliation matching the data provider.
- The same rule governs institutions. Institution names collide (multiple
  "Institute of Atmospheric Physics"), abbreviate ambiguously, and change over
  time. Never accept a ROR on a name match alone — require ROR's own `chosen`
  flag, or corroboration by country/provider.
- When you cannot confirm, leave the field null and explain in `enrichment.notes`.
  Do not pick the "most likely" ORCID or the top-scoring ROR to avoid an empty
  field.

**Apply the same effort to every candidate.** Whatever routes you use, use them
for all candidates the gate lets through. If you widen the search for one person —
an off-evidence Crossref query, an extra page of name-search results, a check
against the provider's own documentation — you owe the same to everyone whose
earlier routes came up empty. Otherwise a `null` means "nothing exists" for one
candidate and "I stopped sooner" for another, and the file gives the reviewer no
way to tell which. Uneven effort is the one failure mode that the provenance
fields cannot record, which is why it has to be prevented rather than
documented.

---

## Human-Approval Gate

This skill produces an enriched candidate list for human review. It does not
write to any SPASE record, does not assign roles, and does not create Person
records. A human reviews the enriched candidates — paying particular attention to
`enrichment.notes` entries flagging ambiguity, finder/lookup discrepancies,
mid-span affiliation changes, sub-unit or successor ROR resolutions, and
unresolved ROR matches — and to any candidate with
`lookup_status: "skipped-unconfirmed-identity"` — before anything downstream
acts on them.