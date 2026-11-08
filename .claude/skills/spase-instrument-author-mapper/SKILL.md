---
name: spase-instrument-author-mapper
description: >
  Procedure for completing a mission's instruments from its Observatory run.
  Builds the record writer's input for every Instrument record of an Observatory,
  already registered or just created by the registrar, from the Observatory run's
  instrument_roles, reusing its authors, ORCIDs, affiliations, component papers and
  links instead of searching again. Records under another naming authority are
  reported, not written; a suite's components go on the suite's input. Writes JSON
  only; never changes the SPASE clone.
user-invocable: false
---

# SPASE Instrument Author Mapper

An Observatory run of `spase-author-finder` already records, in each candidate's
`instrument_roles`, who authored each of the Observatory's instruments, and the
enricher has already resolved their ORCIDs, affiliations and RORs. This skill
turns that into one writer input per instrument, so the record writer can write
every instrument of the mission in one run, with no per-instrument finder or
enricher runs. A mission is then complete: the Observatory and all its
instruments, in one pull request.

```
1–3. Observatory run   finder -> enricher -> writer      branch author-enrichment-<obs>
4.   Registrar         only if instruments are missing   branch instrument-registration-<obs>
5.   This skill        writer inputs for every instrument (JSON only, no branch)
6.   Writer            all ready inputs in one run       branch author-enrichment-<obs>-instruments
                                                         -> the one pull request
```

`<obs>` is the Observatory's ResourceID path, lower-cased with separators turned
into hyphens: `spase://SMWG/Observatory/Foo/Bar` gives `foo-bar`.

**Scope.** This skill writes JSON in the agents repository and nothing else. It
does NOT:
- look anyone up: every person, role and identifier comes from the Observatory run
- create or edit SPASE records, or touch the clone (it only reads it)
- write anything for a record under another naming authority
- give a suite's components inputs of their own

## Settled policy

Decided with the SMWG curators; apply it, do not re-litigate it per mission.

- **Every instrument gets reuse**, registered or new, so a mission is complete
  with all of its instruments.
- **Records under another authority are report only.** An SMWG Observatory's
  instruments filed under NOAA (or NASA, NSF, …) are listed with their authors in
  the mission report, for that authority's curators. Nothing is written for them.
- **Suite level only.** A component that has its own record (a suite's component filed
  under the suite's path) gets no input; its papers, links and authors go on the
  suite's input.

## Input

1. The Observatory run's enriched JSON:
   `spase_records/<record-name>/author_candidates_enriched.json`. It must carry
   `instrument_roles` (every finder run since that field was added does). An
   older file is refused: re-run the Observatory's finder and enricher first.
2. A local clone of the Observatory's authority repository, with the earlier
   stages' branches in it.
3. The registrar's plan, `instrument_registrations.json`, beside the enriched file
   when the registrar ran. The script finds it there.

## Procedure

### Step 1 — Dry-run the script

```bash
python3 .claude/skills/spase-instrument-author-mapper/scripts/build_instrument_inputs.py \
    --repo <clone> \
    --enriched spase_records/<record-name>/author_candidates_enriched.json \
    --dry-run
```

It reads records on `instrument-registration-<obs>` if that branch exists (the
registrar ran), else `author-enrichment-<obs>`, and says which. It lists every
Instrument record of the Observatory under any authority, matched on
ObservatoryID (the Heliophysics Instruments API lists every instrument, and each
record is read from spase-metadata.org), plus the registrar's new records, and
gives each one an action. A record filed under this Observatory's path that the
site does not publish at its ResourceID's address is still included, by its path,
with a warning; look at it yourself.

| Action | Meaning |
|---|---|
| `READY` | a writer input everyone in which was enriched on the Observatory run |
| `ENRICH` | a writer input with someone never enriched; run the enricher on it first |
| `FULL RUN` | the Observatory run's own result for it is incomplete (paper not located, selection uncertain, nobody found); a reference file for its own finder run |
| `REPORT` | under another authority: its authors are listed for that authority's curators, nothing is written |
| `COMPONENT` | a component of a suite: its authors and links are on the suite's input |
| `SKIPPED` | left out with `--skip` |
| `MISSING` | under the Observatory's authority but not in your clone on the base branch: pull, or check the branch |

### Step 2 — Judge what the script cannot

- **Not an instrument.** An ephemeris or position record, a spacecraft-bus or
  housekeeping record, is not something people author. Leave it out with
  `--skip "<ResourceID>=<reason>"`; the reason goes in the report.
- **A `FULL RUN` on an existing record** is normal when the Observatory run found
  nobody for it. Check the record's own Contacts in the clone: if it already has
  curated authors, say so in the report; the finder run on it will start from
  them.
- **Wrong attribution.** Read each input's people against its instrument. A person
  whose `instrument_roles` cite another instrument's paper means the finder
  mislinked them: report it, and fix the Observatory's finder output rather than
  this file.
- **A component shown as a suite**, or the reverse, because the record paths do not
  follow the suite/component convention: report it; the curators decide.
- **`MISSING`**: pull your clone, or rerun against the right base, before going on.

### Step 3 — Run it for real

The same command without `--dry-run`, with your `--skip` flags. It writes:

- one input per writable instrument, under
  `spase_records/<record-name>_<Acronym>/`, named by status:
  `author_candidates_enriched.json` (ready), `author_candidates.json` (enricher
  first) or `seed_candidates.json` (finder run first), with the Observatory's
  duplicate-person rulings for its people in `writer_decisions.json`;
- the mission report, `spase_records/<record-name>/instrument_inputs.json`: every
  instrument, its action, and for report-only records their authors.

It refuses to overwrite an input someone has since worked on (a finder, enricher
or curator edit), and writes nothing if any instrument fails.

### Step 4 — Hand off

1. For each `ENRICH` input, run the enricher on it; for each `FULL RUN`, run the
   finder (on the record's local file if it is new, or its ResourceID if it is
   published), then the enricher.
2. Run the writer once on every ready input, with the command the script prints:

   ```bash
   python3 .claude/skills/spase-record-writer/scripts/run_pipeline.py --repo <clone> \
       --input spase_records/<record-name>_<Acronym1>/author_candidates_enriched.json \
       --input spase_records/<record-name>_<Acronym2>/author_candidates_enriched.json \
       --base <the base the script used> \
       --branch author-enrichment-<obs>-instruments --initials <curator initials>
   ```

3. Open one pull request from `author-enrichment-<obs>-instruments`.
4. Send the report-only authors to that authority's curators.

## Report

Return, inline:

- the base branch used
- every instrument and its action; for each input, its status, people and links
- every `REPORT` record with its authors, grouped by authority, for its curators
- every `SKIPPED` record and why, and anything from Step 2
- the exact next commands, in order, ending with the one pull request to open
