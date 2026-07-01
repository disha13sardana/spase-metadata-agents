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

Top-level fields:
- `record` — the ResourceID of the SPASE record processed
- `date` — date of the run
- `cmad` — object recording the CMAD search outcome: `{ "found": true|false, "url": <link or null>, "notes": <e.g. how it was found, or why not> }`. Record this whether or not a CMAD was found, so reviewers know whether current-team evidence was available.
- `candidates` — the array below
- `notes` — array of free-text judgment calls, ambiguities, dead ends

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
  "cmad": { "found": false, "url": null, "notes": "No CMAD located for PROBA2/LYRA via designated repository, SDC site, or web search; proceeded with remaining sources." },
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
- Read the existing `Contacts` table — anyone already listed is a strong candidate. (Note: existing Contacts can be stale; cross-check against a CMAD when one is available — see below.)
- Read the `RevisionHistory` notes — they may name people, but distinguish carefully: a person named as the *metadata submitter* is NOT a data author (weak evidence at most).
- Read `PublicationInfo` and `InformationURL` if partially filled.

### 2. CMAD — Calibration and Measurement Algorithms Document (top-priority when available)
A CMAD is a document that active missions are required to submit to NASA HQ for funding extensions. The people named on its **front page(s) are the current, correct team** — making a CMAD one of the most authoritative sources for *current* authorship. Front-page CMAD names are **Strong** evidence, ranked alongside the record's own Contacts. When a CMAD and the record's existing Contacts disagree, the CMAD reflects the *current* team.

Find a CMAD in this order; stop at the first that works:
- **(a) A designated CMAD repository, if one exists** (e.g. a Zenodo collection). Check this first when configured.
- **(b) The mission's data center / Science Data Center (SDC) site** — many active missions post CMADs there (e.g. the MMS SDC at `https://lasp.colorado.edu/mms/sdc/public/`).
- **(c) General web search** — `"<mission> CMAD"` or `"<mission> Calibration and Measurement Algorithms Document"`.

**CMADs are not universally available** — older and legacy missions often have none, and many are scattered across the web or in personal folders. A CMAD is a strong-evidence *bonus when found*, never a requirement. **If no CMAD is found, proceed with the remaining sources and record its absence** (see the `cmad` field in the output schema). Do not fail or stall when a CMAD is missing.

### 3. Sibling SPASE records
- Follow `InstrumentIDs` to the **Instrument record**. Instrument records usually carry a full Contacts table (PI, CoIs). People there are strong candidates.
- The Instrument record also validates candidates found elsewhere: a name appearing both here and in another source rises in confidence.

### 4. The data provider's website
- Follow `AccessURL` and `InformationURL` links to the provider's pages.
- Look for an explicit team/PI listing.
- **For derived products (event lists, catalogs):** check whether the product page names a *maintainer* or *compiler* distinct from the instrument PI — that person is a candidate too. Also note if the product derives from another source (e.g. cross-calibrated against external event reports), which may introduce additional contributors.
- Note: provider links in older records may be stale and redirect. Follow redirects to the current site.

### 5. The instrument description paper
- Find the instrument/mission description paper (see heuristic below) and use its PI identification and author list as *medium* evidence.

### 6. The SMWG Person registry
- For each candidate, check `https://spase-metadata.org/SMWG/Person/<First.Last>.html` for an existing record. If present, capture both the `spase://SMWG/Person/...` id and the clickable `.html` url. If absent, set both to `null`.

---

## Paper-Selection Heuristic

When searching the literature, target the **instrument/mission description paper**, not a science-results paper that merely *uses* the instrument.

**Title keywords indicating a description paper:**
- "Instrument", "Observatory", "Telescope", "Overview", "Mission overview", "Observatory overview", "Telescope overview", "Description and overview", "Design", "In-Flight Performance", "Calibration"

**Author count:**
- Description papers are written by the whole team. A 1–2 author paper is almost certainly a science result, not the instrument reference. Prefer papers with many authors.

**Observatory/instrument name:**
- The paper should name the observatory/instrument in its title or abstract.

**Citation count:**
- A heavily-cited mission/instrument paper is more likely the correct reference. Prefer high-citation papers.
- If the paper you found seems wrong, check its reference list for the correct instrument paper.

**Time period (use the operating span to pick the right paper):**
- The description/overview paper usually appears close to the start of operations. Anchor on the operating span from the SPASE record:
  - For an Observatory: `Observatory/OperatingSpan/StartDate`.
  - For an Instrument: the instrument's operating span (note: instrument and observatory spans may differ slightly).
- Expect the description paper within roughly a **2–5 year window** around the operating-span start, not ~10 years later. A paper appearing a decade after operations began is more likely a later science or review paper, not the instrument reference.
- **Fuzzy lower boundary:** a *design* or pre-flight/calibration paper may appear *before* operations begin. Treat earlier design-phase papers as valid description-paper candidates; only the far-later papers should be discounted.

**Which authors to take from the paper:**
- **If the author list is NOT alphabetized:** author order signals contribution — the first author did the most work and is the most important. Take the **first 3–5 authors**. Be aware that some instrument-paper authors may not appear on any other science paper, so they can be hard to corroborate elsewhere; that does not disqualify them when author order supports them.
- **If the author list IS alphabetized:** order carries no information about contribution. Do not infer importance from position. Only include an author if corroborated by another source (CMAD, record Contacts, instrument record, provider site).
- In both cases: do NOT dump the full co-author list into the candidate set. Extract the lead/first authors (per the rules above) and any explicitly named instrument leads.

---

## Evidence-Strength Hierarchy

Classify every candidate by the strongest evidence found. **Only Strong and Medium evidence qualify a person as an included candidate.** Low evidence and below do not — but record those people as `excluded` with a reason so the evaluation trail is visible.

**Strong (include):**
- Named on a CMAD front page (current team — see source 2)
- Named in the record's own Contacts
- Named as PI/CoI in the Instrument SPASE record
- Named as instrument PI on the data provider's official pages

**Medium (include):**
- A first 3–5 author of a non-alphabetized instrument description paper
- An author of an alphabetized instrument paper who is corroborated by another source
- Named on the data provider's team page

**Low (exclude — record with reason, do not include):**
- Mentioned only in a paper's acknowledgements
- Named only in a funding statement
- Named only as the metadata submitter or curator in revision history
- A non-lead / uncorroborated co-author (especially from an alphabetized author list)

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