---
name: spase-author-finder
description: >
  Procedure for finding candidate authors/contributors for an existing SPASE
  record (e.g. an Observatory, Instrument, or data record). Produces a JSON
  candidate list (names, evidence with source links, confidence, Person-record
  link, ORCID, affiliation, activity dates) for human review. This skill ONLY
  finds candidate people — it does NOT assign SPASE roles, format
  PublicationInfo, or build the Contacts table. Role assignment is a separate
  downstream agent. Use when a SPASE record is missing or incomplete on author
  information and the task is to identify who plausibly belongs.
user-invocable: false
---

# SPASE Author Finder

This skill finds the **people** who plausibly belong in a SPASE record's authorship (the record may be an Observatory, Instrument, or data record), and produces a JSON candidate list for a human to review.

**Scope — read this first.** This skill's only job is to *find candidates*. It does NOT:
- assign SPASE roles (PI, CoI, FormerPI, etc.) — that is a separate downstream agent
- format `PublicationInfo.Authors`
- build the `Contacts` table
- create Person records

Produce the candidate list (JSON) and stop.

**Critical principle: do not fabricate or guess people.** Every person in the output must trace to a real source. Only Strong/Medium evidence makes someone an included candidate; weaker mentions are recorded as excluded with a reason, never invented and never promoted. When in doubt, exclude with a reason rather than including on thin evidence.

---

## Input

A single SPASE record (its ResourceID, URL, or XML). This is currently focused on Observatory and Instrument records, but the procedure is general and applies to any SPASE record type. The agent reads this record and follows its internal links outward to find everything else. No other input is provided; do not assume the human has pre-supplied provider URLs or paper references.

---

## Output

A single JSON file for human review and downstream consumption. JSON is chosen so the output can be fed directly into the downstream role-assignment agent, renders readably on GitHub, and keeps each source link attached to the claim it supports.

**Save the output AND return it inline.**
- Save as JSON to: `spase_records/<record-name>/author_candidates.json`, where `<record-name>` is a short slug derived from the ResourceID (e.g. `PROBA2_LYRA_Flarelist`). Create the directory if it does not exist.
- Also return a brief inline summary in your response so the user sees the top candidates immediately.
- (Saving requires the `Write` tool — confirm the agent has it.)

### Schema

One flat `candidates` array. Every person evaluated appears in it, distinguished by the `status` field. **Included candidates are Strong or Medium confidence only** — do not include Low-confidence people as candidates. People who were evaluated but did not clear the bar (acknowledgement-only, submitter-only, dedications, etc.) appear with `status: "excluded"` and a reason, so the reviewer still sees who was considered and rejected. Do not silently drop anyone you evaluated.

Each candidate object:
- `name` — person's name as found
- `status` — `"included"` (Strong/Medium evidence) or `"excluded"` (did not clear the bar)
- `confidence` — `"Strong"` or `"Medium"` if included; `null` if excluded
- `exclusion_reason` — string if `status` is `"excluded"`, otherwise `null` (e.g. `"acknowledgement-only mention"`, `"metadata submitter only"`, `"dedication"`)
- `evidence` — array of objects, each `{ "source": <description>, "url": <clickable link or null>, "strength": "Strong"|"Medium"|"Low" }`. Attach the URL to the source it came from; use `null` if no URL applies (e.g. a printed paper acknowledgement).
- `person_record` — object `{ "id": <spase://SMWG/Person/... or null>, "url": <clickable https link or null> }`. The `id` is the `spase://` form that goes into the actual record; the `url` is the clickable `https://spase-metadata.org/SMWG/Person/<First.Last>.html` form for human review on GitHub. Both `null` if no Person record exists. Do not draft one.
- `orcid` — ORCID string if it surfaced in a fetched source, otherwise `null` (no dedicated lookup)
- `affiliation` — string if it surfaced, otherwise `null`
- `activity_dates` — string if it surfaced, otherwise `null` (the person's window of involvement, recorded for the downstream role agent; never used to include/exclude here)

### Example (from the PROBA2 LYRA Flarelist record)

```json
{
  "record": "spase://ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H",
  "date": "2026-06-18",
  "candidates": [
    {
      "name": "Marie Dominique",
      "status": "included",
      "confidence": "Strong",
      "exclusion_reason": null,
      "evidence": [
        { "source": "Record Contacts (GeneralContact)", "url": "https://spase-metadata.org/ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H", "strength": "Strong" },
        { "source": "LYRA Instrument record PI", "url": "https://spase-metadata.org/SMWG/Instrument/PROBA2/LYRA.html", "strength": "Strong" },
        { "source": "Lead author, instrument paper (2013SoPh..286...21D)", "url": "https://doi.org/10.1007/s11207-013-0252-5", "strength": "Medium" }
      ],
      "person_record": { "id": "spase://SMWG/Person/Marie.Dominique", "url": "https://spase-metadata.org/SMWG/Person/Marie.Dominique.html" },
      "orcid": null,
      "affiliation": "Royal Observatory of Belgium",
      "activity_dates": null
    },
    {
      "name": "Ingolf E. Dammasch",
      "status": "included",
      "confidence": "Medium",
      "exclusion_reason": null,
      "evidence": [
        { "source": "Flarelist product-page footer credits compiler 'IED'", "url": "https://proba2.sidc.be/lyra/data/Flarelist/Flarelist.html", "strength": "Medium" },
        { "source": "Matches co-author 'I. E. Dammasch' on instrument paper (initials-inferred — verify downstream)", "url": "https://doi.org/10.1007/s11207-013-0252-5", "strength": "Low" }
      ],
      "person_record": { "id": null, "url": null },
      "orcid": null,
      "affiliation": null,
      "activity_dates": null
    },
    {
      "name": "Lee Frost Bargatze",
      "status": "excluded",
      "confidence": null,
      "exclusion_reason": "metadata curation role (MetadataContact / RevisionHistory reviewer), not a data author",
      "evidence": [
        { "source": "Record Contacts (MetadataContact); RevisionHistory reviewer 'LFB'", "url": "https://spase-metadata.org/ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H", "strength": "Low" }
      ],
      "person_record": { "id": "spase://SMWG/Person/Lee.Frost.Bargatze", "url": "https://spase-metadata.org/SMWG/Person/Lee.Frost.Bargatze.html" },
      "orcid": null,
      "affiliation": "UCLA",
      "activity_dates": null
    },
    {
      "name": "Melanie Heil",
      "status": "excluded",
      "confidence": null,
      "exclusion_reason": "metadata submitter only (2022-01-28), not a data author",
      "evidence": [
        { "source": "RevisionHistory metadata submitter", "url": "https://spase-metadata.org/ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H", "strength": "Low" }
      ],
      "person_record": { "id": null, "url": null },
      "orcid": null,
      "affiliation": "ESA",
      "activity_dates": null
    },
    {
      "name": "Don McMullin",
      "status": "excluded",
      "confidence": null,
      "exclusion_reason": "acknowledgement-only mention ('special thanks') in instrument paper",
      "evidence": [
        { "source": "Instrument paper acknowledgements", "url": "https://doi.org/10.1007/s11207-013-0252-5", "strength": "Low" }
      ],
      "person_record": { "id": "spase://SMWG/Person/Don.McMullin", "url": "https://spase-metadata.org/SMWG/Person/Don.McMullin.html" },
      "orcid": null,
      "affiliation": null,
      "activity_dates": null
    },
    {
      "name": "Pierre Cugnon",
      "status": "excluded",
      "confidence": null,
      "exclusion_reason": "dedication/memorial only — not authorship evidence",
      "evidence": [
        { "source": "Dedication in instrument paper", "url": "https://doi.org/10.1007/s11207-013-0252-5", "strength": "Low" }
      ],
      "person_record": { "id": null, "url": null },
      "orcid": null,
      "affiliation": null,
      "activity_dates": null
    }
  ],
  "notes": [
    "Long-tail instrument-paper co-authors (Hochedez, Schmutz, Shapiro, Kretzschmar, Zhukov, Gillotay, Stockman, BenMoussa) not listed individually — co-authorship alone is below the inclusion bar unless corroborated by another source.",
    "Dammasch link is initials-inferred from product-page footer; downstream should verify identity and affiliation."
  ]
}
```

Note: every `url` should be a real link encountered during the hunt, so it is clickable on GitHub and followable by the downstream agent. Use `null` rather than inventing a URL when none applies.

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
- For each candidate, check `https://spase-metadata.org/SMWG/Person/<First.Last>.html` for an existing record. If present, capture both the `spase://SMWG/Person/...` id and the clickable `.html` url. If absent, set both to `null`.

---

## Paper-Selection Heuristic

When searching the literature (step 4), target the **instrument/mission description paper**, not a science-results paper that merely *uses* the instrument.

**Title keywords indicating a description paper:**
- "Instrument", "Observatory", "Telescope", "Overview", "Mission overview", "Observatory overview", "Telescope overview", "Description and overview", "Design", "In-Flight Performance", "Calibration"

**Author count:**
- Description papers are written by the whole team. A 1–2 author paper is almost certainly a science result, not the instrument reference. Prefer papers with many authors.

**Observatory/instrument name:**
- The paper should name the observatory/instrument in its title or abstract.

**Time period (use the operating span to pick the right paper):**
- The description/overview paper usually appears close to the start of operations. Anchor on the operating span from the SPASE record:
  - For an Observatory: `Observatory/OperatingSpan/StartDate`.
  - For an Instrument: the instrument's operating span (note: instrument and observatory spans may differ slightly).
- Expect the description paper within roughly a **2–5 year window** around the operating-span start, not ~10 years later. A paper appearing a decade after operations began is more likely a later science or review paper, not the instrument reference.
- **Fuzzy lower boundary:** a *design* or pre-flight/calibration paper may appear *before* operations begin. Treat earlier design-phase papers as valid description-paper candidates; only the far-later papers should be discounted.

**Keep two uses separate:**
- Use the many-authors signal ONLY to *select the right paper*.
- Do NOT dump the paper's full co-author list into the candidate list. Extract the PI / lead author and any explicitly named instrument leads. Co-authorship alone is below the inclusion bar; treat the long tail of co-authors as background (note them), not as included candidates, unless another source corroborates them.

---

## Evidence-Strength Hierarchy

Classify every candidate by the strongest evidence found. **Only Strong and Medium evidence qualify a person as an included candidate.** Low evidence and below do not — but record those people as `excluded` with a reason so the evaluation trail is visible.

**Strong (include):**
- Named in the record's own Contacts
- Named as PI/CoI in the Instrument SPASE record
- Named as instrument PI on the data provider's official pages

**Medium (include):**
- Lead or named author of the instrument description paper
- Named on the data provider's team page

**Low (exclude — record with reason, do not include):**
- Mentioned only in a paper's acknowledgements
- Named only in a funding statement
- Named only as the metadata submitter or curator in revision history
- Co-author (non-lead) of the instrument paper with no other corroboration

**Exclude (record with reason):**
- Dedications and memorials
- Institutional thank-yous
- Mailing-list addresses

---

## Tools / APIs

- **ADS / SciXplorer (SciX)** — heliophysics-native literature index; use to find the instrument description paper via the keyword + author-count + time-period heuristics.
- **Semantic Scholar API** (`https://www.semanticscholar.org/product/api`) — second literature source; use alongside SciX to find and cross-check the instrument/description paper and its author list. Cross-referencing the two reduces the chance of selecting the wrong paper.
- **Crossref API** (`https://api.crossref.org/works/<DOI>`) — given a paper DOI, returns authors, affiliations, and ORCIDs where registered. When you fetch a paper this way, opportunistically capture affiliation/ORCID for candidates (per the schema rules).
- **SMWG Person registry** (`https://spase-metadata.org/SMWG/Person/`) — check for existing Person records; capture both the `spase://` ID and the clickable `.html` URL.

(ORCID and affiliation are captured opportunistically only. A dedicated per-candidate ORCID lookup is out of scope for this skill and belongs downstream.)

---

## Future Refinement (not implemented here)

If two candidates share a name and cannot be told apart from the sources already fetched, a targeted ORCID/affiliation lookup may be needed to disambiguate. Record the ambiguity in the JSON `notes` array for now; do not build the disambiguation lookup into this skill yet.

---

## Human-Approval Gate

This skill produces a JSON candidate list for human review. It does not write to any SPASE record and does not decide roles. A human reviews the candidates before anything downstream acts on them.