---
name: spase-record-writer
description: >
  Procedure for applying the enriched author candidates produced by the
  spase-affiliation-enricher agent to a local clone of a SPASE metadata
  repository. Writes role-tagged Contact blocks into the target Observatory or
  Instrument record, creates Person records for candidates that lack one, adds
  ORCID/ROR/affiliation to existing Person records, corrects schemaLocation to
  match the declared Version, and stages the result on a branch for human review.
  Transcribe-only: every value written comes from the input file. Halts on
  possible duplicate people. Never pushes, merges, or writes to the default
  branch.
user-invocable: false
---

# SPASE Record Writer

The third stage of the pipeline. The finder proposes people, the enricher
resolves their identifiers, and this skill puts the result into the XML.

It is the only stage that modifies SPASE records, so its default posture is
caution: transcribe what the input says, stop when something is ambiguous, and
leave the human a reviewable branch rather than a pushed commit.

## Input

1. `spase_records/<record-name>/author_candidates_enriched.json` — the enricher's
   output. Never the finder's `author_candidates.json`; it lacks resolved ORCIDs,
   affiliations and RORs.
2. The path to a local clone of the target repository (e.g. `~/SMWG`).

### Resolving the target record

The JSON's `record` field holds the ResourceID. Map it to a path by convention:

```
spase://SMWG/Observatory/GOES/16   ->   <clone>/Observatory/GOES/16.xml
spase://SMWG/Instrument/GOES/16/SUVI -> <clone>/Instrument/GOES/16/SUVI.xml
```

**If the file does not exist, stop.** Do not create it. A missing target almost
always means the record lives under a different naming authority and therefore in
a different repository — some records carry an `spase://SMWG/...` ResourceID while
being published under another authority, which is a registration inconsistency
worth reporting rather than working around.

## Which candidates to process

Only `status: "included"`. Ignore `excluded` candidates entirely, regardless of
`exclusion_reason` or `confidence`.

`confidence` (`Strong` / `Medium`) does **not** gate writing — the finder already
made the inclusion decision. If the human wants a confidence floor they will say
so; surface the mix in your report so they can judge.

## Output

Modified XML in the human's clone on a new branch, plus an inline report. Never
write JSON, never modify the input file.

## Procedure

### Step 1 — Branch before touching anything

```bash
cd <clone>
git status --short          # must be clean; stop if not
git checkout -b author-enrichment-<record-name>
```

Never write to `master` or `main`. If the working tree is dirty, stop and ask —
you cannot tell someone else's work in progress from a previous failed run.

### Step 2 — Duplicate check, before any write

For every included candidate without a `person_record.id`, search the existing
`Person/` directory for the same human under a different ID. Match on surname,
then rank by given-name agreement including nicknames.

Real cases this catches:

| Candidate | Existing record | Same person? |
|---|---|---|
| Terrance G. Onsager | `Terry.Onsager` | yes — nickname |
| B. K. Dichter | `Bronislaw.K.Dichter`, `B.Dichter` | yes — initials, and the two existing records duplicate each other |
| Pamela C. Sullivan | `Robert.J.Sullivan.Jr`, `James.D.Sullivan` | no — different people |
| Daniel T. Lindsey | `R.Lindsey` | no |

**When anything is flagged, write nothing and stop.** Report every flagged name
with its candidate matches and ask the human to decide each one. Resolutions are
passed back as explicit `--link "<name>=<PersonID>"` or `--create "<name>"`
arguments. Never guess, and never let a flagged name through because the other
matches looked wrong.

Also report — but do not fix — duplicate pairs you notice among *existing*
records. They are a pre-existing repository problem, not yours to resolve inside
an authorship change.

### Step 3 — Mint IDs for genuinely new people

Convention: `GivenName.[MiddleName. or MI.]FamilyName`.

Strip characters outside `[A-Za-z. ]` from the ID. Apostrophes in particular
have no precedent in the registry and cause trouble in filenames and URIs:

```
Paul T. M. Loto'aniu   ->   Paul.T.M.Lotoaniu
```

The `PersonName` element keeps the correct spelling, apostrophe included. Only
the ID is normalised. Log every mint where the ID differs from a straight
dot-joining of the name, so a reviewer can see the transformation.

### Step 4 — Normalise identifier formats

The repository stores bare identifiers; the enricher emits URLs.

| Field | Input | Written |
|---|---|---|
| ORCID | `https://orcid.org/0000-0001-6601-9116` | `0000-0001-6601-9116` |
| ROR | `https://ror.org/02ttsq026` | `02ttsq026` |

### Step 5 — Resolve the affiliation

`OrganizationName` has cardinality 1 — one value, required on every Person
record. The enricher may supply several separated by ` / `.

- **Multiple affiliations:** keep the first, log the dropped remainder.
- **No affiliation, new record:** use `Unknown`. This is established registry
  practice and is the only way to emit a valid record.
- **No affiliation, existing record:** keep what is already there. Never
  overwrite a real value with the fallback.
- **Real affiliation, existing record:** overwrite, and log the before/after.
  The input carries the current affiliation; the registry value is often stale.

**`RORIdentifier` follows `OrganizationName`.** When you change the organisation,
change its ROR in the same edit. Leaving the old ROR beside a new organisation
makes the record assert two different institutions.

Do not attempt to encode era-matched affiliation in the Person record. Person
records are global and shared across every mission that references them, and
`OrganizationName` is single-valued and timeless. Time-scoped information belongs
on the `Contact` block's `StartDate` / `StopDate`, on the record where the era
actually applies.

### Step 6 — Write Person records

**New record** — element order matters; the schema is a strict sequence:

```xml
<?xml version='1.0' encoding='UTF-8'?>
<Spase xmlns="http://www.spase-group.org/data/schema"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="https://www.spase-group.org/data/schema https://www.spase-group.org/data/schema/spase-2.7.1.xsd">
  <Version>2.7.1</Version>
  <Person>
    <ResourceID>spase://SMWG/Person/Francis.G.Eparvier</ResourceID>
    <NamingAuthority>SMWG</NamingAuthority>
    <ResourceType>Person</ResourceType>
    <ReleaseDate>2026-08-02T21:09:10Z</ReleaseDate>
    <PersonName>Francis G. Eparvier</PersonName>
    <OrganizationName>Laboratory for Atmospheric and Space Physics, University of Colorado Boulder</OrganizationName>
    <ORCIdentifier>0000-0001-7143-2730</ORCIdentifier>
    <RORIdentifier>02ttsq026</RORIdentifier>
  </Person>
</Spase>
```

Full 2.7.1 `Person` sequence, for placing inserts:

```
ResourceID, NamingAuthority, ResourceType, ReleaseDate, PersonName,
OrganizationName, Address, Email, PhoneNumber, FaxNumber, ORCIdentifier,
Note, RORIdentifier, Extension
```

Note `RORIdentifier` sits *after* `Note`, not beside `ORCIdentifier`.

**Existing record** — edit in place. Preserve the file's existing indentation,
field order and untouched content. Do not reformat, do not reorder, do not
rewrite the file canonically: a whole-file rewrite turns three semantic changes
into a thirty-line diff and buries the real change from reviewers.

Add `ORCIdentifier` only when absent. If the record already has a different one,
keep the existing value and log the clash — a conflicting ORCID means one of the
two is attached to the wrong human, which needs a person to look at it.

### Step 7 — Write Contact blocks

Each candidate becomes one `Contact` with `Author` plus any `qualifying_roles`
from the input:

```xml
<Contact>
  <PersonID>spase://SMWG/Person/Howard.J.Singer</PersonID>
  <Role>Author</Role>
  <Role>PrincipalInvestigator</Role>
</Contact>
```

`Role` has cardinality `(+)`, so multiple roles on one Contact are valid and
preferred over duplicate Contact blocks for the same person.

Placement: `Contact` appears in `ResourceHeader` after `Funding` and before
`InformationURL`. When the record has the usual `spase://SMWG/Person/UNKNOWN`
placeholder Contact, replace it — that placeholder is what this work exists to
remove. Otherwise append after the last existing Contact and say so in the
report, since preserving unrelated contacts is a judgement the human should see.

### Step 8 — Correct schemaLocation

Records commonly declare `<Version>2.7.1</Version>` while pointing
`xsi:schemaLocation` at a much older XSD. That inconsistency matters here because
`Author`, `InstrumentScientist`, `ORCIdentifier` and `RORIdentifier` do not exist
in those older schemas — writing them against a stale schemaLocation produces a
record that cannot validate.

Set both, on every file you touch, Person records included:

```
<Version>2.7.1</Version>
xsi:schemaLocation="https://www.spase-group.org/data/schema https://www.spase-group.org/data/schema/spase-2.7.1.xsd"
```

Describe this in the RevisionEvent as a *correction* — the declared Version
already said 2.7.1, so the edit makes the file internally consistent.

### Step 9 — RevisionEvent and ReleaseDate

Append a `RevisionEvent` to the target record's existing `RevisionHistory`,
matching the registry's house style (a short note, ending with curator initials),
and update the `ResourceHeader` `ReleaseDate` to the same timestamp.

```xml
<RevisionEvent>
  <ReleaseDate>2026-08-02T21:09:10Z</ReleaseDate>
  <Note>Added mission Contacts with Author and qualifying roles derived from mission literature and instrument records; corrected schemaLocation to match the declared SPASE Version. DS</Note>
</RevisionEvent>
```

### Step 10 — Validate, then hand over

```bash
python3 <path>/spase-localcheck.py Observatory/GOES/16.xml Person
```

Compare against the pre-run baseline. **New errors mean stop and fix**; identical
errors mean they were already there. Dangling `PersonID` references are the
failure this catches, and they mean a Person record was missed.

**A run that introduces new errors must roll back, not commit.** Restore the
working tree, delete the branch if this run created it, and report which errors
appeared. Never leave a half-applied change behind.

Then stage everything together:

```bash
git add <target record> Person/
git commit -m "GOES 16: add mission Contacts with Author and qualifying roles"
git push -u origin author-enrichment-goes-16
```

Person records and the target record **must** be in the same commit. A commit
where the Contact exists and the Person file does not is a broken referential
state that fails CI.

Push the branch to the curator's own fork. Never push to `master` or `main`, and
never open or merge a pull request — the branch is where the human's review
begins, not ends.

## Reference Implementation

Two scripts. Use `run_pipeline.py` — it performs every step above in order.
`write_records.py` is the step 2–9 core and is called by the pipeline; run it
directly only when debugging.

```bash
python3 scripts/run_pipeline.py --repo ~/SMWG \
    --input spase_records/GOES_16/author_candidates_enriched.json \
    --initials DS
```

That single command does: clean-tree check, branch, baseline validation, write,
re-validation against the baseline, commit, push. It rolls the branch back and
deletes it if the writer aborts or if validation regresses, so a failed run
leaves the clone exactly as it started.

**Collision decisions are answered once per record, not per run.** The first run
aborts, prints each flagged name with the identifying details of every possible
match, and writes a `writer_decisions.json` template beside the input:

```json
{
  "links": {
    "B. K. Dichter": "Bronislaw.K.Dichter",
    "Terrance G. Onsager": "Terry.Onsager"
  },
  "creates": ["Pamela C. Sullivan", "Daniel T. Lindsey"]
}
```

Set `links[name]` to an existing PersonID when it is the same human; move the
name into `creates` when it is a different person. Re-run the identical command
and it proceeds. The file persists, so re-running that record later — after a
finder re-run, say — needs no decisions again. New names appearing in a later
enrichment are appended to the template as undecided rather than assumed.

The agent is expected to *make* these decisions where the evidence is clear,
using the affiliation and email shown for each match, and to ask the human only
where it genuinely cannot tell.

Batch several records by repeating `--input`; each gets its own decisions file
and they land on one branch.

Useful flags: `--no-push` stops after the commit, `--no-commit` leaves changes in
the working tree, `--branch` overrides the derived branch name, `--checker`
points at `spase-localcheck.py` if it is not beside the scripts.

## Divergence Log

Every judgement call gets logged and surfaced to the human. These are the lines a
reviewer will ask about, so they belong in the report and in the PR description:

- `ORG CHANGE` — an existing affiliation was replaced
- `ORG KEPT` — input had no affiliation, existing value preserved
- `ROR CHANGE` — a ROR moved to follow its organisation
- `ORCID CLASH` — repository and input disagree; repository value kept
- `MULTI-AFF` — a second affiliation was dropped
- `NO AFFIL` — `Unknown` fallback used on a new record
- `MINT` — an ID was normalised away from the person's written name
- `LINK` — a curator-confirmed match to an existing record
- `APPEND` — existing Contacts were kept rather than replaced

## Human-Approval Gate

This skill stops at a pushed branch on the curator's own fork. It does not open a
pull request, does not merge, and never writes to `master` or `main`. Everything
it does is reversible with `git push -d origin <branch>`.

Before the human pushes, put in front of them: the diffstat, the divergence log,
the local checker result against the baseline, and the count of new Person
records. Call out explicitly anything that changes data someone previously
curated by hand — replaced affiliations most of all, since those are the edits
most likely to be wrong and least likely to be noticed.