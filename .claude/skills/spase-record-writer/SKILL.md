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

**Check whenever a record would be created, not only when an ID was minted.**
An ID asserted by the input is a claim about which file *should* exist, not
evidence that it does. When the asserted ID resolves to no file, the writer is
about to create a record — so it gets the same scrutiny as one this skill minted.
Gating the check on "the input supplied no ID" lets asserted IDs through
unchecked, which is the shortest path to a silent duplicate: `T.Onsager` asserted
against an existing `Terry.Onsager` would create a second record for one person
without a word in the log.

Where the ID differs from the conventional form for that name, log `ID SHAPE`.
`M.Tajmar` for a person whose name is Martin Tajmar is legal and may be
deliberate, but it is also exactly the shape that collides with a full-name
record later, so a curator should see it.

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

Fold accented letters to their base letter, keep hyphens, and strip anything
else outside `[A-Za-z.- ]`. Apostrophes in particular have no precedent in the
registry and cause trouble in filenames and URIs; folded accents and kept
hyphens are the registry's own practice (`Goran.T.Marklund`,
`Bengt-Goran.Andersson`, `Jorg-Micha.Jahn`):

```
Paul T. M. Loto'aniu   ->   Paul.T.M.Lotoaniu
Göran Olsson           ->   Goran.Olsson
Bengt-Göran Andersson  ->   Bengt-Goran.Andersson
```

The duplicate check compares names on the same folded, letters-only key on both
sides, so an accented or hyphenated surname still meets its existing record.

The `PersonName` element keeps the correct spelling, apostrophe included. Only
the ID is normalised. Log every mint where the ID differs from a straight
dot-joining of the name, so a reviewer can see the transformation.

### Step 4 — Normalise identifier formats

The repository stores bare identifiers; the enricher emits URLs.

Identifiers are written **bare**, matching the registry: 124 of 126 existing
`ORCIdentifier` values and all 141 `RORIdentifier` values are.

| Field | Input (either form) | Written |
|---|---|---|
| ORCID | `https://orcid.org/0000-0001-6601-9116` | `0000-0001-6601-9116` |
| ROR | `https://ror.org/02ttsq026` | `02ttsq026` |

`IDENTIFIER_FORM` in `write_records.py` switches this to `url` in one line, but
only on a curator's instruction — writing URLs would put these records out of
step with every neighbouring record in the registry.

Within any record the skill touches, identifiers already present are re-rendered
in the configured form, so a file never mixes the two. That changes how a value
is written, never which value it is — normalising a format asserts nothing new,
unlike replacing an identifier, which never happens silently.

### Step 5 — Resolve the affiliation

`OrganizationName` has cardinality 1 — one value, required on every Person
record. The enricher may supply several separated by ` / ` or `; ` — both are
treated as separators.

- **Multiple affiliations:** keep the first, log the dropped remainder.
- **No affiliation, new record:** use `Unknown`. This is established registry
  practice and is the only way to emit a valid record.
- **No affiliation, existing record:** keep what is already there. Never
  overwrite a real value with the fallback.
- **Real affiliation, existing record:** overwrite, and log the before/after.
  The input carries the current affiliation; the registry value is often stale.

**Address, phone and fax are flagged, not moved.** `Address`, `PhoneNumber` and
`FaxNumber` describe where the person worked at the *previous* organisation — 451,
318 and 104 records carry them. The input never supplies replacements, so the
only choice is keep or remove, and that choice is not the writer's:

- Some `ORG CHANGE` lines are a **real move**. Pollock, SwRI to GSFC: the address
  and phone are now wrong.
- Many are a **renaming of the same employer**. `Institute of Geophysics and
  Planetary Physics ... University of California, Los Angeles` normalised to
  `University of California, Los Angeles` is the same building, and the address
  and phone remain correct.

Nothing in the input distinguishes them, so removing by default would destroy
correct data in the second class to fix the first. Leave them in place, and **say
so in the Note** — a curator reads the record, not the run log, so a caution that
lives only in terminal output is a caution nobody acts on:

```
Previously recorded in this record as 'Institute of Geophysics and Planetary
Physics ... University of California, Los Angeles'. The address, phone number,
fax number and email address in this record relate to that previous organization.

The organization name on display is from the person's ORCID employment history
(https://orcid.org/0000-0002-6847-4136). This affiliation was held while the
mission was operating.
```

Name only the fields the record actually holds. `--drop-stale-contacts` removes
them when a curator has confirmed a real move, and the sentence then names only
what remains.

`Email` is kept even then, and flagged separately as `EMAIL CHECK`. An address
often survives a move, and it is frequently the only way to reach the person —
deleting it costs more than an out-of-date phone number does.

This is deliberately unlike the ROR rule below. A ROR is a machine-resolvable
identifier *of the organisation string beside it*, so a changed string makes it
definitionally wrong. Contact details describe a person at a place, and a renamed
employer does not move anybody.

**`RORIdentifier` follows `OrganizationName`.** A ROR identifies the organisation
named beside it, so when the organisation changes the old ROR is no longer true
of that record. Two cases, and the second is the one that is easy to miss:

- **Input supplies a ROR** — replace, and log the change.
- **Input supplies none** — **remove** the existing ROR. Leaving it makes the
  record assert a specific institution that is not the one it names, which is
  worse than having no ROR at all: a consumer resolving the ID gets a confident,
  wrong answer.

Removing an identifier is normally forbidden, and this is the one exception. It
is not a retraction of curated data but the consequence of a change made in the
same edit — the ROR described the value being replaced. Log it as `ROR DROPPED`
so a reviewer sees the removal and can supply the right ID by hand.

A ROR is untouched when the organisation does not change.

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

**Record affiliation provenance in `Person/Note`, in plain English.** Where the
affiliation came from is part of what makes the record auditable — but the Note
is read by curators who have never seen this pipeline, so no internal vocabulary
reaches the record. Render `affiliation_source` and `affiliation_type` as
sentences:

```xml
<Note>Affiliation from the person's ORCID employment history (https://orcid.org/0000-0002-0494-2025). This affiliation was held while the mission was operating.</Note>
<Note>Affiliation as printed on the paper (Darnel et al. 2022, https://doi.org/10.1029/2022SW003044). This is the affiliation recorded at the time of publication.</Note>
```

**Cite papers the same way the Contact Notes do** — `(Author et al. Year, DOI)`,
not a bare DOI. Take the citation from `affiliation_evidence_citation` where the
enricher supplies it. Where it does not, fall back to a citation for the same DOI
found elsewhere in the candidate's evidence. Where neither exists, the DOI stands
alone — an author and year are never inferred from a DOI.

Never write the raw enumeration values — `as-deposited`, `era-matched`,
`Crossref (paper DOI)` — into a record. A value with no known rendering falls
through to its raw string rather than being dropped: an odd phrase is better than
a silent omission, and it signals that the mapping needs extending.

`Note` is cardinality 0..1 and sits between `ORCIdentifier` and `RORIdentifier`
in the Person sequence — not beside `ORCIdentifier`.

Write it whenever the input supplied a real affiliation, including when that
affiliation matched what the record already had: the provenance is true either
way. Do **not** write it when the input had no affiliation and the existing
`OrganizationName` was kept — that would attribute a curated value to a source
that did not produce it.

**Never lose what a curator wrote.** The Note is rebuilt from up to three parts,
in this order:

1. **Existing Note text this skill did not write** — preserved verbatim, first.
2. **Any `OrganizationName` this run replaced.** 347 Person records carry status
   inside that field — "Retired - formerly at Science and Exploration
   Directorate", "Deceased - formerly at GSFC". Replacing one with a plain
   organisation name does not merely lose detail; it asserts current employment
   for someone who has retired or died. The old value is recorded as
   `Previously recorded in this record as '...'.`
3. **This run's affiliation provenance**, phrased so it is clear which
   organisation it describes. Where a previous value is named in the paragraph
   above, the sentence opens "The organization name on display is ..." rather
   than "Affiliation ...", because the Note now mentions two organisations and
   the reader must not have to guess which one has the evidence behind it.

Paragraphs are separated by a blank line, which is what SPASE 2.7.1 section 3.4
treats as a break — a single newline renders as one run-on paragraph.

When the replaced value carried a person status, log `ORG STATUS` as well — the
Note preserves it, but a human should confirm the new value is right at all.

Rebuilding is idempotent: this skill's own segments are recognised and replaced
rather than appended to, so a re-run does not stack duplicates. Curated text is
never matched by that pattern and so is never removed.

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

### Role vocabulary — check legality before ordering

`Role` is a **closed enumeration** in SPASE 2.7.1. These are the only legal
values:

```
ArchiveSpecialist, Author, CoInvestigator, Contributor, CoPI, DataProducer,
DeputyPI, Developer, FormerPI, GeneralContact, HostContact, InstrumentLead,
InstrumentScientist, MetadataContact, MissionManager,
MissionPrincipalInvestigator, OperationsManager, PrincipalInvestigator,
ProgramManager, ProgramScientist, ProjectEngineer, ProjectManager,
ProjectScientist, Publisher, Scientist, TeamLeader, TeamMember,
TechnicalContact, User
```

Note what is **not** there: `InstrumentPrincipalInvestigator`. A record using it
will not validate.

The registry's convention resolves the mission/instrument ambiguity with two
existing terms rather than a new one: a PI of the mission is
`MissionPrincipalInvestigator`, and a PI of an instrument is `InstrumentLead`.
Bare `PrincipalInvestigator` says nothing about which, so upstream should stop
emitting it — but it stays in the precedence list, because 465 existing
Observatory records use it and those are not this skill's to rewrite.

Write the role the input gives — the finder and enricher are the authority on who
did what, and silently substituting a different role would misstate the evidence.
But log any value outside the enumeration loudly, because it is a schema failure
waiting to happen and the fix belongs upstream in the finder's vocabulary.

### Program Scientists: funding is not authorship, writing is

A Program Scientist is the agency official who signs and funds the mission — the
person who signed the SDO Project Data Management Plan as "Program Scientist
(HQ)", or is named Parker Solar Probe Program Scientist at NASA Headquarters.
The record lists that role, but signing and funding is not authorship of the
mission's data.

What decides it is **where the Author evidence comes from**:

- **Derived from the funding role** — "named Program Scientist on the team
  page". Not an author. `Author` is withheld even when the input lists it, and the
  person sits at the end of the list, since `ProgramScientist` ranks below
  `Author`. Logged `AUTHOR WITHHELD`.
- **Independent of it** — Goodman is the GOES-R Program Scientist *and* the sole
  author of the GOES-R Series Introduction chapter, the mission-overview
  reference. He is an author because he wrote it. `Author` is kept and he is
  placed among the authors, by what he authored rather than by his funding role.
  Logged `AUTHOR KEPT`.

The test is mechanical: the Author evidence must **cite a publication**, by DOI.
A team page, a signature on a plan or a programme listing does not. This relies on
the finder citing papers in the `(Author et al. Year, DOI)` form its skill
requires, so a Program Scientist who genuinely wrote something is recognised as
such.

The writer never *adds* `Author` to a funding-only person by default — the
default that applies to everyone else does not apply here. Someone who also holds
a role reflecting work on the mission (`ProjectScientist`, `InstrumentLead` and
so on) is not funding-only, and keeps `Author` in the usual way.

The Note only justifies roles actually written: evidence for a withheld role is
dropped, so it never contradicts the Role list above it.

### Role precedence

Contact blocks are ordered by each person's **highest-ranking role**, and the
`Role` elements inside a block follow the same order:

```
MissionPrincipalInvestigator, PrincipalInvestigator, ProjectScientist, CoPI,
DeputyPI, FormerPI, InstrumentLead, InstrumentScientist, CoInvestigator,
Author, ProgramScientist
```

`Author` ranks last, so people carrying only that role follow everyone with a
mission or instrument role. This puts the record's most senior contributors at
the top, where a reader looking for who ran the mission will find them.

**Within a rank, order by authorship scope.** People sharing a role rank are
ordered by what their authorship describes, taken from the finder's
`authorship_scope` field:

1. `observatory` — the mission as a whole: mission overview papers and chapters
2. `instrument` — one instrument's description paper
3. `component` — one part of an instrument, such as a single sensor in a suite

Goodman and Sullivan both wrote observatory-level chapters of the GOES-R
reference volume, so they come ahead of the SUVI, MAG, EXIS and SEISS paper
authors, even though all of them hold only the `Author` role.

A candidate without `authorship_scope` sorts after those with it. When no
candidate carries the field the order is exactly what it was before — so older
inputs are unaffected. An unrecognised value is logged as `SCOPE UNKNOWN` and
treated as unset.

Beyond that, people keep the order the finder produced — evidence strength and
author position — so the sort is stable rather than reshuffling the list.
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
elements above them**, and **as a SPASE list item on its own line** — a run-on string carrying two
or three justifications is unreadable in a diff or a rendered record. Single-entry Notes stay on one line.

**Use the SPASE text mark-up, not bare newlines.** Section 3.4 of the 2.7.1 spec
defines how a viewer interprets Note text, and a lone newline is not a break —
which is why plain indented continuation lines render as one run-on paragraph.
What a viewer does recognise is a list item: a line beginning `* `.

**Indent the items to sit under the tag.** Normalization strips leading
whitespace *before* the interpretation rules run, and the spec explicitly allows
white space "introduced in the form of indentation" to keep the XML readable. So
indentation costs nothing at render time and keeps the file aligned for anyone
reading the raw XML or a diff — where reviewers do most of their reading. Items
are indented one level past `<Note>`, and the closing tag returns to the level of
its siblings:

```xml
<Contact>
  <PersonID>spase://SMWG/Person/Howard.J.Singer</PersonID>
  <Role>PrincipalInvestigator</Role>
  <Role>Author</Role>
  <Note>
    * PrincipalInvestigator: GOES-16 MAG SPASE Instrument record Contacts (https://spase-metadata.org/SMWG/Instrument/GOES/16/MAG.html)
    * Author: MAG PrincipalInvestigator in the GOES-16 MAG SPASE record, corroborated by the record Acknowledgement and MAG description-paper co-authorship
  </Note>
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

### Step 7b — Write InformationURL entries

Reference links — description papers, mission pages, CMADs — come from the
input's `information_urls` block and are transcribed into `InformationURL`
elements:

```xml
<InformationURL>
  <Name>GOES-R Series Introduction</Name>
  <URL>https://doi.org/10.1016/b978-0-12-814327-8.00001-9</URL>
  <Description>Mission overview chapter of the GOES-R Series reference volume.</Description>
</InformationURL>
```

`Name` and `URL` are required; `Description` is optional but expected — 776 of
the 852 existing entries carry one. Placement is after `Contact` and before
`Association`: append after the last existing `InformationURL`, or after the last
`Contact` when the record has none.

**Scope decides which record a link belongs to, and the input declares it.**
Observatory-level references — mission overview papers, mission home pages,
programme team pages, mission-wide CMADs — go on the Observatory record.
Instrument-level references — instrument description papers, per-instrument CMAD
chapters — go on that instrument's record, never on the mission's.

The writer takes the scope from each entry's `scope` field and matches it against
the target record's own type, which it derives from the ResourceID. It does not
infer scope from the URL, the title, or surrounding prose: a paper titled for an
instrument may still be the mission's overview reference, and guessing wrong
misattributes the link. An entry whose scope does not match is left for the
record it belongs to and logged as `URL DEFERRED`; an entry with no scope at all
is skipped and logged, never assumed.

Skip a URL already present in the record — comparison ignores case, a trailing
slash and the `http`/`https` scheme — and log it as `URL PRESENT` rather than
writing a second copy. When the copy already there is written differently, the
log names it (`already in the record as http://…`). The existing entry is kept as
curated, even if its Name or Description is wrong; that is a curator item, not
something to replace.

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

**Never lower a Version.** A record that already declares a newer Version
(2.7.2, say) keeps its Version and schemaLocation exactly as they are: a newer
schema already holds every element the writer adds, and rewriting it to 2.7.1
would be a silent downgrade that still validates, so nobody would notice it. Log it
as `VERSION KEPT`. If the target record itself is the newer one, the
RevisionEvent note leaves out the schemaLocation clause, since nothing was
corrected.

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

### Step 9b — Link the artifacts, pinned to a commit

The RevisionEvent documents this edit, so it is where the provenance of the edit
belongs. Append a link to the candidate and enrichment files that produced it:

```
... corrected schemaLocation to match the declared SPASE Version. Candidate and
enrichment files: https://github.com/<owner>/<repo>/tree/62b74df/spase_records/SOHO. DS
```

**The URL must name a commit, never a branch.** A `/tree/main/...` link resolves
to whatever is in that folder when someone clicks it. Records get re-enriched —
and runs disagree — so a branch link will eventually show values the record does
not contain, while looking like corroboration. A commit hash names one immutable
snapshot: the artifacts that produced this version of this record.

The pipeline derives the URL from the input file's own repository, so no hash is
copied by hand. It uses the last commit touching the record's artifact folder,
not repository HEAD, so the link is precise even when other work has landed since.

It refuses to guess when the link would be wrong:

- **uncommitted changes in the folder** — the link would not show what was used
- **commit not on any remote** — the link would 404
- **origin is not a GitHub remote** — no URL can be built

Each aborts with the reason and rolls the run back. `--artifacts-url` supplies
one explicitly; `--no-artifacts-url` omits the link.

This puts a new ordering on the run: commit and push the enricher output first,
then write the record. That sequence is what makes the link meaningful — the
artifacts have to exist publicly before a record can point at them.

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
enrichment are appended to the template as undecided rather than assumed;
everything already in the file — rulings, `_rationale`, earlier `_candidates` —
is kept.

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