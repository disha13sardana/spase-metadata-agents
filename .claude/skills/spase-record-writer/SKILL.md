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

**Confirm you are in the right clone.** More than one clone of the same
repository can exist on one machine, on branches of the same name, both clean.
Nothing in a clone's git state identifies which one is live, so use the `--repo`
path you were given rather than the first clone you find by name, and if a second
one turns up, ask.

**Re-runs reset, they do not stack.** If the branch already exists, reset it to
the default branch before writing, and take the validation baseline *after* the
reset. A re-run must neither build on the previous run's output nor inherit it as
its baseline. Two things go wrong otherwise:

- the writer reads its own earlier `OrganizationName` as a curated registry value
  and reports `ORG KEPT` on it, so a bad write becomes permanent and invisible;
- errors the earlier run introduced are counted as pre-existing, and the
  regression check in Step 10 stops being able to fail.

**Reset only what this skill wrote.** If any commit on the branch is not one of
this skill's own, stop and ask. This is the same rule as the dirty working tree
above, applied to commits: you cannot tell a curator's hand-correction from your
own earlier output, and a reset would destroy it silently.

Resetting is what makes the rest of the procedure safe to repeat, but it is not a
substitute for checking the output. It stops the writer misreading its own work
as curated data; it does not catch a value that was never in the input to begin
with. That is Step 10's audit.

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

**Backfill `PersonName` when it is missing.** It is optional in the schema but
present on all but a handful of registry records, so a record without one stands
out. Set it from the candidate's name and log the addition.

Never overwrite an existing `PersonName`. Registry names carry honorifics and
spellings the input does not — `Bronislaw K Dichter` against an input of
`B. K. Dichter`, `Mr. William E. Shenk` against `William Shenk`. Replacing those
would trade curated data for generated data and lose information.

**Existing record** — edit in place. Preserve the file's existing indentation,
field order and untouched content. Do not reformat, do not reorder, do not
rewrite the file canonically: a whole-file rewrite turns three semantic changes
into a thirty-line diff and buries the real change from reviewers.

Add `ORCIdentifier` only when absent. If the record already has a different one,
keep the existing value and log the clash — a conflicting ORCID means one of the
two is attached to the wrong human, which needs a person to look at it.

**Record affiliation provenance in `Person/Note`.** Where the affiliation came
from is part of what makes the record auditable, so write the enrichment's
`affiliation_source` and `affiliation_type` into the Person record's `Note`:

```xml
<Note>Affiliation source: ORCID employment; type: current.</Note>
```

`Note` is cardinality 0..1 and sits between `ORCIdentifier` and `RORIdentifier`
in the Person sequence — not beside `ORCIdentifier`.

Write it whenever the input supplied a real affiliation, including when that
affiliation matched what the record already had: the provenance is true either
way. Do **not** write it when the input had no affiliation and the existing
`OrganizationName` was kept — that would attribute a curated value to a source
that did not produce it.

Never overwrite a curated `Note`. If a record already has one that this skill did
not write (it will not begin with `Affiliation source:`), preserve it and log
that the provenance was not recorded. Registry Notes carry things like
"Retired as of the creation of this SPASE record", which must not be lost.

Keep the Note to source and type. The enricher's full reasoning — candidate
ORCIDs considered, checksum results, reviewer suggestions — belongs in the run
log and the PR description, not in the registry record.

### Step 7 — Write Contact blocks

Each candidate becomes one `Contact` with `Author` plus any `qualifying_roles`
from the input:

```xml
<Contact>
  <PersonID>spase://SMWG/Person/Howard.J.Singer</PersonID>
  <Role>PrincipalInvestigator</Role>
  <Role>Author</Role>
</Contact>
```

`Role` has cardinality `(+)`, so multiple roles on one Contact are valid and
preferred over duplicate Contact blocks for the same person.

### Role precedence

Contact blocks are ordered by each person's **highest-ranking role**, and the
`Role` elements inside a block follow the same order:

```
MissionPrincipalInvestigator, PrincipalInvestigator, ProgramScientist,
ProjectScientist, CoPI, DeputyPI, FormerPI, InstrumentLead,
InstrumentScientist, CoInvestigator, Author
```

`Author` ranks last, so people carrying only that role follow everyone with a
mission or instrument role. This puts the record's most senior contributors at
the top, where a reader looking for who ran the mission will find them.

People sharing a rank keep the order the enricher produced — evidence strength
and author position — so the sort is stable rather than reshuffling the list.
A role outside the precedence list sorts last and is logged rather than dropped;
that is a signal the list needs extending, not a reason to discard the role.

### The Note carries the role evidence

Every Contact gets a `<Note>` holding the `role_evidence` source from the input
— the citation or record that justifies the role. This is what makes the
authorship claim auditable: a reviewer can see *why* each person is listed
without going back to the JSON.

```xml
<Contact>
  <PersonID>spase://SMWG/Person/Paul.T.M.Lotoaniu</PersonID>
  <Role>Author</Role>
  <Note>Lead author (position 1), GOES-16 MAG description paper (Loto'aniu et al. 2019, 10.1007/s11214-019-0600-3)</Note>
</Contact>
```

`Note` has cardinality 0..1 — **one Note per Contact, no more**. When a candidate
has several `role_evidence` entries, fold them into a single Note, each labelled
with the role it supports, **ordered by the same role precedence as the `Role`
elements above them**, and **on its own line** — a run-on string carrying two
or three justifications is unreadable in a diff or a rendered record. Continuation
lines are indented to sit under the opening tag; single-entry Notes stay on one
line:

```xml
<Contact>
  <PersonID>spase://SMWG/Person/Howard.J.Singer</PersonID>
  <Role>PrincipalInvestigator</Role>
  <Role>Author</Role>
  <Note>PrincipalInvestigator: GOES-16 MAG SPASE Instrument record Contacts (https://spase-metadata.org/SMWG/Instrument/GOES/16/MAG.html)
          Author: MAG PrincipalInvestigator in the GOES-16 MAG SPASE record, corroborated by the record Acknowledgement and MAG description-paper co-authorship</Note>
</Contact>
```

Note text is transcribed from the input and XML-escaped, never composed. A
candidate with no `role_evidence` gets a Contact without a Note, and the omission
is logged rather than papered over with invented justification.

**Bare DOIs are turned into resolver URLs** so a reviewer can click straight
through to the evidence: `10.1007/s11214-019-0600-3` becomes
`https://doi.org/10.1007/s11214-019-0600-3`. This is the one permitted edit to
transcribed text, and only because it is purely additive — a prefix goes on, the
identifier itself is never altered, so the note still reproduces exactly what the
input said. Strings that are already URLs are left alone, and a DOI already
inside a URL is never prefixed twice. The same applies to `affiliation_evidence`
in the Person Note.

`Note` is the last child of `Contact`: `PersonID, Role(+), StartDate, StopDate,
Note`.

### Placement, and re-running safely

`Contact` appears in `ResourceHeader` after `Funding` and before
`InformationURL`.

Writing Contacts is **idempotent**. Replace the `spase://SMWG/Person/UNKNOWN`
placeholder and any existing Contact whose `PersonID` is one you are writing;
leave every other Contact untouched and report how many you kept. This matters
because records get re-run — after a finder re-run, or to add a field like this
one — and blind appending silently doubles the contact list.

An existing Person record whose ID is exactly the ID you would mint for a
candidate **is** that person; link to it rather than flagging a collision. That
case is usually your own output from an earlier run.

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

**Audit every written value against the input before committing.** Diff the
Person records this run touched and check each `OrganizationName`,
`RORIdentifier` and `ORCIdentifier` you added or replaced against the candidate
it came from. A written value with no matching value in the input is a bug, not a
judgement call — the input is the only source. Being right about the real world
is not the standard; matching the input is. A null is a researched finding, not a
blank to fill.

Then stage everything together:

```bash
git add <target record> Person/
git commit -m "GOES 16: add mission Contacts with Author and qualifying roles"
git push --force-with-lease -u origin author-enrichment-goes-16
```

Person records and the target record **must** be in the same commit. A commit
where the Contact exists and the Person file does not is a broken referential
state that fails CI.

The push is forced because Step 1 resets an existing branch, so a re-run diverges
from what was pushed before. Use `--force-with-lease`, never bare `--force`: it
refuses when the remote moved for a reason you have not seen. If it does refuse,
stop and ask rather than escalating — someone else has touched the branch, which
is exactly the case Step 1's reset guard exists to protect.

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