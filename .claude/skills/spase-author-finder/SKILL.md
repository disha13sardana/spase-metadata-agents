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
- `operating_span` — object `{ "start": <date>, "stop": <date or null> }` from the record's `OperatingSpan` (`stop: null` = still operating). Recorded once here so downstream agents (the affiliation enricher's era-matching) use the same dates this run used for the paper time-window and the CMAD expectation.
- `cmad` — object recording the CMAD search outcome:
  `{ "found": true|false, "expected": true|false, "url": <link or null>, "notes": <free text> }`.
  `expected` records whether a CMAD *should* exist (see source 2: operational + NASA-funded ⇒ expected). Record this object whether or not a CMAD was found, so reviewers know whether current-team evidence was available — and whether its absence is remarkable.
- `instrument_coverage` — object recording the instrument-discovery outcome (see source 3):
  `{ "spase_instruments": [<ResourceIDs found in SPASE>], "external_roster": [<instrument names from landing page / mission paper, or empty>], "missing_from_spase": [<instruments on the external roster with no SPASE record>], "notes": <how the roster was established> }`.
  This makes silent gaps visible: an instrument absent from SPASE is invisible to registry-based discovery, so the external roster is the ground truth and this object reports the difference.
- `pending_instrument_runs` — **Observatory records only** (omit or leave `[]` otherwise); the worklist of instruments this run could NOT fully resolve, for a dedicated per-instrument finder pass. Add an entry when an instrument's description paper could not be located, its paper-selection was uncertain, or the instrument has no SPASE record: `{ "instrument": <ResourceID or name>, "spase_record": <instrument ResourceID or null if unregistered>, "description_paper": <DOI/URL if one was seen, else null>, "reason": <"paper not located" | "paper-selection uncertain" | "no SPASE record" | ...>, "notes": <what was captured anyway, e.g. Contacts-derived PIs> }`. Instruments fully resolved here (Contacts roles + paper authors taken) need no entry.
- `candidates` — the array below
- `notes` — array of free-text judgment calls, ambiguities, dead ends

Each candidate object:
- `name` — person's name as found
- `status` — `"included"` (Strong/Medium evidence) or `"excluded"` (did not clear the bar)
- `confidence` — `"Strong"` or `"Medium"` if included; `null` if excluded
- `exclusion_reason` — string if `status` is `"excluded"`, otherwise `null` (e.g. `"acknowledgement-only mention"`, `"metadata submitter only"`, `"non-qualifying contact role only"`, `"dedication"`)
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
  "operating_span": { "start": "2010-01-06", "stop": null },
  "cmad": { "found": false, "expected": false, "url": null, "notes": "No CMAD located via designated repository, SDC site, or web search. PROBA2 is an ESA mission, not subject to the NASA senior-review CMAD requirement — absence is unremarkable. Proceeded with remaining sources." },
  "instrument_coverage": {
    "spase_instruments": ["spase://SMWG/Instrument/PROBA2/LYRA", "spase://SMWG/Instrument/PROBA2/SWAP"],
    "external_roster": ["LYRA", "SWAP", "DSLP", "TPMU"],
    "missing_from_spase": ["DSLP", "TPMU"],
    "notes": "Roster from PROBA2 mission site (science payload page). LYRA is the producing instrument for this record; DSLP/TPMU absence noted for curators but not pursued — irrelevant to this data product."
  },
  "pending_instrument_runs": [],
  "candidates": [
    {
      "name": "Marie Dominique",
      "status": "included",
      "confidence": "Strong",
      "exclusion_reason": null,
      "evidence": [
        { "source": "Lead author, non-alphabetized instrument paper (2013SoPh..286...21D)", "url": "https://doi.org/10.1007/s11207-013-0252-5", "strength": "Strong" },
        { "source": "LYRA Instrument record PI (qualifying role: PrincipalInvestigator)", "url": "https://spase-metadata.org/SMWG/Instrument/PROBA2/LYRA.html", "strength": "Medium" },
        { "source": "Record Contacts (GeneralContact — non-qualifying role; context only)", "url": "https://spase-metadata.org/ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H", "strength": "Low" }
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
    "Dammasch link is initials-inferred from product-page footer; downstream should verify identity and affiliation.",
    "Dominique's Strong confidence comes from lead authorship of the (non-alphabetized) instrument paper; her Instrument-record PI role corroborates at Medium. In the Flarelist record's own Contacts she appears only as GeneralContact (non-qualifying).",
    "Paper selection confident: 2013SoPh..286...21D matches title keywords, author count, and operating-span timing; SciX and Semantic Scholar agree."
  ]
}
```

Note: every `url` should be a real link encountered during the hunt, so it is clickable on GitHub and followable by the downstream agent. Use `null` rather than inventing a URL when none applies. (The `instrument_coverage` values above are illustrative of the format.)

---

## Qualifying Contact Roles

SPASE Contacts tables carry a `Role` for each person. **Only the following roles count as author-evidence** when reading any Contacts table (the record's own, or a sibling Instrument/Observatory record's):

- `Author`
- `CoInvestigator`
- `CoPI`
- `DeputyPI`
- `FormerPI`
- `MissionPrincipalInvestigator`
- `PrincipalInvestigator`
- `InstrumentLead`
- `InstrumentScientist`
- `ProgramScientist`
- `ProjectScientist`

Match role names tolerantly (case, hyphenation, spacing — e.g. `Co-Investigator` = `CoInvestigator`), but do not stretch semantics: a role not on this list does not qualify, however scientific it sounds.

A qualifying role is **Medium** evidence, not Strong: SPASE records may be outdated or incomplete, so a Contacts entry — even with the right role — should be checked against other sources (publication authorship, CMAD, provider pages). A qualifying-role contact who is also corroborated by an independent Strong source is Strong via that source.

**Non-qualifying roles** (e.g. `GeneralContact`, `TechnicalContact`, `MetadataContact`, `ArchiveSpecialist`, `HostContact`, `Publisher`, `DataProducer`, `Scientist`, `TeamLeader`, `ProjectManager`, `ProgramManager`, `User`) are **not author-evidence on their own**. Record the appearance as Low-strength context evidence — the person may still become an included candidate via other sources, and the reviewer should see that they also appear in Contacts. A person whose ONLY evidence is a non-qualifying contact role is `excluded` with reason `"non-qualifying contact role only"`.

Note that `FormerPI` qualifies deliberately: multiple generations of PI matter (original and current), and a FormerPI is authorship-relevant even though no longer active.

---

## Source-Priority Search Order

Search these sources in order, following links outward from the record — the order reflects how the hunt naturally unfolds from the record's own links, not evidence weight. **Evidence weight is set by the Evidence-Strength Hierarchy below, not by search position.**

### 1. The record itself
- Read the existing `Contacts` table, **applying the qualifying-role gate above**: a qualifying role is a Medium-strength candidate signal; a non-qualifying role is Low-strength context. SPASE records may be outdated or incomplete — always cross-check Contacts entries against other sources (publications, CMAD, provider pages) before trusting them.
- Read the `RevisionHistory` notes — they may name people, but distinguish carefully: a person named as the *metadata submitter* is NOT a data author (weak evidence at most).
- Read `PublicationInfo` and `InformationURL` if partially filled.
- Note the **operating span** (`OperatingSpan` / `StartDate`/`StopDate`) and record it in the output's `operating_span` field — it drives the paper time-window heuristic AND the CMAD expectation below, and the affiliation enricher's era-matching downstream.

### 2. CMAD — Calibration and Measurement Algorithms Document (top-priority when available)
A CMAD is a document that missions must submit to NASA HQ to receive continued funding. The people named on its **front page(s) are the current, correct team** — making a CMAD the most authoritative source for *current* authorship. Front-page CMAD names are **Strong** evidence. A CMAD outranks the record's own Contacts (Medium): when they disagree, the CMAD reflects the *current* team and the Contacts are likely outdated.

**Check the CMAD's date before treating it as current-team evidence.** A CMAD names the team *as of its revision date*. Senior-review-era CMADs are current-team evidence, as assumed above — but a CMAD written years before the operating span began (a pre-launch or design-phase document) names the *founding* team instead. Compare the CMAD's date to the operating span: if it substantially predates the span's start, treat its front-page names as founding-era evidence (still Strong, but not evidence of the *current* team) and say so in `cmad.notes` and the candidate's evidence description. When a CMAD and the record's Contacts disagree, the *more recent* source reflects the current team.

**When to expect a CMAD.** CMADs are a requirement for continued NASA funding of *operational* missions — and this applies regardless of launch date. A legacy mission launched decades ago that is still operating under NASA funding is still required to have a CMAD. Set the expectation from mission status:
- **Operational (no `StopDate`, or `StopDate` in the future) and NASA-funded** → a CMAD is *expected* to exist. Record `"expected": true` in the `cmad` object. If none is found after all three search strategies, record that explicitly (e.g. `"CMAD expected for operational NASA mission but not located"`) — this is a notable gap the reviewer should see, and worth one extra search pass before giving up.
- **Ended missions** → the mission may predate the CMAD requirement or no longer undergo senior review; absence is unremarkable. `"expected": false`.
- **Non-NASA missions** (e.g. ESA's PROBA2) → not subject to the NASA requirement; a CMAD may still exist but its absence is unremarkable. `"expected": false`.

Find a CMAD in this order; stop at the first that works:
- **(a) A designated CMAD repository, if one exists** (e.g. a Zenodo collection). Check this first when configured.
- **(b) The mission's data center / Science Data Center (SDC) site** — many active missions post CMADs there (e.g. the MMS SDC at `https://lasp.colorado.edu/mms/sdc/public/`).
- **(c) General web search** — `"<mission> CMAD"` or `"<mission> Calibration and Measurement Algorithms Document"`.

A CMAD is a strong-evidence *bonus when found*, never a hard requirement of this procedure. **If no CMAD is found, proceed with the remaining sources and record the outcome** (found/expected/notes in the `cmad` object). Do not fail or stall when a CMAD is missing — but do distinguish "absent and unremarkable" from "expected but not located."

### 3. Sibling SPASE records — and the instruments SPASE doesn't know about

**Caution: SPASE linkage is one-directional and possibly incomplete.** Data and Instrument records point *upward* (`InstrumentID` → Instrument; `ObservatoryID` → Observatory), but **Observatory records do not list their instruments** — and instruments that were never registered in SPASE are invisible to any registry-based search. Never treat the set of SPASE Instrument records as the full payload roster.

**Discovery, by record type being processed:**
- **Data record:** follow its `InstrumentID`(s) upward to the Instrument record(s), and from there `ObservatoryID` to the Observatory record. These are the directly relevant siblings.
- **Instrument record:** follow `ObservatoryID` upward to the Observatory record (mission-level contacts such as a Mission PI or Project Scientist live there).
- **Observatory record:** there is no downward link to follow — do a **reverse lookup**: find Instrument records whose `ObservatoryID` points back to this observatory. In practice, list the registry path `https://spase-metadata.org/SMWG/Instrument/<ObservatoryName>/` (instrument records are conventionally grouped under the observatory name), and/or search hpde.io for the observatory's ResourceID. Confirm each hit's `ObservatoryID` actually matches — path conventions are not guaranteed.

**Establish the true instrument roster from external ground truth**, then compare:
- Check the **observatory/mission landing page** (via the record's `InformationURL`, or web search) for the science-payload / instrument-suite listing.
- The **mission overview paper** also enumerates the payload.
- Record the comparison in the `instrument_coverage` object: instruments found in SPASE, the external roster, and any instruments **missing from SPASE**. A missing instrument is a metadata gap worth surfacing to curators even when it doesn't affect this run's candidates.
- **When an instrument relevant to the record being processed has no SPASE record** (e.g. processing an Observatory record whose key instrument is unregistered): its team can't be found via SPASE — pursue it through the provider's instrument pages and the instrument's description paper instead. Do not let a missing SPASE record silently drop a whole instrument team from an Observatory's candidate list.

**Relevance scoping, by record type:**
- For a *data record*, the producing instrument's team is what matters — do not sweep in the PIs of unrelated instruments on the same observatory (note them in `instrument_coverage` and move on).
- For an *Observatory record*, each instrument contributes its **leads only** — not its full author team — **across both PI generations**. "Lead" has a precise definition here (see (b) below): paper positions 1–3, plus every qualifying-role person in the Instrument record's Contacts. Instrument-team depth (4th/5th authors, co-authors, tail members) belongs to that Instrument record's own finder run, not to the observatory's list. For each payload instrument, harvest both of the following:

  **(a) From the Instrument record's Contacts — zero extra fetch.** Take every person with a qualifying role, not just the sitting PI: `PrincipalInvestigator` (current PI), `FormerPI` (founding/earlier PI — this is how the original generation is recovered for free), `CoPI`, `CoInvestigator`, `DeputyPI`, `InstrumentLead`, `InstrumentScientist`. All are Medium (see Qualifying Contact Roles). Do not stop at the first PI you find — read the whole Contacts table.

  **(b) From the instrument's description paper, when the Instrument record links one** (or it is otherwise readily identified). Always run the FULL author-order procedure first — backward-scan alphabetization detection, then classification — because position is meaningless until the list is classified. Then, **on an Observatory record, take positions 1–3 only** (or prefix positions 1–3 of a partially alphabetized list): these are the instrument's leads, and they are Strong-tier. **Do NOT take the instrument paper's 4th and 5th authors here** — unlike the mission overview paper, whose 4th–5th are Medium-tier candidates, an instrument paper's 4th–5th authors are instrument-team depth and belong to that Instrument record's own run.

  Do **not** shortcut to "take the lead author" either: between authors 1 and 2 the ordering can reflect politics rather than contribution, so the first three is the robust signal where a single lead is not. If a classified prefix is shorter than three (e.g. prefix = Lemen, Title), take exactly the prefix — never pad from the alphabetized tail.

  **This rule is symmetric and admits no exceptions.** Every instrument-paper author at position 1–3 is included at Strong; every author at position 4 or beyond is `excluded` with the reason `"instrument-team depth — belongs to the <instrument> Instrument-record run"`, regardless of whether they also look mission-level or catch your eye for another reason. If such a person genuinely belongs at observatory level, they will earn it through an *independent* source — a mission-overview position, an Observatory-record qualifying contact role, a CMAD front page — and that source, not intuition, is what includes them. Never include a 4th+ author while excluding a 3rd, and never invent a scoping rationale to keep or drop an individual.

  The two sources corroborate each other and jointly capture both generations: a founding PI typically appears as a paper-prefix author (Strong) *and* as `FormerPI` in Contacts (Medium), while the current PI appears in Contacts only. Where a paper cannot be located or its selection is uncertain, record the instrument in `pending_instrument_runs` for a dedicated per-instrument pass rather than guessing.

  **Worked example (PROBA2/SWAP, doi:10.1007/978-1-4614-8187-4_4).** Backward scan: sorted suffix of 11 from position 10, so prefix = positions 1–9 (Seaton, Berghmans, Nicula, Halain, De Groof, Thibert, Bloomfield, Raftery, Gallagher). On the **Observatory** record, take prefix positions 1–3 — Seaton, Berghmans, **Nicula** — all Strong. Halain (4), De Groof (5), and prefix positions 6–9 are excluded as instrument-team depth. De Groof is nevertheless an included candidate, but via an *independent* source: she is a named author on the PROBA2 mission overview paper and the ESA project scientist. That independent evidence is why she is in; her SWAP position 5 is not. On the **SWAP Instrument record's** own run, the full prefix weighting applies (1–3 Strong, 4–5 Medium) and Halain and De Groof are Medium there.

**Never name a person in prose and then drop them.** If you identify an instrument's founding or current PI/Co-PI from any source, they become a candidate (at the strength their evidence supports) or an `excluded` entry with a reason — never a name mentioned only in the `notes` array. An observed person who is neither asserted nor excluded is a silent loss of exactly the information this pipeline exists to capture.

**Using what's found:** apply the same qualifying-role gate to sibling records' Contacts tables — qualifying roles (PI, CoI, InstrumentLead, etc.) are Medium-strength evidence with the same caveat that the metadata may be outdated; non-qualifying roles are context only. A sibling record also validates candidates found elsewhere: a name appearing both here and in another source rises in confidence.

### 4. The data provider's website
- Follow `AccessURL` and `InformationURL` links to the provider's pages.
- Look for an explicit team/PI listing — and note the **instrument roster** for the `instrument_coverage` comparison (source 3) while there.
- **For derived products (event lists, catalogs):** check whether the product page names a *maintainer* or *compiler* distinct from the instrument PI — that person is a candidate too. Also note if the product derives from another source (e.g. cross-calibrated against external event reports), which may introduce additional contributors.
- Note: provider links in older records may be outdated and redirect. Follow redirects to the current site.

### 5. The description paper
- Find the record's description paper (see heuristic below — which paper that is depends on the record type). Publication authorship is **Strong** evidence *when the paper selection is confident*: a peer-reviewed author list is deliberate, static, and more trustworthy than possibly outdated SPASE metadata. Apply the author-order rules below to extract the right people, and the self-aware downgrade rule when selection is uncertain.

### 6. The SMWG Person registry
- For each candidate, check `https://spase-metadata.org/SMWG/Person/<First.Last>.html` for an existing record. If present, capture both the `spase://SMWG/Person/...` id and the clickable `.html` url. If absent, set both to `null`.

---

## Paper-Selection Heuristic

When searching the literature, target the **description paper** of the resource being processed, not a science-results paper that merely *uses* it. Which paper that is depends on the record type:
- **Instrument record or data record:** the *instrument's* description paper — for a data record, specifically the paper of the *producing* instrument, not the mission overview.
- **Observatory record:** the *mission/observatory* overview paper.

Everywhere below, "the description paper" means the paper matching the record type per this definition.

**Title keywords indicating a description paper:**
- "Instrument", "Observatory", "Telescope", "Overview", "Mission overview", "Observatory overview", "Telescope overview", "Description and overview", "Design", "In-Flight Performance", "Calibration"

**Author count:**
- Description papers are written by the whole team. A 1–2 author paper is almost certainly a science result, not the description-paper reference. Prefer papers with many authors.

**Observatory/instrument name:**
- The paper should name the observatory/instrument in its title or abstract.

**Citation count:**
- A heavily-cited description paper is more likely the correct reference. Prefer high-citation papers.
- If the paper you found seems wrong, check its reference list for the correct description paper.

**Time period (use the operating span to pick the right paper):**
- The description/overview paper usually appears close to the start of operations. Anchor on the operating span from the SPASE record:
  - For an Observatory: `Observatory/OperatingSpan/StartDate`.
  - For an Instrument: the instrument's operating span (note: instrument and observatory spans may differ slightly).
- Expect the description paper within roughly a **2–5 year window** around the operating-span start, not ~10 years later. A paper appearing a decade after operations began is more likely a later science or review paper, not the correct description-paper reference.
- **Fuzzy lower boundary:** a *design* or pre-flight/calibration paper may appear *before* operations begin. Treat earlier design-phase papers as valid description-paper candidates; only the far-later papers should be discounted.

**Self-aware downgrade rule (paper-selection confidence).** Because publication authorship is Strong evidence, a wrongly selected paper mints Strong candidates who may have nothing to do with the record — so the selection must earn its weight. Treat the selection as **uncertain** if any of these hold and cannot be resolved:
- SciX and Semantic Scholar point to different papers and the conflict cannot be settled;
- multiple candidate papers score similarly on the heuristics above;
- the best paper found fails one or more heuristic checks (timing window, author count, title keywords, instrument named);
- the paper was only found via general web search with no literature-index confirmation.

When selection is uncertain: **shift that paper's position-based evidence down one tier** — authors/prefix positions 1–3 drop from Strong to Medium; positions 4–5 drop from Medium to Low (excluded unless corroborated by another source) — and record the uncertainty and its reason in the JSON `notes`. When selection is confident, say so in `notes` too (one line — which checks passed), so the reviewer knows the Strong weight was earned rather than defaulted.

**Which authors to take from the paper (or any authored source — dataset, Zenodo record, report):**

First, **check the author list for alphabetization** — fully, partially, or not at all. In publications, author order very often consists of a short deliberate prefix (the lead author(s)) followed by everyone else **alphabetized by family name**. Checking only the first few names WILL misclassify these lists — the unsorted prefix masks the sorted tail. Detect from the END of the list:

1. **Normalize family names**: case- and diacritic-insensitive, handling "Family, Given" ordering and name particles (van, von, de, etc.) leniently.
2. **Walk backward from the last author** and find the longest suffix in which every adjacent pair is in sorted order by normalized family name.
3. **Classify by that suffix:**
   - Suffix of **five or more** names covering the **whole list** → *fully alphabetized*.
   - Suffix of **five or more** names with authors before it → *partially alphabetized*: the authors before the suffix are the deliberate prefix.
   - Suffix of **fewer than five** names → *not alphabetized*. A short sorted run proves nothing — 2–3 adjacent names in alphabetical order happen by chance (1-in-2 and 1-in-6); the ≥5 threshold is what makes intent plausible.
4. When detection is ambiguous (near-sorted lists, compound surnames), **err against awarding position-based evidence** and record the ambiguity: falsely inflating an alphabetically-placed author is worse than losing an ordering signal that other sources can recover.

**Worked example (SDO/AIA, Lemen et al. 2012, doi:10.1007/s11207-011-9776-8):** the author list begins "James R. Lemen, Alan M. Title, David J. Akin, Paul F. Boerner, Catherine Chou, Jerry F. Drake, Dexter W. Duncan, …" and continues sorted to the end. Lemen→Title is not in alphabetical order, but the backward scan finds a sorted suffix starting at Akin (Akin→Boerner→Chou→Drake→Duncan→…). Classification: **partially alphabetized**, prefix = Lemen, Title (2 authors). Take Lemen and Title ONLY (both within the first three, so both Strong-tier). Taking "the first three authors" without the backward scan would wrongly promote Akin — and "the first five" would add Boerner and Chou — all alphabetical accidents, not contribution order.

Then apply the matching case:

- **Not alphabetized** (backward scan found no qualifying sorted suffix): author order signals contribution — the first author did the most work and is the most important. Take up to the first five authors, **weighted by position: authors 1–3 are Strong-tier; authors 4 and 5 are Medium-tier** (position still supports them, but less decisively). Authors 6 and beyond get NO position-based evidence: Low, excluded unless corroborated by another source. Be aware that some instrument-paper authors may not appear on any other science paper, so they can be hard to corroborate elsewhere; that does not disqualify them when author order supports them.
- **Fully alphabetized:** order carries no information about contribution. Do not infer importance from position — the alphabetically-first author is NOT the lead. Only include an author if corroborated by another source (CMAD, record Contacts, instrument record, provider site).
- **Partially alphabetized (non-alphabetized prefix followed by an alphabetized tail):** the prefix authors were *deliberately placed first* — apply the same positional weighting as a non-alphabetized list, within the prefix only: **prefix positions 1–3 are Strong-tier; prefix positions 4 and 5 are Medium-tier**. **Prefix positions 6 and beyond get NO position-based evidence** — a long prefix does not make its 11th member a lead. Treat them exactly like alphabetized-tail members: Low, excluded unless corroborated by another source (the same rule applies to authors 6+ of a non-alphabetized list). **Take at most the prefix, however short**: a 1- or 2-author prefix means 1 or 2 Strong-tier authors — NEVER pad by pulling names from the alphabetized tail. The tail carries no contribution-order information: tail members remain valid *identity/participation* evidence but get no position-based strength; include them only with corroboration, as in the fully-alphabetized case.
- **Team/consortium name as the leading "author"** (e.g. first creator is "X Mission Team" followed by alphabetized individuals): the team name is not a person and generates no candidate — and it does NOT transfer a position boost to the alphabetically-first individual after it. Record the team name in the JSON `notes` (it may point to a team roster elsewhere) and let other sources do the shortlisting.

In all cases:
- Do NOT dump the full co-author list into the candidate set. Extract the lead/prefix authors (per the rules above) and any explicitly named instrument leads. On a large alphabetized list, "appears in the author list" is participation-level evidence only — corroborative, never sufficient for inclusion on its own.
- Structured **contributor roles survive alphabetization**: if the source separately names people with explicit roles (e.g. a Zenodo record's Contributors section listing an Editor or Project manager), those are deliberate role assignments and keep their normal evidence weight even when the creator list is alphabetized.
- **Record the detection in the JSON `notes`** so the reviewer knows why position was or wasn't used as evidence — e.g. "author list fully alphabetized (n=104); position not used", or "backward scan: sorted suffix of 43 detected starting at author 3; prefix = 2 (taken as strong-contribution)".

---

## Evidence-Strength Hierarchy

Classify every candidate by the strongest evidence found. **Only Strong and Medium evidence qualify a person as an included candidate.** Low evidence and below do not — but record those people as `excluded` with a reason so the evaluation trail is visible.

Rationale for the ordering: **trust publications over SPASE metadata.** A peer-reviewed author list is deliberate and static; a CMAD front page is a formal deliverable naming the current team. SPASE Contacts, by contrast, may be outdated or incomplete. Note the complementarity: the description paper captures the *original* team, the CMAD captures the *current* team — both Strong, covering both generations of contributors.

**Strong (include):**
- Named on a CMAD front page (current team — see source 2)
- One of the **first three authors** of a non-alphabetized description paper, **when paper selection is confident** (see the self-aware downgrade rule)
- One of the **first three prefix authors** of a partially alphabetized author list (same paper-selection condition)
- Named as PI on the data provider's official pages (instrument PI or mission PI, per the record type)

**Medium (include):**
- Named in the record's own Contacts **with a qualifying role** (see Qualifying Contact Roles) — corroborate against other sources; SPASE records may be outdated or incomplete
- *On an Observatory record:* every qualifying-role person in each instrument's Contacts — the current `PrincipalInvestigator`, any `FormerPI` (founding generation), `CoPI`, `CoInvestigator`, etc. Founding PIs commonly also appear as prefix authors of the instrument's paper, where they additionally earn Strong. See source 3 relevance scoping.
- Named **with a qualifying role** in a sibling Instrument/Observatory SPASE record's Contacts — same caveat
- The **4th or 5th author** (or 4th/5th prefix position) of the record's OWN description paper, when paper selection is confident. (On an Observatory record, this means the mission overview paper. An *instrument* paper's 4th/5th authors are NOT candidates on an Observatory run — see source 3 relevance scoping — but they are Medium on that Instrument record's own run.)
- One of the first three authors / prefix authors of a description paper whose **selection was uncertain** (downgrade rule applied — reason in `notes`; positions 4–5 drop to Low under the same rule)
- An author of an alphabetized description paper (or the alphabetized tail of a partially alphabetized list) who is corroborated by another source
- Named on the data provider's team page

**Low (exclude — record with reason, do not include):**
- Named in a Contacts table only with a **non-qualifying role** (e.g. GeneralContact, TechnicalContact, ArchiveSpecialist) and uncorroborated elsewhere
- Mentioned only in a paper's acknowledgements
- Named only in a funding statement
- Named only as the metadata submitter or curator in revision history
- A non-lead / uncorroborated co-author: an alphabetized-list author, an alphabetized-tail member, or **any author at position 6 or beyond** (including within a long non-alphabetized prefix) — position stops carrying evidence after the fifth author
- *On an Observatory record only:* an instrument paper's author at **position 4 or beyond** — instrument-team depth, deferred to that Instrument record's own run (exclusion reason: `"instrument-team depth — belongs to the <instrument> Instrument-record run"`)

**Exclude (record with reason):**
- Dedications and memorials
- Institutional thank-yous
- Mailing-list addresses

---

## Tools / APIs

- **ADS / SciXplorer (SciX)** — heliophysics-native literature index; use to find the description paper via the keyword + author-count + time-period heuristics.
- **Semantic Scholar API** (`https://www.semanticscholar.org/product/api`) — second literature source; use alongside SciX to find and cross-check the description paper and its author list. Cross-referencing the two reduces the chance of selecting the wrong paper — and agreement between them is a key input to the paper-selection confidence check.
- **Crossref API** (`https://api.crossref.org/works/<DOI>`) — given a paper DOI, returns authors, affiliations, and ORCIDs where registered. When you fetch a paper this way, opportunistically capture affiliation/ORCID for candidates (per the schema rules).
- **SMWG Person registry** (`https://spase-metadata.org/SMWG/Person/`) — check for existing Person records; capture both the `spase://` ID and the clickable `.html` URL.
- **SPASE registry browsing** (`https://spase-metadata.org/SMWG/Instrument/<ObservatoryName>/`, hpde.io search) — reverse lookup of an observatory's Instrument records (source 3). Verify each hit's `ObservatoryID`.

(ORCID and affiliation are captured opportunistically only. A dedicated per-candidate ORCID lookup is out of scope for this skill and belongs downstream.)

---

## Future Refinement (not implemented here)

If two candidates share a name and cannot be told apart from the sources already fetched, a targeted ORCID/affiliation lookup may be needed to disambiguate. Record the ambiguity in the JSON `notes` array for now; do not build the disambiguation lookup into this skill yet.

---

## Human-Approval Gate

This skill produces a JSON candidate list for human review. It does not write to any SPASE record and does not decide roles. A human reviews the candidates before anything downstream acts on them.
