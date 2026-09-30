#!/usr/bin/env python3
"""
write_records.py -- apply enriched author candidates to a local SMWG clone.

Reads the spase-affiliation-enricher output and writes:
  * Contact blocks into the target Observatory (or Instrument) record
  * new Person records for candidates with no existing record
  * in-place field updates to existing Person records

Edits are MINIMAL: existing files keep their indentation, field order and
untouched content, so reviewers see only semantic changes.

Usage:
    python3 write_records.py --repo ~/SMWG --input .../author_candidates_enriched.json
    python3 write_records.py --repo ~/SMWG --input ... --dry-run
    python3 write_records.py --repo ~/SMWG --input ... --link "B. K. Dichter=Bronislaw.K.Dichter"

Exit codes: 0 written, 1 aborted (no files changed), 2 usage error.
"""

import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone

SCHEMA_LOC = ("https://www.spase-group.org/data/schema "
              "https://www.spase-group.org/data/schema/spase-2.7.1.xsd")
TARGET_VERSION = "2.7.1"
UNKNOWN_ORG = "Unknown"

# Curator-defined precedence. Contact blocks are ordered by each person's
# highest-ranking role, and the Role elements inside a block follow the same
# order. Roles outside this list sort last and are logged.
ROLE_PRECEDENCE = [
    "MissionPrincipalInvestigator",
    "PrincipalInvestigator",
    "ProjectScientist",
    "CoPI",
    "DeputyPI",
    "FormerPI",
    "InstrumentLead",
    "InstrumentScientist",
    "CoInvestigator",
    "Author",
    # Last, and deliberately below Author: a Program Scientist is the agency
    # official who signs and funds the mission, not a contributor to its data.
    "ProgramScientist",
]

# Roles that credit a person without making them an author. Someone holding
# only these -- no role that reflects work on the mission itself -- is listed
# but not given the Author role.
NON_AUTHOR_ROLES = {"ProgramScientist"}

# Within a role rank, people are ordered by what their authorship describes:
# the mission as a whole before one instrument, one instrument before a single
# component of it. Supplied by the finder as authorship_scope; a candidate
# without it sorts after those with it, and when no candidate carries it the
# order is exactly what it was before.
SCOPE_RANK = {"observatory": 0, "instrument": 1, "component": 2}
SCOPE_UNSET = len(SCOPE_RANK)
ROLE_RANK = {r: i for i, r in enumerate(ROLE_PRECEDENCE)}

# The closed Role enumeration in SPASE 2.7.1. A role outside this set is still
# written -- the input is the authority on who did what -- but it will fail
# schema validation, so it is logged prominently.
SPASE_271_ROLES = {
    "ArchiveSpecialist", "Author", "CoInvestigator", "Contributor", "CoPI",
    "DataProducer", "DeputyPI", "Developer", "FormerPI", "GeneralContact",
    "HostContact", "InstrumentLead", "InstrumentScientist", "MetadataContact",
    "MissionManager", "MissionPrincipalInvestigator", "OperationsManager",
    "PrincipalInvestigator", "ProgramManager", "ProgramScientist",
    "ProjectEngineer", "ProjectManager", "ProjectScientist", "Publisher",
    "Scientist", "TeamLeader", "TeamMember", "TechnicalContact", "User",
}
UNRANKED = len(ROLE_PRECEDENCE)

# SPASE 2.7.1 Person child order -- insertion points are derived from this.
PERSON_ORDER = [
    "ResourceID", "NamingAuthority", "ResourceType", "ReleaseDate",
    "PersonName", "OrganizationName", "Address", "Email", "PhoneNumber",
    "FaxNumber", "ORCIdentifier", "Note", "RORIdentifier", "Extension",
]

NICKNAMES = {
    "terrance": "terry", "terence": "terry", "robert": "bob",
    "william": "bill", "richard": "dick", "james": "jim",
    "michael": "mike", "thomas": "tom", "daniel": "dan",
    "joseph": "joe", "christopher": "chris", "edward": "ed",
    "kenneth": "ken", "ronald": "ron", "donald": "don",
    "stephen": "steve", "steven": "steve", "anthony": "tony",
    "charles": "charlie", "matthew": "matt", "nicholas": "nick",
    "benjamin": "ben", "samuel": "sam", "patrick": "pat",
    "francis": "frank", "gregory": "greg", "jeffrey": "jeff",
}


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Registry convention: identifiers are written bare (124 of 126 existing
# ORCIdentifier values and all 141 RORIdentifier values are). Set to "url" to
# write resolvable URLs instead -- but only on a curator's instruction, since it
# would put these records out of step with the rest of the registry.
IDENTIFIER_FORM = "bare"

ORCID_BASE = "https://orcid.org/"
ROR_BASE = "https://ror.org/"


def _norm_identifier(v, base):
    """Return the identifier in the configured form, either way round."""
    if not v:
        return None
    v = v.strip()
    bare = re.sub(r"^https?://[^/]+/", "", v)
    return (base + bare) if IDENTIFIER_FORM == "url" else bare


def _same_identifier(a, b):
    """True when two identifiers differ only in bare-vs-URL form."""
    strip = lambda v: re.sub(r"^https?://[^/]+/", "", (v or "").strip())
    return bool(a) and strip(a) == strip(b)


def bare_orcid(v):
    return _norm_identifier(v, ORCID_BASE)


def bare_ror(v):
    return _norm_identifier(v, ROR_BASE)


def primary_affiliation(v):
    """OrganizationName is single-valued; keep the first listed."""
    if not v or not v.strip():
        return None
    return v.split(" / ")[0].strip()


def mint_id(name):
    """'Paul T. M. Loto'aniu' -> Paul.T.M.Lotoaniu (apostrophes stripped)."""
    cleaned = re.sub(r"[^A-Za-z. ]", "", name)
    toks = [t.strip(".") for t in cleaned.split() if t.strip(".")]
    return ".".join(toks)


DOI_IN_TEXT = re.compile(r"(?<![\w/.])(10\.\d{4,9}/[^\s,;)\]<]+)")


def doi_url(value):
    """Bare DOI -> resolver URL. Anything already a URL passes through."""
    v = (value or "").strip()
    if not v:
        return v
    if v.lower().startswith(("http://", "https://")):
        return v
    if v.startswith("10."):
        return "https://doi.org/" + v
    return v


def linkify_dois(text):
    """Prefix bare DOIs inside free text so a reviewer can click them.

    The lookbehind keeps DOIs that are already part of a URL untouched. Only a
    prefix is added -- the identifier itself is never altered, so the note still
    reproduces exactly what the input said.
    """
    if not text:
        return text
    return DOI_IN_TEXT.sub(
        lambda m: "https://doi.org/" + m.group(1).rstrip("."), text)


# Plain-English renderings of the enricher's controlled vocabulary. The Note is
# read by curators who have never seen the pipeline, so no internal term reaches
# the record. Unknown values fall through to the raw string rather than being
# dropped -- a reader seeing an odd phrase is better than a reader seeing nothing.
AFFIL_SOURCE_PHRASE = {
    "Crossref (paper DOI)": "as printed on the paper",
    "ORCID employment": "from the person's ORCID employment history",
    "ORCID name-search (corroborated)": "from the person's ORCID record",
    "provider documentation": "from the data provider's own documentation",
    "SPASE record": "from an existing SPASE record",
    "uncorroborated": "reported but not confirmed against an independent source",
}

# Contact fields whose value describes the organisation, named in plain words.
CONTACT_FIELD_WORDS = [
    ("Address", "address"),
    ("PhoneNumber", "phone number"),
    ("FaxNumber", "fax number"),
    ("Email", "email address"),
]


def join_words(words):
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


AFFIL_TYPE_PHRASE = {
    "as-deposited": "This is the affiliation recorded at the time of publication",
    "era-matched": "This affiliation was held while the mission was operating",
    "current": "This is the person's current or most recent affiliation",
}


CITATION_RE = re.compile(
    r"\(([^()]*?\b(?:19|20)\d{2}[^()]*?),\s*(10\.[^\s,()]+?)\)")


def find_citation(candidate, doi):
    """Recover '(Author et al. Year, DOI)' for a DOI already cited elsewhere in
    this candidate, so the affiliation Note matches the Contact Note style.

    The enricher supplies affiliation_evidence as a bare DOI. Where the same DOI
    is cited in the candidate's evidence with an author and year, that citation is
    reused; where it is not, the DOI stands alone rather than being invented.
    """
    if not doi or not doi.startswith("10."):
        return None
    want = doi.lower().rstrip(".")
    pool = [e.get("source", "") for e in (candidate.get("role_evidence") or [])]
    pool += [e.get("source", "") for e in (candidate.get("evidence") or [])]
    for text in pool:
        for m in CITATION_RE.finditer(text or ""):
            if m.group(2).lower().rstrip(".") == want:
                return m.group(1).strip()
    return None


def build_person_note(candidate, lead=None):
    """Person/Note records where the affiliation came from, in plain English.

    Only the provenance of OrganizationName -- what supports it, and what period
    it refers to. The enricher's full reasoning belongs in the run log, not the
    registry. affiliation_origin is pipeline bookkeeping and is not written: a
    curator cares which evidence supports the value, not which stage proposed it.
    """
    e = candidate.get("enrichment") or {}
    src = (e.get("affiliation_source") or "").strip()
    raw_ev = (e.get("affiliation_evidence") or "").strip()
    # Prefer the enricher's own citation; fall back to one recovered from the
    # candidate's other evidence; never infer an author or year from a DOI.
    cite = (e.get("affiliation_evidence_citation") or "").strip() \
        or find_citation(candidate, raw_ev)
    ev = doi_url(raw_ev)
    if cite and ev:
        ev = "%s, %s" % (cite, ev)
    typ = (e.get("affiliation_type") or "").strip()

    # Legacy outputs conflated origin and evidence into the source string.
    if src.startswith("finder (pre-existing"):
        src = "uncorroborated" if src == "finder (pre-existing)" else ""

    if not src and not typ:
        return None

    first = lead or "Affiliation"
    if src:
        first += " " + AFFIL_SOURCE_PHRASE.get(src, src)
    if ev:
        first += " (%s)" % ev
    first += "."

    second = AFFIL_TYPE_PHRASE.get(typ)
    if typ and not second:
        second = "Affiliation period: %s" % typ
    return first + (" " + second + "." if second else "")


# Segments this skill writes into a Person Note. Recognising them lets a re-run
# rebuild the Note instead of appending to its own previous output.
OURS_RE = re.compile(
    r"(?:"
    r"Previously recorded in this record as [^\n]*?\."
    r"|The [a-z ,]*?(?:address|phone number|fax number|email address)[^\n]*?"
    r"previous(?:ly recorded)? organi[sz]ation\."
    r"|(?:Affiliation|The organization name on display is)\b[^.]*?\."
    r"(?:\s*(?:This is|This affiliation)[^.]*?\.)?"
    r")\s*", re.S)

STATUS_RE = re.compile(r"\b(retired|deceased|emeritus|formerly|no longer)\b", re.I)


def split_curated(note):
    """Return the part of an existing Note this skill did not write."""
    if not note:
        return ""
    return OURS_RE.sub("", note).strip()


OUR_NOTE_PREFIX = "Affiliation source:"


def build_note(candidate, indent="          ", close_indent="        "):
    """Contact/Note holds the role evidence.

    Note has cardinality 0..1, so several role_evidence entries are folded into
    one value -- each labelled with the role it supports and placed on its own
    line, because a single run-on string is unreadable once it carries two or
    three justifications.

    Accepts the older plain-string form of role_evidence too.
    """
    ev = candidate.get("role_evidence")
    if not ev:
        return None
    if isinstance(ev, str):
        return linkify_dois(ev.strip()) or None
    entries = [e for e in ev
               if isinstance(e, dict) and (e.get("source") or "").strip()]
    if not entries:
        return None
    if len(entries) == 1:
        return linkify_dois(entries[0]["source"].strip())
    # Same precedence as the Role elements, so the Note reads in the order the
    # roles are listed above it rather than in the enricher's emission order.
    entries = sorted(
        entries,
        key=lambda e: (ROLE_RANK.get((e.get("role") or "").strip(), UNRANKED),
                       (e.get("role") or "").strip()))
    # SPASE 2.7.1 section 3.4: a bare newline is not a break -- a list item is a
    # line beginning "* ". Normalization strips leading whitespace before the
    # interpretation rules run, and the spec explicitly allows indentation added
    # for XML readability, so the items are indented to sit under the tag and
    # still render as a list.
    items = ("\n" + indent).join(
        "* %s: %s" % ((e.get("role") or "Role").strip(),
                      linkify_dois(e["source"].strip()))
        for e in entries)
    return "\n" + indent + items + "\n" + close_indent


# --------------------------------------------------------------------------
# duplicate detection
# --------------------------------------------------------------------------

def build_person_index(repo):
    ids = [f[:-4] for f in os.listdir(os.path.join(repo, "Person"))
           if f.endswith(".xml")]
    by_sur = {}
    for pid in ids:
        parts = pid.split(".")
        sur = parts[-1].lower()
        if sur in ("jr", "sr", "ii", "iii") and len(parts) > 1:
            sur = parts[-2].lower()
        by_sur.setdefault(sur, []).append(pid)
    return ids, by_sur


def find_collisions(name, ids, by_sur):
    """Return existing Person IDs that may be the same human."""
    toks = [t for t in name.split() if t]
    if not toks:
        return []
    sur = re.sub(r"[^a-z]", "", toks[-1].lower())
    hits = list(by_sur.get(sur, []))
    if not hits:
        flat = re.sub(r"[^a-z]", "", name.lower())
        close = difflib.get_close_matches(
            flat, [re.sub(r"[^a-z]", "", i.lower()) for i in ids],
            n=3, cutoff=0.85)
        hits = [i for i in ids if re.sub(r"[^a-z]", "", i.lower()) in close]
    # rank: nickname-aware given-name agreement first
    given = re.sub(r"[^a-z]", "", toks[0].lower())
    alt = NICKNAMES.get(given, "")
    def score(pid):
        first = pid.split(".")[0].lower()
        if first == given or first == alt:
            return 0
        if len(given) == 1 and first.startswith(given):
            return 1
        if len(first) == 1 and given.startswith(first):
            return 1
        return 2
    return sorted(hits, key=score)


# --------------------------------------------------------------------------
# Person record read / minimal write
# --------------------------------------------------------------------------

def read_person(path):
    txt = open(path, encoding="utf-8").read()
    fields = {}
    for m in re.finditer(r"<([A-Za-z]+)>([^<]*)</\1>", txt):
        fields.setdefault(m.group(1), []).append(m.group(2).strip())
    return txt, fields


def detect_indent(txt, tag):
    m = re.search(r"^([ \t]*)<%s>" % tag, txt, re.M)
    return m.group(1) if m else "    "


def set_field(txt, tag, value):
    """Replace tag's text if present, else insert at schema-correct position."""
    if re.search(r"<%s>[^<]*</%s>" % (tag, tag), txt):
        return re.sub(r"<%s>[^<]*</%s>" % (tag, tag),
                      "<%s>%s</%s>" % (tag, esc(value), tag), txt, count=1)

    idx = PERSON_ORDER.index(tag)
    # insert after the last existing element that precedes it
    for prev in reversed(PERSON_ORDER[:idx]):
        m = list(re.finditer(r"^([ \t]*)<%s>.*?</%s>[ \t]*$" % (prev, prev),
                             txt, re.M | re.S))
        if m:
            last = m[-1]
            ind = last.group(1)
            return (txt[:last.end()] +
                    "\n%s<%s>%s</%s>" % (ind, tag, esc(value), tag) +
                    txt[last.end():])
    # else insert before the first element that follows it
    for nxt in PERSON_ORDER[idx + 1:]:
        m = re.search(r"^([ \t]*)<%s>" % nxt, txt, re.M)
        if m:
            ind = m.group(1)
            return (txt[:m.start()] +
                    "%s<%s>%s</%s>\n" % (ind, tag, esc(value), tag) +
                    txt[m.start():])
    return txt


def existing_urls(txt):
    """Every URL already present in the record, normalised for comparison."""
    out = set()
    for u in re.findall(r"<URL>([^<]*)</URL>", txt):
        out.add(u.strip().rstrip("/").lower())
    return out


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def build_information_urls(data, target_scope, txt):
    """Transcribe scope-matching entries from the input's information_urls.

    Scope is the input's to declare, never the writer's to infer: an observatory
    record takes observatory-level references, an instrument record takes its
    own. An entry with no scope is skipped and logged rather than guessed at,
    because putting an instrument paper on a mission record misattributes it.
    """
    blocks, log = [], []
    have = existing_urls(txt)
    for item in (data.get("information_urls") or []):
        url = (item.get("url") or "").strip()
        name = (item.get("name") or "").strip()
        scope = (item.get("scope") or "").strip().lower()
        desc = (item.get("description") or "").strip()
        if not url or not name:
            log.append("URL SKIPPED  incomplete entry (needs name and url): %r"
                       % (url or name))
            continue
        if not scope:
            log.append("URL SKIPPED  %s has no scope; not added" % url)
            continue
        if scope != target_scope:
            log.append("URL DEFERRED %s is %s-level, not written to this "
                       "%s record" % (url, scope, target_scope))
            continue
        if norm_url(url) in have:
            log.append("URL PRESENT  %s already in the record" % url)
            continue
        have.add(norm_url(url))
        b = ["      <InformationURL>",
             "        <Name>%s</Name>" % esc(name),
             "        <URL>%s</URL>" % esc(url)]
        if desc:
            b.append("        <Description>%s</Description>" % esc(desc))
        b.append("      </InformationURL>")
        blocks.append("\n".join(b))
    return blocks, log


def drop_field(txt, tag):
    """Remove every occurrence of an element, and its line, from a record."""
    return re.sub(r"^[ \t]*<%s>.*?</%s>[ \t]*\n" % (tag, tag), "", txt,
                  flags=re.M | re.S)


def bump_schema(txt):
    txt = re.sub(r'xsi:schemaLocation="[^"]*"',
                 'xsi:schemaLocation="%s"' % SCHEMA_LOC, txt, count=1)
    txt = re.sub(r"<Version>[^<]*</Version>",
                 "<Version>%s</Version>" % TARGET_VERSION, txt, count=1)
    return txt


def new_person_xml(pid, name, org, orcid, ror, stamp, note=None):
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             '<Spase xmlns="http://www.spase-group.org/data/schema" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:schemaLocation="%s">' % SCHEMA_LOC,
             "  <Version>%s</Version>" % TARGET_VERSION,
             "  <Person>",
             "    <ResourceID>spase://SMWG/Person/%s</ResourceID>" % pid,
             "    <NamingAuthority>SMWG</NamingAuthority>",
             "    <ResourceType>Person</ResourceType>",
             "    <ReleaseDate>%s</ReleaseDate>" % stamp,
             "    <PersonName>%s</PersonName>" % esc(name),
             "    <OrganizationName>%s</OrganizationName>" % esc(org)]
    if orcid:
        lines.append("    <ORCIdentifier>%s</ORCIdentifier>" % orcid)
    if note:
        lines.append("    <Note>%s</Note>" % esc(note))
    if ror:
        lines.append("    <RORIdentifier>%s</RORIdentifier>" % ror)
    lines += ["  </Person>", "</Spase>", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="local SMWG clone root")
    ap.add_argument("--input", required=True, help="author_candidates_enriched.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--link", action="append", default=[],
                    metavar="NAME=PersonID",
                    help="confirmed match for a candidate the finder left unlinked")
    ap.add_argument("--create", action="append", default=[], metavar="NAME",
                    help="confirm a candidate is NOT a flagged collision; mint a new ID")
    ap.add_argument("--decisions", default=None, metavar="PATH",
                    help="JSON file of persistent link/create decisions. "
                         "Written as a template on first abort.")
    ap.add_argument("--drop-stale-contacts", action="store_true",
                    help="when OrganizationName changes, also remove Address, "
                         "PhoneNumber and FaxNumber, which describe the previous "
                         "organisation. Off by default: many changes rename the "
                         "same employer, where those details are still correct.")
    ap.add_argument("--artifacts-url", default=None,
                    help="commit-pinned URL for the candidate and enrichment "
                         "files, appended to the RevisionEvent note")
    ap.add_argument("--note", default=None, help="RevisionEvent note")
    ap.add_argument("--initials", default="", help="curator initials for the note")
    args = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(args.repo))
    data = json.load(open(os.path.expanduser(args.input), encoding="utf-8"))
    stamp = now_stamp()

    overrides = {}
    confirmed_new = set()
    if args.decisions and os.path.isfile(os.path.expanduser(args.decisions)):
        dec = json.load(open(os.path.expanduser(args.decisions), encoding="utf-8"))
        for k, v in (dec.get("links") or {}).items():
            if v:
                overrides[k.strip()] = v.strip()
        confirmed_new |= {n.strip() for n in (dec.get("creates") or [])}

    for pair in args.link:
        if "=" not in pair:
            print("bad --link (need NAME=PersonID): %s" % pair)
            return 2
        k, v = pair.split("=", 1)
        overrides[k.strip()] = v.strip()
    confirmed_new |= {n.strip() for n in args.create}

    # ---- resolve the target record ---------------------------------------
    rid = data.get("record", "")
    if not rid.startswith("spase://"):
        print("input has no usable 'record' field")
        return 2
    authority, rest = rid[len("spase://"):].split("/", 1)
    target = os.path.join(repo, rest + ".xml")
    if not os.path.isfile(target):
        print("ABORT: target record not found: %s" % target)
        print("  ResourceID %s resolves outside this clone." % rid)
        print("  Check the naming authority -- the record may live in another repo.")
        return 1

    included = [c for c in data["candidates"] if c.get("status") == "included"]
    if not included:
        print("ABORT: no included candidates")
        return 1

    ids, by_sur = build_person_index(repo)
    contacts, creates, updates, log, blockers = [], [], [], [], []
    written_ids = set()

    for c in included:
        name = c["name"]
        linked = (c.get("person_record") or {}).get("id") or ""
        pid = linked.replace("spase://SMWG/Person/", "")

        if name in overrides:
            pid = overrides[name]
            log.append("LINK       %s -> %s (confirmed by curator)" % (name, pid))

        if not pid:
            pid = mint_id(name)

        # The collision check belongs to CREATING a record, not to how the ID was
        # arrived at. An ID asserted by the input is a claim about which file
        # should exist, not proof that it does -- so an asserted ID with no file
        # behind it gets the same scrutiny as a minted one. Gating this on
        # "no person_record.id" let asserted IDs through unchecked, which is the
        # exact path to a silent duplicate.
        if not os.path.isfile(os.path.join(repo, "Person", pid + ".xml")):
            hits = [h for h in find_collisions(name, ids, by_sur) if h != pid]
            if hits and name not in confirmed_new:
                blockers.append((name, hits[:4]))
                continue
            conventional = mint_id(name)
            if pid != conventional:
                log.append("ID SHAPE   %s: minting '%s' for '%s'; the "
                           "conventional form is '%s'"
                           % (pid, pid, name, conventional))
            elif pid != name.replace(" ", "."):
                log.append("MINT       %s -> %s" % (name, pid))

        orcid = bare_orcid(c.get("orcid"))
        ror = bare_ror(c.get("affiliation_ror"))
        org = primary_affiliation(c.get("affiliation"))
        if c.get("affiliation") and " / " in c["affiliation"]:
            log.append("MULTI-AFF  %s kept '%s', dropped '%s'"
                       % (name, org, c["affiliation"].split(" / ", 1)[1]))

        path = os.path.join(repo, "Person", pid + ".xml")

        if os.path.isfile(path):
            txt, fields = read_person(path)
            before = txt
            existing_org = (fields.get("OrganizationName") or [""])[0]
            replaced_org = ""

            # RULE: never overwrite a real value with the Unknown fallback.
            if org and org != existing_org:
                if existing_org and existing_org != UNKNOWN_ORG:
                    replaced_org = existing_org
                    log.append("ORG CHANGE %s: '%s' -> '%s'"
                               % (pid, existing_org, org))
                txt = set_field(txt, "OrganizationName", org)
                # RULE: OrganizationName and RORIdentifier move together. A ROR
                # identifies the organisation named beside it, so when the
                # organisation changes the old ROR is no longer true of this
                # record. Replace it when the input has one; REMOVE it when the
                # input has none, rather than leaving a stale ID attached to an
                # organisation it does not identify.
                existing_ror = (fields.get("RORIdentifier") or [""])[0]
                if ror:
                    if existing_ror and existing_ror != ror:
                        log.append("ROR CHANGE %s: '%s' -> '%s' (follows org)"
                                   % (pid, existing_ror, ror))
                    txt = set_field(txt, "RORIdentifier", ror)
                elif existing_ror:
                    txt = drop_field(txt, "RORIdentifier")
                    log.append("ROR DROPPED %s: '%s' identified the previous "
                               "organisation and the input supplies none; "
                               "removed rather than left stale"
                               % (pid, existing_ror))
            elif not org and existing_org:
                log.append("ORG KEPT   %s: no affiliation in input, kept '%s'"
                           % (pid, existing_org))

            existing_orcid = (fields.get("ORCIdentifier") or [""])[0]
            if orcid and not existing_orcid:
                txt = set_field(txt, "ORCIdentifier", orcid)
            elif orcid and _same_identifier(existing_orcid, orcid):
                pass  # same iD, form normalised below
            elif orcid and existing_orcid != orcid:
                log.append("ORCID CLASH %s: repo=%s input=%s (kept repo)"
                           % (pid, existing_orcid, orcid))

            # Keep one record internally consistent: an identifier already in the
            # file is re-rendered in the configured form. This changes how the
            # value is written, never which value it is, so it asserts nothing
            # new -- it just avoids a bare iD sitting beside a URL-form ROR.
            for tag, base in (("ORCIdentifier", ORCID_BASE),
                              ("RORIdentifier", ROR_BASE)):
                for cur in (fields.get(tag) or []):
                    want = _norm_identifier(cur, base)
                    if cur and want and cur != want:
                        txt = set_field(txt, tag, want)
                        log.append("FORM %s: %s rewritten as %s"
                                   % (pid, tag, IDENTIFIER_FORM))

            # PersonName is optional in the schema but present on all but a
            # handful of records. Backfill when missing; never overwrite, since
            # registry names carry honorifics and forms the input does not.
            if not (fields.get("PersonName") or [""])[0].strip():
                txt = set_field(txt, "PersonName", name)
                log.append("NAME ADDED %s: PersonName was missing, set to '%s'"
                           % (pid, name))

            # The Note is rebuilt from three parts, so nothing a curator wrote
            # is lost and a re-run does not append to its own output:
            #   1. whatever a human put there, preserved verbatim and first
            #   2. any OrganizationName this run replaced -- 347 records carry
            #      status such as "Retired - formerly at ..." in that field, and
            #      dropping it would assert current employment that has ended
            #   3. this run's affiliation provenance
            # The Note is what a curator actually reads, so what they need to
            # act on goes here, not only into the run log. Up to three
            # paragraphs:
            #   1. whatever a human wrote, preserved verbatim and first
            #   2. the OrganizationName this run replaced, and which contact
            #      fields still describe it -- 451 records carry an Address, and
            #      after an org change it belongs to the previous employer
            #   3. where the organisation now shown came from
            curated = split_curated((fields.get("Note") or [""])[0])
            paras = []
            if curated:
                paras.append(curated.rstrip())

            if replaced_org:
                sent = ["Previously recorded in this record as '%s'." % replaced_org]
                kept = [w for t, w in CONTACT_FIELD_WORDS
                        if fields.get(t) and not (args.drop_stale_contacts
                                                  and t != "Email")]
                if kept:
                    sent.append("The %s in this record %s that previous "
                                "organization."
                                % (join_words(kept),
                                   "relates to" if len(kept) == 1 else "relate to"))
                paras.append(" ".join(sent))
                if STATUS_RE.search(replaced_org):
                    log.append("ORG STATUS %s: replaced value carried a person "
                               "status ('%s') -- preserved in the Note, but "
                               "verify the new value is right"
                               % (pid, replaced_org))

            lead = "The organization name on display is" if replaced_org else None
            pnote = build_person_note(c, lead=lead)
            if pnote and org:
                paras.append(pnote)

            if paras:
                if len(paras) > 1:
                    body = ("\n\n          ").join(paras)
                    joined = "\n          " + body + "\n        "
                else:
                    joined = paras[0]
                if joined != (fields.get("Note") or [""])[0]:
                    txt = set_field(txt, "Note", joined)
                if curated:
                    log.append("NOTE KEPT  %s: existing Note preserved and "
                               "appended to" % pid)

            # Address, PhoneNumber and FaxNumber describe where the person
            # worked at the PREVIOUS organisation. The input never supplies
            # replacements, so the choice is keep or remove -- and it is not the
            # writer's to make: an ORG CHANGE may be a real move, where those
            # details are now wrong, or a renaming of the same employer, where
            # they remain correct. Flag by default; remove only when told.
            if replaced_org:
                stale = [t for t in ("Address", "PhoneNumber", "FaxNumber")
                         if fields.get(t)]
                if stale and args.drop_stale_contacts:
                    for t in stale:
                        txt = drop_field(txt, t)
                    log.append("CONTACT DROP %s: removed %s -- described the "
                               "previous organisation" % (pid, ", ".join(stale)))
                elif stale:
                    log.append("CONTACT CHECK %s: record still holds %s from "
                               "'%s'; verify against the new organisation, or "
                               "re-run with --drop-stale-contacts"
                               % (pid, ", ".join(stale), replaced_org))
                if fields.get("Email"):
                    log.append("EMAIL CHECK  %s: '%s' may belong to the previous "
                               "organisation; kept, since an address often "
                               "outlives a move" % (pid, fields["Email"][0]))

            existing_ror_now = (fields.get("RORIdentifier") or [""])[0]
            if ror and not existing_ror_now:
                txt = set_field(txt, "RORIdentifier", ror)
            elif ror and not replaced_org and existing_ror_now != ror:
                # The organisation did not change, so the existing ROR stands --
                # but the record now holds a ROR the input disagrees with, and a
                # silent disagreement is the kind a reviewer never sees.
                log.append("ROR KEPT   %s: record has '%s', input says '%s'; "
                           "organisation unchanged so the record value stands"
                           % (pid, existing_ror_now, ror))

            if txt != before:
                txt = bump_schema(txt)
                txt = set_field(txt, "ReleaseDate", stamp)
                txt = set_field(txt, "NamingAuthority", "SMWG")
                txt = set_field(txt, "ResourceType", "Person")
                if not args.dry_run:
                    open(path, "w", encoding="utf-8").write(txt)
                updates.append(pid)
        else:
            if not org:
                org = UNKNOWN_ORG
                log.append("NO AFFIL   %s -> OrganizationName=Unknown" % name)
            if not args.dry_run:
                open(path, "w", encoding="utf-8").write(
                    new_person_xml(pid, name, org, orcid, ror, stamp,
                                   build_person_note(c)))
            creates.append(pid)

        roles = list(c.get("qualifying_roles") or ["Author"])
        work_roles = [r for r in roles
                      if r != "Author" and r not in NON_AUTHOR_ROLES]
        funding_only = (any(r in NON_AUTHOR_ROLES for r in roles)
                        and not work_roles)
        if funding_only:
            # A Program Scientist signs and funds the mission. That alone does
            # not make them an author, so Author is never added by default. But
            # a Program Scientist who actually WROTE something about the mission
            # is an author on that basis -- so an Author role the input supplies
            # is kept when its evidence cites a publication, and withheld when it
            # merely restates the funding role.
            author_ev = [e.get("source", "") for e in
                         (c.get("role_evidence") or [])
                         if isinstance(e, dict) and e.get("role") == "Author"]
            wrote = any(DOI_IN_TEXT.search(x) for x in author_ev)
            if "Author" in roles and wrote:
                log.append("AUTHOR KEPT %s: ProgramScientist with authorship "
                           "evidence that cites a publication" % pid)
            elif "Author" in roles:
                roles = [r for r in roles if r != "Author"]
                log.append("AUTHOR WITHHELD %s: ProgramScientist whose Author "
                           "evidence cites no publication%s"
                           % (pid, ("; set aside: " + " | ".join(author_ev))
                              if author_ev else ""))
        elif "Author" not in roles:
            roles = ["Author"] + roles
        for r in roles:
            if r not in ROLE_RANK:
                log.append("ROLE UNRANKED %s: '%s' is not in the precedence "
                           "list; sorted last" % (pid, r))
            if r not in SPASE_271_ROLES:
                log.append("ROLE INVALID %s: '%s' is NOT in the SPASE 2.7.1 "
                           "Role enumeration; this record will fail schema "
                           "validation" % (pid, r))
        roles.sort(key=lambda r: (ROLE_RANK.get(r, UNRANKED), r))
        rank = min(ROLE_RANK.get(r, UNRANKED) for r in roles)

        block = ["      <Contact>",
                 "        <PersonID>spase://SMWG/Person/%s</PersonID>" % pid]
        block += ["        <Role>%s</Role>" % r for r in roles]
        # The Note justifies the roles actually written; evidence for a role
        # this Contact does not carry would contradict the Role list above it.
        c_for_note = dict(c)
        if isinstance(c.get("role_evidence"), list):
            c_for_note["role_evidence"] = [
                e for e in c["role_evidence"]
                if not isinstance(e, dict) or e.get("role") in roles]
        note = build_note(c_for_note)
        if note:
            block.append("        <Note>%s</Note>" % esc(note))
        else:
            log.append("NO EVIDENCE %s: no role_evidence, Contact written "
                       "without a Note" % pid)
        block.append("      </Contact>")
        scope = (c.get("authorship_scope") or "").strip().lower()
        if scope and scope not in SCOPE_RANK:
            log.append("SCOPE UNKNOWN %s: authorship_scope '%s' not recognised; "
                       "sorted with unscoped candidates" % (pid, scope))
        scope_rank = SCOPE_RANK.get(scope, SCOPE_UNSET)
        contacts.append((rank, scope_rank, len(contacts), "\n".join(block)))
        written_ids.add(pid)

    # Order Contact blocks by each person's highest-ranking role. The second
    # key is the original position, so people sharing a rank keep the order the
    # enricher produced (evidence strength / author position).
    contacts.sort(key=lambda t: (t[0], t[1], t[2]))
    contacts = [b for _, _, _, b in contacts]

    if blockers:
        print("ABORT: %d unresolved possible duplicate(s). Nothing written.\n"
              % len(blockers))
        for name, hits in blockers:
            print("  - %s" % name)
            for h in hits:
                p = os.path.join(repo, "Person", h + ".xml")
                _, f = read_person(p) if os.path.isfile(p) else ("", {})
                bits = []
                for tag in ("PersonName", "OrganizationName", "Email"):
                    if f.get(tag):
                        bits.append(f[tag][0])
                print("      %-28s %s" % (h, " | ".join(bits)))
        if args.decisions:
            path = os.path.expanduser(args.decisions)
            existing = {}
            if os.path.isfile(path):
                existing = json.load(open(path, encoding="utf-8"))
            links = dict(existing.get("links") or {})
            creates = list(existing.get("creates") or [])
            for name, hits in blockers:
                if name not in links and name not in creates:
                    links[name] = ""
            tmpl = {
                "_help": ("For each name: set links[name] to an existing PersonID "
                          "if it is the same human, or move the name into creates "
                          "if it is a different person. Empty string means undecided."),
                "_candidates": {n: h for n, h in blockers},
                "links": links,
                "creates": creates,
            }
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(tmpl, fh, indent=2)
            print("\nDecisions template written: %s" % path)
            print("Fill it in once; later runs of this record reuse it.")
        else:
            print("\nEvery flagged name needs a --link or --create decision, "
                  "or pass --decisions <path> to record them persistently.")
        return 1

    # ---- target record ----------------------------------------------------
    txt = open(target, encoding="utf-8").read()
    txt = bump_schema(txt)

    # Replace the UNKNOWN placeholder and any Contact for a person we are
    # writing; leave unrelated Contacts alone. This makes re-runs idempotent.
    blocks = list(re.finditer(r"[ \t]*<Contact>.*?</Contact>\n", txt, re.S))
    if not blocks:
        print("ABORT: no Contact block found in %s; cannot place new Contacts."
              % target)
        return 1

    drop, keep = [], []
    for m in blocks:
        pm = re.search(r"<PersonID>\s*spase://SMWG/Person/([^<\s]+)\s*</PersonID>",
                       m.group(0))
        who = pm.group(1) if pm else None
        if who == "UNKNOWN" or (who and who in written_ids):
            drop.append(m)
        else:
            keep.append(who)

    anchor = drop[0].start() if drop else blocks[-1].end()
    out, cursor = [], 0
    for m in drop:
        out.append(txt[cursor:m.start()])
        cursor = m.end()
    out.append(txt[cursor:])
    txt = "".join(out)

    # recompute the anchor against the reduced text
    if drop:
        removed_before = sum(m.end() - m.start()
                             for m in drop if m.start() < anchor)
        insert_at = anchor - removed_before
    else:
        removed = sum(m.end() - m.start() for m in drop)
        insert_at = anchor - removed
    txt = txt[:insert_at] + "\n".join(contacts) + "\n" + txt[insert_at:]

    if len(drop) > 1 or (drop and not any(
            re.search(r"Person/UNKNOWN", m.group(0)) for m in drop)):
        log.append("REPLACED   %d existing Contact block(s) for the same people"
                   % len(drop))
    if keep:
        log.append("KEPT       %d unrelated Contact(s): %s"
                   % (len(keep), ", ".join(k for k in keep if k)))

    # InformationURL sits after Contact and before Association in ResourceHeader,
    # so new entries are appended after the last existing InformationURL, or
    # immediately after the Contact block when the record has none.
    scope = "instrument" if "/Instrument/" in rid else "observatory"
    url_blocks, url_log = build_information_urls(data, scope, txt)
    log.extend(url_log)
    if url_blocks:
        last_url = None
        for m in re.finditer(r"[ \t]*<InformationURL>.*?</InformationURL>\n",
                             txt, re.S):
            last_url = m
        if last_url:
            at = last_url.end()
        else:
            last_contact = None
            for m in re.finditer(r"[ \t]*<Contact>.*?</Contact>\n", txt, re.S):
                last_contact = m
            at = last_contact.end() if last_contact else None
        if at is None:
            log.append("URL SKIPPED  no anchor found; none written")
        else:
            txt = txt[:at] + "\n".join(url_blocks) + "\n" + txt[at:]
            log.append("URL ADDED    %d InformationURL entr%s"
                       % (len(url_blocks), "y" if len(url_blocks) == 1 else "ies"))

    note = args.note or (
        "Added mission Contacts with Author and qualifying roles derived from "
        "mission literature and instrument records; corrected schemaLocation to "
        "match the declared SPASE Version.")
    # Provenance of this edit belongs in the RevisionEvent, which is what a
    # RevisionEvent is for. The URL must be commit-pinned: a branch link drifts
    # as soon as the record is re-enriched and would then appear to corroborate
    # values the record does not contain.
    if args.artifacts_url:
        note = (note.rstrip(".") + ". Candidate and enrichment files: %s"
                % args.artifacts_url.strip())
    if args.initials:
        note = note.rstrip(".") + ". " + args.initials

    m = re.search(r"^([ \t]*)</RevisionHistory>", txt, re.M)
    if m:
        ind = m.group(1)
        # A re-run must not stack a second event carrying the same note. When the
        # last event is already ours, restamp it in place; the pipeline normally
        # resets the branch first, but write_records.py is also run directly.
        last = None
        for last in re.finditer(
                r"<RevisionEvent>\s*<ReleaseDate>([^<]*)</ReleaseDate>\s*"
                r"<Note>(.*?)</Note>\s*</RevisionEvent>", txt, re.S):
            pass
        if last and last.group(2).strip() == esc(note).strip():
            txt = (txt[:last.start(1)] + stamp + txt[last.end(1):])
            log.append("REVISION   restamped the existing RevisionEvent "
                       "(same note) rather than adding a duplicate")
        else:
            event = ("%s  <RevisionEvent>\n%s    <ReleaseDate>%s</ReleaseDate>\n"
                     "%s    <Note>%s</Note>\n%s  </RevisionEvent>\n"
                     % (ind, ind, stamp, ind, esc(note), ind))
            txt = txt[:m.start()] + event + txt[m.start():]
    else:
        log.append("WARN       no RevisionHistory in target; no RevisionEvent added")

    txt = re.sub(r"(<ResourceHeader>.*?)<ReleaseDate>[^<]*</ReleaseDate>",
                 r"\g<1><ReleaseDate>%s</ReleaseDate>" % stamp,
                 txt, count=1, flags=re.S)

    if not args.dry_run:
        open(target, "w", encoding="utf-8").write(txt)

    # ---- report -----------------------------------------------------------
    mode = "DRY RUN -- nothing written" if args.dry_run else "written"
    print("target   : %s (%s)" % (os.path.relpath(target, repo), mode))
    print("contacts : %d" % len(contacts))
    print("created  : %d  %s" % (len(creates), creates))
    print("updated  : %d  %s" % (len(updates), updates))
    print("\n--- divergence log (%d) ---" % len(log))
    for line in log:
        print("  " + line)
    print("\nNext: run the local checker, then commit Person records and the "
          "target record TOGETHER in one commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())