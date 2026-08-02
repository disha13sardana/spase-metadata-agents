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


def bare_orcid(v):
    return re.sub(r"^https?://orcid\.org/", "", v).strip() if v else None


def bare_ror(v):
    return re.sub(r"^https?://ror\.org/", "", v).strip() if v else None


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


def bump_schema(txt):
    txt = re.sub(r'xsi:schemaLocation="[^"]*"',
                 'xsi:schemaLocation="%s"' % SCHEMA_LOC, txt, count=1)
    txt = re.sub(r"<Version>[^<]*</Version>",
                 "<Version>%s</Version>" % TARGET_VERSION, txt, count=1)
    return txt


def new_person_xml(pid, name, org, orcid, ror, stamp):
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

    for c in included:
        name = c["name"]
        linked = (c.get("person_record") or {}).get("id") or ""
        pid = linked.replace("spase://SMWG/Person/", "")

        if name in overrides:
            pid = overrides[name]
            log.append("LINK       %s -> %s (confirmed by curator)" % (name, pid))

        if not pid:
            hits = find_collisions(name, ids, by_sur)
            if hits and name not in confirmed_new:
                blockers.append((name, hits[:4]))
                continue
            pid = mint_id(name)
            if pid != name.replace(" ", "."):
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

            # RULE: never overwrite a real value with the Unknown fallback.
            if org and org != existing_org:
                if existing_org and existing_org != UNKNOWN_ORG:
                    log.append("ORG CHANGE %s: '%s' -> '%s'"
                               % (pid, existing_org, org))
                txt = set_field(txt, "OrganizationName", org)
                # RULE: OrganizationName and RORIdentifier move together.
                existing_ror = (fields.get("RORIdentifier") or [""])[0]
                if ror and existing_ror and existing_ror != ror:
                    log.append("ROR CHANGE %s: '%s' -> '%s' (follows org)"
                               % (pid, existing_ror, ror))
                if ror:
                    txt = set_field(txt, "RORIdentifier", ror)
            elif not org and existing_org:
                log.append("ORG KEPT   %s: no affiliation in input, kept '%s'"
                           % (pid, existing_org))

            existing_orcid = (fields.get("ORCIdentifier") or [""])[0]
            if orcid and not existing_orcid:
                txt = set_field(txt, "ORCIdentifier", orcid)
            elif orcid and existing_orcid != orcid:
                log.append("ORCID CLASH %s: repo=%s input=%s (kept repo)"
                           % (pid, existing_orcid, orcid))

            if ror and not (fields.get("RORIdentifier") or [""])[0]:
                txt = set_field(txt, "RORIdentifier", ror)

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
                    new_person_xml(pid, name, org, orcid, ror, stamp))
            creates.append(pid)

        roles = c.get("qualifying_roles") or ["Author"]
        if "Author" not in roles:
            roles = ["Author"] + list(roles)
        block = ["      <Contact>",
                 "        <PersonID>spase://SMWG/Person/%s</PersonID>" % pid]
        block += ["        <Role>%s</Role>" % r for r in roles]
        block.append("      </Contact>")
        contacts.append("\n".join(block))

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

    placeholder = re.search(
        r"[ \t]*<Contact>\s*<PersonID>spase://SMWG/Person/UNKNOWN</PersonID>"
        r"\s*<Role>[A-Za-z]+</Role>\s*</Contact>\n", txt)
    if placeholder:
        txt = txt[:placeholder.start()] + "\n".join(contacts) + "\n" + txt[placeholder.end():]
    else:
        last = None
        for m in re.finditer(r"[ \t]*<Contact>.*?</Contact>\n", txt, re.S):
            last = m
        if not last:
            print("ABORT: no Contact block found in %s; cannot place new Contacts." % target)
            return 1
        txt = txt[:last.end()] + "\n".join(contacts) + "\n" + txt[last.end():]
        log.append("APPEND     kept existing Contacts, appended %d new" % len(contacts))

    note = args.note or (
        "Added mission Contacts with Author and qualifying roles derived from "
        "mission literature and instrument records; corrected schemaLocation to "
        "match the declared SPASE Version.")
    if args.initials:
        note = note.rstrip(".") + ". " + args.initials

    m = re.search(r"^([ \t]*)</RevisionHistory>", txt, re.M)
    if m:
        ind = m.group(1)
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
