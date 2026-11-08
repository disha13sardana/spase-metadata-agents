---
name: spase-missing-instrument-registrar
description: >
  Procedure for registering the instruments an Observatory author-finder run
  reported as missing from SPASE. Reads the run's enriched JSON, checks every
  naming authority (the Heliophysics Instruments API, with each record read from
  spase-metadata.org) for an existing record, writes a reviewable plan, and creates
  skeleton Instrument records under the Observatory's own naming authority, on a
  branch built on the Observatory's. Their authors come next, from
  spase-instrument-author-mapper. Never overwrites a record, never creates one
  that exists under any authority.
user-invocable: false
---

# SPASE Missing Instrument Registrar

An Observatory run of `spase-author-finder` compares the instruments registered
in SPASE against the mission's real payload and lists the gap in two places:
`instrument_coverage.missing_from_spase` and `pending_instrument_runs` entries
whose `spase_record` is `null`. Those instruments cannot get authors until they
have an Instrument record.

This skill creates that record, a skeleton. The next step,
`spase-instrument-author-mapper`, then builds the writer's input for every
instrument of the Observatory, these new records included, from what the
Observatory run already found. Its branch is built on the Observatory writer's,
so a mission ends in one pull request:

```
1–3. Observatory run   finder -> enricher -> writer      branch author-enrichment-<obs>
4.   This skill        plan -> skeleton records          branch instrument-registration-<obs>
                                                         (built on 1–3)
5.   Author mapper     writer inputs for every instrument (JSON only)
6.   Writer            all ready inputs in one run       branch author-enrichment-<obs>-instruments
                                                         -> the one pull request
```

`<obs>` is the Observatory's ResourceID path, lower-cased with separators turned
into hyphens: `spase://SMWG/Observatory/Foo/Bar` gives `foo-bar`.

Most Observatories have nothing missing. When the worklist (Step 1) is empty,
write no plan, create no branch, and report "no missing instruments"; go straight
to the author mapper.

**Scope.** This skill creates new Instrument records and nothing else. It does
NOT:
- write Contacts or InformationURLs (the record carries only the UNKNOWN
  placeholder until the writer runs)
- build the writer's inputs (the author mapper does, for every instrument)
- fill InstrumentType, InvestigationName or Description, for now (see Step 4)
- write DOI, PublicationInfo, Acknowledgement, OperatingSpan, Caveats or
  InstrumentGroupID
- edit any existing record, including the Observatory record
- create records for the components inside a suite

## Settled policy

These were decided with the SMWG curators. Apply them; do not re-litigate them
per mission.

- **The pipeline registers missing instruments.**
- **Same naming authority as the Observatory record.** A new Instrument record for
  `spase://<A>/Observatory/...` is `spase://<A>/Instrument/...`, in authority
  `<A>`'s repository, even when some of the Observatory's existing instruments sit
  under another authority. The script refuses any other authority.
- **Check every authority first**, through the Heliophysics Instruments API and
  the records it lists on spase-metadata.org.
- **Suite level only.** A suite gets one record; its components get none. A component's
  papers, links and authors go on the **suite's** record.
- **Register everything on the payload**, including instruments outside
  heliophysics (Earth-observing, meteorological, astrophysics), and flag those,
  so they can be found later if the policy changes.
- **Skeleton fields left unfilled for now**: InstrumentType, InvestigationName
  and Description.
- **Reuse the Observatory run** for every instrument, through the author mapper.
- **One pull request per mission**, at the end of the chain. (For NASA-authority
  records, submitting through the mEditor API instead is planned; not yet built.)

## Principles

**Unfilled is not invented.** A skeleton leaves some fields unfilled, but nothing
it does write is guessed: the name, the alternate names, the ObservatoryID and
the placeholder Contact are all real. An unfilled field is visibly unfilled
(`Unspecified`, or an empty element), never a plausible-looking guess.

**Never create what already exists.** A record missing from the curator's clone is
not missing from SPASE. Instrument records are published under many naming
authorities, and one Observatory's instruments are often split across several. A
second record for the same instrument splits its identity the way a duplicate
Person record splits a person's. The script checks every instrument the
Heliophysics Instruments API lists, under every authority, before it writes
anything.

**Never overwrite.** If the target file exists, the entry is a `skip`. A skeleton
is only ever a new file.

**Research and writing stay separate.** You decide the values and record them,
with evidence, in `instrument_registrations.json`. The script writes the XML from
that file, nothing else. A reviewer can check every value before anything touches the repository.

**Chain the branches; never share one.** The registration branch is built on the
Observatory writer's branch, and the instrument writer's branch on the
registration branch, so the last branch carries everything for the mission and
is the one pull request. They stay separate branches because each stage resets
its own branch on a re-run: a stage's commits are never mixed into another
stage's branch, so any stage can be re-run without disturbing the others' work.
After re-running an earlier stage, re-run the later ones in order; each accepts
the earlier stages' stale commits as pipeline output and resets past them.

## Input

1. The Observatory run's enriched JSON:
   `spase_records/<record-name>/author_candidates_enriched.json`.
2. A local clone of the Observatory's authority repository (the SMWG repository
   for an SMWG Observatory), supplied by the human, in which the Observatory
   writer's branch `author-enrichment-<obs>` exists.

## Procedure

### Step 1 — Build the worklist

Collect, from the enriched JSON:

- every `pending_instrument_runs` entry with `spase_record: null`
- every name in `instrument_coverage.missing_from_spase`

Merge entries that name the same instrument. A suite often appears twice, once by
itself and once with its components in parentheses (`<Suite>` and
`<Suite> (<ComponentA>, <ComponentB>)`): that is one instrument plus its components.
List the components on the suite's `create` entry as `components`; the author mapper
uses that list to put the components' papers, links and authors on the suite's input.
Keep the `description_paper`, `reason` and `notes` from the pending entry.

A `pending_instrument_runs` entry whose `spase_record` is **not** null already has
a record. It needs an ordinary per-instrument author run, not a skeleton. Leave it
out of the plan and list it in the report so it is not forgotten.

`missing_from_spase` entries are sometimes prose rather than a bare name. Read the
reasoning, and `instrument_coverage.notes` and each pending entry's `notes`: the
finder records why something is on the roster (a communications relay, a
platform pseudo-instrument, an antenna with no receiver), and that decides Step 3.

### Step 2 — Check every authority for an existing record

Run the registry lookup for the Observatory:

```bash
python3 .claude/skills/spase-missing-instrument-registrar/scripts/registry.py \
    lookup --observatory <Observatory ResourceID> --name <Acronym> --name <Full name>
```

It works in two steps:

1. **The Heliophysics Instruments API** (https://api.heliophysics.net/api/instruments/)
   lists every registered instrument under every authority (`id`, `long_name`,
   `spase_id`).
2. **Each listed record is read from spase-metadata.org**, at the address its
   ResourceID gives (`spase://ASWS/Instrument/Ground/Alice_Springs/Ionosonde` is
   `https://spase-metadata.org/ASWS/Instrument/Ground/Alice_Springs/Ionosonde.xml`),
   for its `<ObservatoryID>`.

So it finds the Observatory's instruments under any authority and wherever they
are filed (`spase://SMWG/Observatory/X` and `spase://NASA/Observatory/X` are the
same mission). No GitHub token is needed. The first run reads every record once
(a few thousand small files); later runs read only instruments new to the API, and
records older than 30 days.

A few records are published at a path that differs from their ResourceID, so
there is nothing at the address it gives. The lookup lists any such record filed
under this Observatory's path as `UNREADABLE`; it is still checked by its name
and path, but its ObservatoryID could not be read, so look at it yourself. Such
records elsewhere in the registry are only counted.

`--source github` reads the hpde repositories (https://github.com/hpde) through
the GitHub API instead: it reads the files themselves, so no record is
unreadable, but its first build needs a GitHub token (`GITHUB_TOKEN`, or
`gh auth login`).

The lookup marks records that share a name with yours. Then judge, which the script cannot: search under
every name the instrument goes by (acronym, full name, the provider's variants:
`MAG` and `Magnetometer` often name the same record), and look for the same
mission registered as an Observatory under another authority with a different
path.

A hit anywhere makes the entry a `skip` with
`skip_reason: "exists as <ResourceID>"`. Report it prominently: it means the
Observatory run's `instrument_coverage` missed a registered record, and the
finder should be re-run or corrected.

Record what you checked in each entry's `existence_check`. The script repeats both
checks before writing, so a record you missed still stops the run.

### Step 3 — Decide create or skip

| Situation | Action |
|---|---|
| No record under any authority; a payload instrument or suite | `create` |
| Record exists under any authority | `skip` — "exists as …" |
| A component inside a suite | `skip` — "component of the <Suite> suite; records are suite-level, its papers and links go on the <Suite> record"; and list it in the suite's `components` |
| Not an instrument: comms relay, spacecraft bus, housekeeping | `skip` — "not an instrument" |
| The finder flagged it for curators (no data product, unclear whether it is a separate instrument) | `skip` — "curator decision: <the finder's reason>" |

**Flags.** Create the record but add a `flags` entry when something needs a
curator's eye, now or later. A flag never blocks the write; it is what the
reviewer reads first. Always flag:
- **an instrument outside heliophysics** — Earth-observing, meteorological,
  astrophysics, planetary-interior: `"outside heliophysics: <what it observes>"`.
  It is registered either way; the flag lets these records be found if the
  policy changes.
- **a suite with components** — `"suite record; carries the papers and links of its
  components <ComponentA>, <ComponentB>"`.

Also flag anything the sources disagree on, such as the instrument's name.

### Step 4 — Fill the fields

Read the **sibling Instrument records** of the same Observatory in the clone
first: they set the house conventions you match.

**`resource_id`** — `spase://<A>/Instrument/<ObservatoryPath>/<Acronym>`, where
`<A>` is the Observatory record's authority. If siblings under `<A>` sit at
`spase://<A>/Instrument/<ObservatoryPath>/<X>`, the new one goes beside them;
with none, use the Observatory's own path after `Instrument/`. Use the
instrument's standard acronym: letters, digits, `-` and `.` only.

**`resource_name`** — the full name as the Observatory's siblings style it: if
they write `<Mission> <Full name> (<Acronym>)`, so do you; otherwise the full name
as the instrument's team writes it. **`alternate_names`** — the acronym, the bare
full name if `resource_name` adds to it, and any other name the sources use. Do
not repeat `resource_name`.

**`observatory_id`** — the Observatory record's ResourceID, exactly.

**InstrumentType, InvestigationName and Description are left unfilled for now.**
Do not research them and leave them out of the plan. SPASE requires all three
elements, so the script writes them in their unfilled form:
- `<InvestigationName></InvestigationName>` and `<Description></Description>`,
  empty, which the schema accepts;
- `<InstrumentType>Unspecified</InstrumentType>`. InstrumentType is a closed
  enumeration and an empty value fails schema validation, so the record would
  fail CI; `Unspecified` is the schema's own "not known" value.

When the policy changes, a plan entry may carry `instrument_type`
(`{"value", "evidence", "source_url"}`), `investigation_name` and `description`
(`{"text", "sources"}`); the script validates and writes them.

### Step 5 — Check the Observatory file carries `instrument_roles`

The author mapper needs every candidate in the Observatory's enriched file to
have the `instrument_roles` key (even if `[]`). Files from finder runs before
that field existed do not; report that the Observatory's finder and enricher
must be re-run before its instruments can be filled.

### Step 6 — Write the plan, then run the script

Save `spase_records/<record-name>/instrument_registrations.json` next to the
enriched file. Never modify the enriched file. The shape, with placeholders:

```json
{
  "observatory_record": "spase://<A>/Observatory/<ObservatoryPath>",
  "source_file": "spase_records/<record-name>/author_candidates_enriched.json",
  "date": "<YYYY-MM-DD>",
  "entries": [
    {
      "instrument": "<Acronym>",
      "source_entries": ["pending_instrument_runs: <Acronym>", "instrument_coverage.missing_from_spase: <Acronym>"],
      "action": "create",
      "skip_reason": null,
      "resource_id": "spase://<A>/Instrument/<ObservatoryPath>/<Acronym>",
      "resource_name": "<Full instrument name, styled like the siblings>",
      "alternate_names": ["<Acronym>"],
      "components": ["<ComponentA>", "<ComponentB>"],
      "observatory_id": "spase://<A>/Observatory/<ObservatoryPath>",
      "existence_check": {
        "clone": "<what was compared, and the result>",
        "registry": "<registry.py lookup result from both sources, other names searched>"
      },
      "description_paper": "<DOI, or citation when there is none, or null>",
      "not_duplicate_of": [],
      "flags": ["suite record; carries the papers and links of its components <ComponentA>, <ComponentB>"]
    },
    {
      "instrument": "<ComponentA>",
      "source_entries": ["instrument_coverage.missing_from_spase: <ComponentA>"],
      "action": "skip",
      "skip_reason": "component of the <Suite> suite; records are suite-level, its papers and links go on the <Suite> record"
    }
  ],
  "notes": ["<pending entries that already have a record, and anything else the reviewer should know>"]
}
```

`components` is only for a suite; omit it otherwise. `not_duplicate_of` is for the
script's duplicate guard: if it flags an existing record as a possible duplicate
and the evidence shows a different instrument, add
`{"id": "<that ResourceID>", "reason": "<why>"}` and re-run. Rule on it yourself
when the evidence is clear; ask the human only when you cannot tell.

Dry-run first; it validates the plan and prints each record, without touching
git:

```bash
python3 .claude/skills/spase-missing-instrument-registrar/scripts/register_instruments.py \
    --repo <clone> \
    --input spase_records/<record-name>/instrument_registrations.json \
    --initials <curator initials> --dry-run
```

Then the same command without `--dry-run`. It checks the clone is clean, consults
both registry sources, creates `instrument-registration-<obs>` on top of the
Observatory writer's branch `author-enrichment-<obs>` (falling back, with a
warning, to the default branch if that branch is missing; `--base` overrides),
and validates the plan against that base. A re-run resets the registration
branch, and refuses only if it carries commits that neither this script nor the
record writer made. Nothing is written unless every `create` entry passes: the
authority the Observatory's, the ObservatoryID present in the clone, the target
absent from the clone, from the Heliophysics Instruments API and from every
authority repository, no unruled name clash with any record of the same
Observatory. It then writes the records, runs `spase-localcheck.py`, commits, and
pushes the branch to the curator's fork.
It never touches `master` or `main`, and rolls the clone back completely on any
failure.

`--no-push`, `--no-commit`, `--branch`, `--base` and `--plan-url` (a
commit-pinned link to the plan, appended to the RevisionEvent) behave as in the
record writer. `--registry-source github` reads the hpde repositories instead
of the API and site; `--registry-dir DIR` reads local clones of them, for offline
work.

Each record gets a first `RevisionEvent` saying it is a skeleton, which fields are
not yet filled, and why, so the writer's later event reads as the next step in
its history.

### Step 7 — Hand off

Run `spase-instrument-author-mapper` next, on the same Observatory enriched file.
It builds the writer's input for every instrument of the Observatory, these new
records included, on top of this branch; the script prints the command.

## Report

Return, inline:

- the worklist and where each entry came from
- each `create`, with its ResourceID and its components, if a suite
- each `skip` and its reason — **"exists as …" first**, since it means the
  Observatory run's coverage is wrong
- every `flags` entry
- pending entries that already had a record and need an ordinary author run
- the script's output: base branch, registry results from both sources, local
  check, commit, push status
- the next command: the author mapper on the Observatory's enriched file
