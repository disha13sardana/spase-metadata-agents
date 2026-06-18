---
name: spase-author-finder
description: >
  Procedure for finding candidate authors/contributors for an existing SPASE
  NumericalData record. Produces a candidate table (names, evidence, confidence,
  Person-record link, ORCID, affiliation, active period) for human review. This
  skill ONLY finds candidate people — it does NOT assign SPASE roles, format
  PublicationInfo, or build the Contacts table. Role assignment is a separate
  downstream agent. Use when a SPASE record is missing or incomplete on author
  information and the task is to identify who plausibly belongs.
user-invocable: false
---

# SPASE Author Finder

This skill finds the **people** who plausibly belong in a SPASE NumericalData record's authorship, and produces a candidate table for a human to review.

**Scope — read this first.** This skill's only job is to *find candidates*. It does NOT:
- assign SPASE roles (PI, CoI, FormerPI, etc.) — that is a separate downstream agent
- format `PublicationInfo.Authors`
- build the `Contacts` table
- create Person records

Produce the candidate table and stop.

**Critical principle: do not fabricate or guess people.** Every candidate in the table must trace to a real source. When evidence is weak, include the person but mark them low-confidence — never invent names, and never promote a weakly-supported name to high confidence.

---

## Input

A single SPASE NumericalData record (its ResourceID, URL, or XML). The agent reads this record and follows its internal links outward to find everything else. No other input is provided; do not assume the human has pre-supplied provider URLs or paper references.

---

## Output

A candidate table for human review. Include **everyone considered**, including people who were evaluated and dropped, so the reviewer sees the full evaluated set and why some are low-confidence.

**Save the output to a file AND return it inline.**
- Save as markdown to: `spase_records/<record-name>/author_candidates.md`, where `<record-name>` is a short slug derived from the ResourceID (e.g. `PROBA2_LYRA_Flarelist`). Create the directory if it does not exist.
- Also return the same table inline in your response so the user sees it immediately.
- (Saving requires the `Write` tool — confirm the agent has it.)

```markdown
# SPASE Author Finder — Candidate List

**Record:** [ResourceID]
**Date:** [Date]

| Candidate | Evidence (source) | Confidence | Person Record | ORCID | Affiliation | Active Period |
|---|---|---|---|---|---|---|

## Considered and excluded
- [name] — [reason, e.g. "acknowledgement-only mention", "dedication"]

## Notes
- [judgment calls, ambiguities, dead ends]
```

**Every person evaluated must appear somewhere** — either as a row in the candidate table (any confidence level, including Low) or under "Considered and excluded" with a reason. Do not silently drop a name you evaluated. Acknowledgement-only and dedication mentions go under "Considered and excluded," not omitted entirely.

Column rules:
- **Candidate** — person's name as found.
- **Evidence (source)** — where they were found (e.g. "record Contacts", "LYRA Instrument record", "instrument paper author list", "acknowledgements only").
- **Confidence** — Strong / Medium / Low (per the hierarchy below). Low-confidence/excluded candidates stay in the table with the reason in the Evidence column.
- **Person Record** — if an SMWG Person record exists, the `spase://SMWG/Person/...` link. If not, "No". Do not draft a record.
- **ORCID** — record only if it already appeared in a source you fetched (paper metadata, Person record). Otherwise leave blank. Do not make a dedicated lookup.
- **Affiliation** — same rule as ORCID: opportunistic only.
- **Active Period** — when the person was active with the instrument/mission, if it surfaced. Recorded for the downstream role agent; do NOT use it to include or exclude anyone here.

---

## Source-Priority Search Order

Search these sources in order, following links outward from the record. Earlier sources are more authoritative for *this specific data product*; later sources establish the broader instrument/mission team.

### 1. The record itself
- Read the existing `Contacts` table — anyone already listed is a strong candidate.
- Read the `RevisionHistory` notes — they may name people, but distinguish carefully: a person named as the *metadata submitter* is NOT a data author (weak evidence at most).
- Read `PublicationInfo` and `InformationURL` if partially filled.

### 2. Sibling SPASE records (highest-yield single source)
- Follow `InstrumentIDs` to the **Instrument record**. Instrument records usually carry a full Contacts table (PI, CoIs). People there are strong candidates.
- The Instrument record also validates candidates found elsewhere: a name appearing both here and in another source rises in confidence.

### 3. The data provider's website
- Follow `AccessURL` and `InformationURL` links to the provider's pages.
- Look for an explicit team/PI listing.
- **For derived products (event lists, catalogs):** check whether the product page names a *maintainer* or *compiler* distinct from the instrument PI — that person is a candidate too. Also note if the product derives from another source (e.g. cross-calibrated against external event reports), which may introduce additional contributors.
- Note: provider links in older records may be stale and redirect. Follow redirects to the current site.

### 4. The instrument description paper
- Find the instrument/mission description paper (see heuristic below) and use its PI identification and author list as *medium* evidence.

### 5. The SMWG Person registry
- For each candidate, check `https://spase-metadata.org/SMWG/Person/<First.Last>.html` for an existing record. Record the link if present, "No" if absent.

---

## Paper-Selection Heuristic

When searching the literature (step 4), target the **instrument/mission description paper**, not a science-results paper that merely *uses* the instrument.

**Title keywords indicating a description paper:**
- "Instrument", "Overview", "Mission overview", "Description and overview", "Design", "In-Flight Performance", "Calibration"

**Author count:**
- Description papers are written by the whole team. A 1–2 author paper is almost certainly a science result, not the instrument reference. Prefer papers with many authors.

**Observatory/instrument name:**
- The paper should name the observatory/instrument in its title or abstract.

**Keep two uses separate:**
- Use the many-authors signal ONLY to *select the right paper*.
- Do NOT dump the paper's full co-author list into the candidate table. Extract the PI / lead author and any explicitly named instrument leads. Treat the long tail of co-authors as background, not candidates, unless another source corroborates them.

---

## Evidence-Strength Hierarchy

Classify every candidate by the strongest evidence found. All candidates go in the table; the hierarchy sets their confidence, not their inclusion.

**Strong:**
- Named in the record's own Contacts
- Named as PI/CoI in the Instrument SPASE record
- Named as instrument PI on the data provider's official pages

**Medium:**
- Lead or named author of the instrument description paper
- Named on the data provider's team page

**Low (include, but mark clearly — do not promote):**
- Mentioned only in a paper's acknowledgements
- Named only in a funding statement
- Named only as the metadata submitter in revision history

**Exclude from candidacy (record in Notes with reason, not as a candidate):**
- Dedications and memorials
- Institutional thank-yous
- Mailing-list addresses

---

## Tools / APIs

- **ADS / SciXplorer (SciX)** — heliophysics-native literature index; use to find the instrument description paper via the keyword + author-count heuristic.
- **Crossref API** (`https://api.crossref.org/works/<DOI>`) — given a paper DOI, returns authors, affiliations, and ORCIDs where registered. When you fetch a paper this way, opportunistically capture affiliation/ORCID for candidates (per the column rules).
- **SMWG Person registry** (`https://spase-metadata.org/SMWG/Person/`) — check for existing Person records.

(ORCID and affiliation are captured opportunistically only. A dedicated per-candidate ORCID lookup is out of scope for this skill and belongs downstream.)

---

## Future Refinement (not implemented here)

If two candidates share a name and cannot be told apart from the sources already fetched, a targeted ORCID/affiliation lookup may be needed to disambiguate. Note the ambiguity in the table's Notes for now; do not build the disambiguation lookup into this skill yet.

---

## Human-Approval Gate

This skill produces a candidate list for human review. It does not write to any SPASE record and does not decide roles. A human reviews the candidates before anything downstream acts on them.