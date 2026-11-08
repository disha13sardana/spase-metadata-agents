#!/usr/bin/env python3
"""
register_instruments.py -- create skeleton SPASE Instrument records from a reviewed plan.

The spase-missing-instrument-registrar agent researches each instrument the Observatory
author-finder run reported as missing from SPASE and writes its findings to
spase_records/<record-name>/instrument_registrations.json. This script turns the
entries marked "create" into minimal, schema-valid Instrument records:

    ResourceID, ResourceHeader (ResourceName, AlternateName*, ReleaseDate,
    RevisionHistory, Description, one placeholder Contact), InstrumentType,
    InvestigationName, ObservatoryID

The records carry no people. The next step, spase-instrument-author-mapper,
builds the writer's input for every instrument of the Observatory (these new
records included) from the Observatory run, and the writer then replaces the
UNKNOWN placeholder.

Pipeline:
    clean-tree check -> registry (every naming authority: the Heliophysics
    Instruments API and the hpde GitHub organisation; see registry.py) ->
    branch, built on the Observatory writer's branch -> validate plan ->
    duplicate guard -> build writer inputs -> write records -> local check ->
    commit -> push (to the curator's fork, never main/master) -> write writer
    inputs

InstrumentType, InvestigationName and Description are left unfilled for now:
InstrumentType is written as Unspecified (an empty value fails the schema's
closed enumeration) and the other two as empty elements, unless the plan
supplies values.

Nothing is written unless every "create" entry passes validation. A failed run
leaves the clone exactly as it found it.

Usage:
    python3 register_instruments.py --repo ~/SMWG \\
        --input spase_records/<record-name>/instrument_registrations.json --initials DS

    --dry-run        validate and print the XML; touch nothing
    --no-commit      write files on the branch, leave them uncommitted
    --no-push        commit, but do not push
    --branch NAME    override the derived branch name
    --base NAME      branch to start from (default: origin's HEAD)
    --plan-url URL   commit-pinned link to the plan, appended to the RevisionEvent
    --registry-dir DIR   read the registry from local clones instead of the API
    --registry-cache PATH   API index cache (default ~/.cache/spase-registry/)
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import registry  # noqa: E402
from registry import name_key, observatory_key  # noqa: E402
DEFAULT_CHECKER = os.path.normpath(os.path.join(
    HERE, "..", "..", "spase-record-writer", "scripts", "spase-localcheck.py"))

# Kept in step with spase-record-writer/scripts/write_records.py so every record
# the pipeline creates declares the same version.
TARGET_VERSION = "2.7.1"
SCHEMA_LOC = ("https://www.spase-group.org/data/schema "
              "https://www.spase-group.org/data/schema/spase-2.7.1.xsd")

# Registry convention for "no contact known": 39 of the 50 Instrument records
# that use the UNKNOWN Person pair it with GeneralContact. The record writer
# replaces this Contact when it writes real people.
PLACEHOLDER_PERSON = "spase://SMWG/Person/UNKNOWN"
PLACEHOLDER_ROLE = "GeneralContact"

# Every commit this script makes carries this line. A registration branch holding a
# commit without it has been touched by someone else and must not be reset.
COMMIT_MARKER = "Registered missing Instrument records:"
# The record writer's marker. The registration branch is built on the
# Observatory writer's branch, so after an Observatory re-run it still holds the
# old Observatory commit; that commit is reproducible pipeline output, not a
# curator's work, and may be reset away.
WRITER_MARKER = "Applied enriched author candidates:"
PIPELINE_MARKERS = (COMMIT_MARKER, WRITER_MARKER)

# SPASE 2.7.1 InstrumentType enumeration (spase-base-2.7.1/member.tab).
INSTRUMENT_TYPES = {
    "Antenna", "Channeltron", "Coronograph", "DoubleSphere", "DustDetector",
    "ElectronDriftInstrument", "ElectrostaticAnalyser",
    "EnergeticParticleInstrument", "Experiment", "FaradayCup", "FluxFeedback",
    "FourierTransformSpectrograph", "GeigerMuellerTube", "Imager",
    "ImagingSpectrometer", "Interferometer", "IonChamber", "IonDrift",
    "IonGauge", "LangmuirProbe", "Lidar", "LongWire", "Magnetograph",
    "Magnetometer", "MassSpectrometer", "MicrochannelPlate",
    "MultispectralImager", "NeutralAtomImager", "NeutralParticleDetector",
    "ParticleCorrelator", "ParticleDetector", "Photometer",
    "PhotomultiplierTube", "Photopolarimeter", "Platform",
    "ProportionalCounter", "QuadrisphericalAnalyser", "Radar", "Radiometer",
    "ResonanceSounder", "RetardingPotentialAnalyser", "Riometer",
    "ScintillationDetector", "SearchCoil", "SolidStateDetector", "Sounder",
    "SpacecraftPotentialControl", "SpectralPowerReceiver", "Spectrometer",
    "TimeOfFlight", "Unspecified", "WaveformReceiver",
}

# Text that means the agent did not finish the job. A skeleton is minimal, not
# unfinished: every field it carries is real.
PLACEHOLDER_TEXT = re.compile(
    r"\b(TODO|TBD|FIXME|lorem ipsum|placeholder|to be (?:added|determined)|"
    r"description pending)\b", re.I)

RID_RE = re.compile(r"^spase://([A-Za-z0-9_-]+)/(Instrument|Observatory)/"
                    r"([A-Za-z0-9._/-]+)$")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("%s failed:\n%s%s" % (" ".join(cmd), p.stdout, p.stderr))
    return p


def git(args, repo, check=True):
    return run(["git", "-C", repo] + args, check=check)


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rid_to_path(repo, rid):
    m = RID_RE.match(rid)
    return os.path.join(repo, m.group(2), m.group(3) + ".xml") if m else None


def text_of(entry, key):
    """Fields may be a bare value or {"value"/"text": ..., evidence...}."""
    v = entry.get(key)
    if isinstance(v, dict):
        v = v.get("value", v.get("text"))
    return v


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def default_branch(repo, override=None):
    if override:
        return override
    p = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo, check=False)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip().split("/", 1)[-1]
    for b in ("master", "main"):
        if git(["rev-parse", "--verify", b], repo, check=False).returncode == 0:
            return b
    return None


def foreign_commits(repo, base, branch):
    p = git(["log", "--format=%H%x00%s%x00%b%x01", "%s..%s" % (base, branch)],
            repo, check=False)
    out = []
    for rec in p.stdout.split("\x01"):
        if not rec.strip():
            continue
        sha, subject, body = (rec.strip().split("\x00") + ["", ""])[:3]
        if not any(m in body for m in PIPELINE_MARKERS):
            out.append((sha[:8], subject))
    return out


# --------------------------------------------------------------------------
# existing-record index, for the duplicate guard
# --------------------------------------------------------------------------

def index_instruments(repo):
    """Every Instrument record in the clone: id, ObservatoryID, folded names."""
    out = []
    for f in glob.glob(os.path.join(repo, "Instrument", "**", "*.xml"), recursive=True):
        try:
            t = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        rid = re.search(r"<ResourceID>\s*([^<]+?)\s*</ResourceID>", t)
        obs = re.search(r"<ObservatoryID>\s*([^<]+?)\s*</ObservatoryID>", t)
        names = re.findall(r"<(?:ResourceName|AlternateName)>\s*([^<]+?)\s*</", t)
        rid = rid.group(1) if rid else f
        names.append(rid.rsplit("/", 1)[-1])
        out.append({"id": rid, "file": f, "obs": obs.group(1) if obs else None,
                    "keys": {name_key(n) for n in names if name_key(n)}})
    return out


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def validate(plan, repo, authority, registry_records, registry_failed, helio_items=()):
    """Return (creates, errors, notes). Nothing is written if errors is non-empty."""
    errors, notes, creates = [], [], []
    obs0 = plan.get("observatory_record")
    mine, other = registry.split_failures(registry_failed, obs0)
    for f in mine:
        if f.startswith("spase://"):
            notes.append("registry: %s is listed by the Heliophysics Instruments API but "
                         "not published at the address its ResourceID gives, so its "
                         "ObservatoryID could not be read; it was checked by name and "
                         "path only" % f.split(": ", 1)[0])
        else:
            errors.append("registry: could not read %s; the duplicate check would be "
                          "incomplete" % f)
    if other:
        notes.append("registry: %d record(s) under other Observatories could not be read "
                     "at their ResourceID's address" % len(other))
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        return [], ["plan has no 'entries' list"], []

    obs_default = plan.get("observatory_record")
    # The clone may hold records not yet published, and the registry records
    # under other authorities the clone cannot see. Check both.
    index = index_instruments(repo)
    have = {r["id"] for r in index}
    for r in registry_records:
        if r["id"] in have:
            continue
        index.append({"id": r["id"], "file": r.get("where") or "hpde/%s/%s" % (r["repo"], r["path"]),
                      "published": True, "obs": r.get("obs"),
                      "keys": {name_key(n) for n in r["names"] if name_key(n)}})
    published = {r["id"]: r.get("where") or "hpde/%s/%s" % (r["repo"], r["path"])
                 for r in registry_records}
    seen_ids = set()

    if authority == "SMWG" and not os.path.exists(os.path.join(repo, "Person", "UNKNOWN.xml")):
        errors.append("placeholder Person %s is missing from the clone "
                      "(Person/UNKNOWN.xml)" % PLACEHOLDER_PERSON)

    for i, e in enumerate(entries):
        label = e.get("instrument") or "entry %d" % i
        action = e.get("action")
        if action == "skip":
            if not e.get("skip_reason"):
                errors.append("%s: action 'skip' needs a skip_reason" % label)
            continue
        if action != "create":
            errors.append("%s: action must be 'create' or 'skip', got %r" % (label, action))
            continue

        rid = e.get("resource_id") or ""
        m = RID_RE.match(rid)
        if not m or m.group(2) != "Instrument":
            errors.append("%s: resource_id %r is not a spase://<Authority>/Instrument/... ID"
                          % (label, rid))
            continue
        if m.group(1) != authority:
            errors.append("%s: resource_id authority %s is not the Observatory's (%s); "
                          "new Instrument records go under the same naming authority "
                          "as their Observatory record" % (label, m.group(1), authority))
            continue
        if rid in seen_ids:
            errors.append("%s: resource_id %s appears twice in the plan" % (label, rid))
        seen_ids.add(rid)

        path = rid_to_path(repo, rid)
        for h in registry.helio_exact(helio_items, rid):
            errors.append("%s: %s is listed by the Heliophysics Instruments API (%s); "
                          "it is already registered. Mark the entry 'skip'"
                          % (label, rid, h.get("long_name") or h.get("id")))
        if rid in published:
            errors.append("%s: %s is already published (%s); your clone is behind. "
                          "Pull, then mark the entry 'skip'" % (label, rid, published[rid]))
        if os.path.exists(path):
            errors.append("%s: %s already exists; mark the entry 'skip' (a skeleton "
                          "never overwrites a record)" % (label, os.path.relpath(path, repo)))
        # Case-only clashes break checkouts on macOS and Windows.
        d = os.path.dirname(path)
        if os.path.isdir(d):
            for other in os.listdir(d):
                if other.lower() == os.path.basename(path).lower() and \
                        other != os.path.basename(path):
                    errors.append("%s: %s differs only in case from existing %s"
                                  % (label, os.path.basename(path), other))

        name = e.get("resource_name")
        if not name or not str(name).strip():
            errors.append("%s: resource_name is required" % label)

        # InstrumentType, InvestigationName and Description are left unfilled
        # for now. SPASE requires all three elements; an empty InstrumentType
        # fails the schema (closed enumeration), so it defaults to the schema's
        # own "not known" value, Unspecified. The other two are written empty,
        # which the schema accepts. A plan that supplies a value is still
        # checked, so they can be filled later without changing this script.
        types = as_list(text_of(e, "instrument_type")) or ["Unspecified"]
        for t in types:
            if t not in INSTRUMENT_TYPES:
                errors.append("%s: InstrumentType %r is not in the SPASE 2.7.1 "
                              "enumeration" % (label, t))
        it = e.get("instrument_type")
        if isinstance(it, dict) and "Unspecified" not in types and not it.get("evidence"):
            errors.append("%s: instrument_type %s has no evidence" % (label, types))

        inv = [str(x).strip() for x in as_list(text_of(e, "investigation_name"))
               if str(x).strip()] or [""]

        desc = text_of(e, "description")
        dsrc = (e.get("description") or {}).get("sources") \
            if isinstance(e.get("description"), dict) else None
        if desc and len(desc.strip()) < 40:
            errors.append("%s: a description, when given, is at least one full "
                          "sentence" % label)
        elif desc and PLACEHOLDER_TEXT.search(desc):
            errors.append("%s: description contains placeholder text (%r)"
                          % (label, PLACEHOLDER_TEXT.search(desc).group(0)))
        if desc and not dsrc:
            errors.append("%s: description has no sources" % label)

        obs = e.get("observatory_id") or obs_default
        om = RID_RE.match(obs or "")
        if not om or om.group(2) != "Observatory":
            errors.append("%s: observatory_id %r is not an Observatory ResourceID"
                          % (label, obs))
        elif om.group(1) == authority:
            if not os.path.exists(rid_to_path(repo, obs)):
                errors.append("%s: ObservatoryID %s has no file in the clone"
                              % (label, obs))
        else:
            notes.append("%s: ObservatoryID %s is under another authority and "
                         "cannot be checked locally" % (label, obs))

        # Duplicate guard: same observatory, overlapping name. The agent rules
        # on a flagged match with not_duplicate_of; anything unruled stops the run.
        mine = {name_key(n) for n in
                [name, rid.rsplit("/", 1)[-1]] + as_list(e.get("alternate_names"))
                if name_key(n)}
        ruled = {x.get("id") if isinstance(x, dict) else x
                 for x in as_list(e.get("not_duplicate_of"))}
        okey = observatory_key(obs)
        for h in registry.helio_lookup(helio_items, obs,
                                       [name, rid.rsplit("/", 1)[-1]] +
                                       as_list(e.get("alternate_names"))):
            if h["shared"] and h["spase_id"] != rid and h["spase_id"] not in ruled \
                    and h["spase_id"] not in {r["id"] for r in index}:
                errors.append("%s: possible duplicate of %s, listed by the Heliophysics "
                              "Instruments API under this Observatory's path (shared name "
                              "%s). Mark the entry 'skip', or record not_duplicate_of with "
                              "a reason" % (label, h["spase_id"], h["shared"]))
        for rec in index:
            if okey and observatory_key(rec["obs"]) == okey and rec["keys"] & mine \
                    and rec["id"] not in ruled:
                errors.append("%s: possible duplicate of existing %s in %s (same "
                              "Observatory, shared name %s). Mark the entry 'skip', "
                              "or record not_duplicate_of with a reason"
                              % (label, rec["id"], rec["file"] if rec.get("published")
                                 else "your clone", sorted(rec["keys"] & mine)))

        e = dict(e)
        e["_types"], e["_inv"], e["_desc"], e["_obs"] = types, inv, desc.strip() if desc else "", obs
        creates.append(e)

    return creates, errors, notes


# --------------------------------------------------------------------------
# XML
# --------------------------------------------------------------------------

def skeleton_xml(e, stamp, note):
    m = RID_RE.match(e["resource_id"])
    L = ["<?xml version='1.0' encoding='UTF-8'?>",
         '<Spase xmlns="http://www.spase-group.org/data/schema" '
         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
         'xsi:schemaLocation="%s">' % SCHEMA_LOC,
         "  <Version>%s</Version>" % TARGET_VERSION,
         "  <Instrument>",
         "    <ResourceID>%s</ResourceID>" % esc(e["resource_id"]),
         "    <NamingAuthority>%s</NamingAuthority>" % m.group(1),
         "    <ResourceType>Instrument</ResourceType>",
         "    <ResourceHeader>",
         "      <ResourceName>%s</ResourceName>" % esc(e["resource_name"].strip())]
    for alt in as_list(e.get("alternate_names")):
        if alt and alt.strip() and alt.strip() != e["resource_name"].strip():
            L.append("      <AlternateName>%s</AlternateName>" % esc(alt.strip()))
    L += ["      <ReleaseDate>%s</ReleaseDate>" % stamp,
          "      <RevisionHistory>",
          "        <RevisionEvent>",
          "          <ReleaseDate>%s</ReleaseDate>" % stamp,
          "          <Note>%s</Note>" % esc(note),
          "        </RevisionEvent>",
          "      </RevisionHistory>",
          "      <Description>%s</Description>" % esc(e["_desc"]),
          "      <Contact>",
          "        <PersonID>%s</PersonID>" % PLACEHOLDER_PERSON,
          "        <Role>%s</Role>" % PLACEHOLDER_ROLE,
          "      </Contact>",
          "    </ResourceHeader>"]
    for t in e["_types"]:
        L.append("    <InstrumentType>%s</InstrumentType>" % t)
    for inv in e["_inv"]:
        L.append("    <InvestigationName>%s</InvestigationName>" % esc(str(inv).strip()))
    L += ["    <ObservatoryID>%s</ObservatoryID>" % esc(e["_obs"]),
          "  </Instrument>",
          "</Spase>", ""]
    return "\n".join(L)


def revision_note(plan, args):
    obs = plan.get("observatory_record") or "the Observatory"
    note = ("Skeleton Instrument record created for an instrument missing from "
            "SPASE, identified by the author-finder run on %s. InstrumentType "
            "(Unspecified), InvestigationName and Description are not yet filled; "
            "Contact is the UNKNOWN placeholder until authors are written" % obs)
    if args.plan_url:
        note += ". Registration plan: %s" % args.plan_url.strip()
    if args.initials:
        note += ". " + args.initials.strip()
    return note


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="local clone of the SPASE repository")
    ap.add_argument("--input", required=True, help="instrument_registrations.json")
    ap.add_argument("--initials", default="")
    ap.add_argument("--authority", default=None,
                    help="naming authority of this repository (default: from the "
                         "plan's observatory_record)")
    ap.add_argument("--branch", default=None)
    ap.add_argument("--base", default=None)
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--checker", default=DEFAULT_CHECKER)
    ap.add_argument("--plan-url", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--registry-dir", default=None,
                    help="local clones of the hpde authority repositories")
    ap.add_argument("--registry-cache", default=registry.DEFAULT_CACHE)
    ap.add_argument("--registry-source", choices=("site", "github"), default="site",
                    help="site: Heliophysics Instruments API + spase-metadata.org (default); "
                         "github: the hpde repositories through the GitHub API")
    ap.add_argument("--no-registry", action="store_true",
                    help="skip the all-authority duplicate check (tests only)")
    ap.add_argument("--no-instruments-api", action="store_true",
                    help="skip the Heliophysics Instruments API check (tests only)")
    args = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(args.repo))
    plan = json.load(open(args.input, encoding="utf-8"))
    obs_rec = plan.get("observatory_record") or ""
    om = RID_RE.match(obs_rec)
    authority = args.authority or (om.group(1) if om else "SMWG")

    # ---- registry: every naming authority --------------------------------
    if args.no_registry:
        print("WARN     --no-registry: records under other naming authorities were "
              "NOT checked")
        reg_records, reg_failed = [], []
    else:
        try:
            reg_records, reg_failed = registry.load_records(
                args.registry_dir, args.registry_cache, log=lambda s: print(s),
                source=args.registry_source)
        except Exception as exc:  # noqa: BLE001
            print("ABORT: registry check failed: %s\nNothing written." % exc)
            return 2
        mine = registry.lookup(reg_records, obs_rec)
        by_auth = {}
        for r in mine:
            by_auth.setdefault(r["id"].split("/")[2], []).append(r["id"].rsplit("/", 1)[-1])
        print("registry : %s has %d published Instrument record(s)%s"
              % (obs_rec, len(mine), "".join("; %s: %s" % (a, ", ".join(sorted(v)))
                                              for a, v in sorted(by_auth.items()))))
    helio_items = []
    if args.no_instruments_api:
        print("WARN     --no-instruments-api: the Heliophysics Instruments API was NOT "
              "checked")
    else:
        try:
            helio_items = registry.helio_instruments(
                os.path.dirname(args.registry_cache), log=lambda s: print(s))
        except Exception as exc:  # noqa: BLE001
            print("ABORT: Heliophysics Instruments API check failed: %s\nNothing "
                  "written." % exc)
            return 2
        api = registry.helio_lookup(helio_items, obs_rec)
        extra = sorted(h["spase_id"] for h in api
                       if h["spase_id"] not in {r["id"] for r in reg_records})
        print("api      : %d instrument(s) under this Observatory's path%s"
              % (len(api), "; not in the hpde index: %s" % ", ".join(extra) if extra and
                 not args.no_registry else ""))

    # ---- 1. clean tree ---------------------------------------------------
    if not args.dry_run:
        dirty = git(["status", "--porcelain", "--untracked-files=no"], repo).stdout.strip()
        if dirty:
            print("ABORT: the clone has uncommitted changes to tracked files:\n%s\n"
                  "Commit or stash them first." % dirty)
            return 1

    # ---- 2. validate (against base, after branching) --------------------
    # Validation reads the clone, so it has to see the base branch, not
    # whatever branch the clone happens to be on.
    stamp = now_stamp()
    note = revision_note(plan, args)

    if args.dry_run:
        creates, errors, notes = validate(plan, repo, authority, reg_records, reg_failed, helio_items)
        report_validation(plan, creates, errors, notes)
        if errors:
            return 1
        for e in creates:
            print("\n----- %s -----" % os.path.relpath(rid_to_path(repo, e["resource_id"]), repo))
            print(skeleton_xml(e, stamp, note))
        return 0

    slug = re.sub(r"[^a-z0-9]+", "-", (om.group(3) if om else "batch").lower()).strip("-")
    branch = args.branch or "instrument-registration-%s" % slug
    # One pull request per mission: build on the Observatory writer's branch, so
    # the final branch carries the Observatory's authors, these records and their
    # authors together.
    obs_branch = "author-enrichment-%s" % slug
    if args.base:
        base = args.base
    elif git(["rev-parse", "--verify", obs_branch], repo, check=False).returncode == 0:
        base = obs_branch
    else:
        base = default_branch(repo)
        if base is not None:
            print("WARN     no %s branch in the clone; building on %s, so the final pull "
                  "request will not include the Observatory's own authors" % (obs_branch, base))
    if base is None:
        print("ABORT: cannot determine the default branch; pass --base.")
        return 2
    if branch in ("master", "main", base):
        print("ABORT: refusing to register instruments on %s." % branch)
        return 2

    start_branch = git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()
    exists = git(["rev-parse", "--verify", branch], repo, check=False).returncode == 0
    orig_tip = None
    if exists:
        foreign = foreign_commits(repo, base, branch)
        if foreign:
            print("ABORT: %s carries %d commit(s) this script did not write:\n" %
                  (branch, len(foreign)))
            for sha, subject in foreign:
                print("  %s  %s" % (sha, subject))
            print("\nA reset would discard them. If the record writer has already "
                  "run on top of\nthese skeletons, its branch is built on this one; "
                  "decide what should\nhappen to that work before re-running.")
            return 1
        orig_tip = git(["rev-parse", branch], repo).stdout.strip()

    git(["checkout", branch] if exists else ["checkout", "-b", branch, base], repo)
    if exists:
        git(["reset", "--hard", base], repo)
        print("branch   : %s (existing, reset to %s)" % (branch, base))
    else:
        print("branch   : %s (new, from %s)" % (branch, base))

    written = []

    def rollback():
        for p in written:
            if os.path.exists(p):
                os.remove(p)
        git(["checkout", "--", "."], repo, check=False)
        if orig_tip:
            git(["reset", "--hard", orig_tip], repo, check=False)
            if start_branch != branch:
                git(["checkout", start_branch], repo, check=False)
        else:
            git(["checkout", start_branch], repo, check=False)
            git(["branch", "-D", branch], repo, check=False)

    try:
        creates, errors, notes = validate(plan, repo, authority, reg_records, reg_failed, helio_items)
        report_validation(plan, creates, errors, notes)
        if errors:
            print("\nNothing written.")
            rollback()
            return 1
        if not creates:
            print("\nNo entries marked 'create'; nothing to write.")
            rollback()
            return 0

        # ---- 3. write ---------------------------------------------------
        for e in creates:
            path = rid_to_path(repo, e["resource_id"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(skeleton_xml(e, stamp, note))
            written.append(path)
            print("CREATED  %s" % os.path.relpath(path, repo))

        # ---- 4. local check --------------------------------------------
        rel = [os.path.relpath(p, repo) for p in written]
        if os.path.exists(args.checker):
            p = subprocess.run([sys.executable, args.checker, "--repo-root", repo] + rel,
                               cwd=repo, capture_output=True, text=True)
            print("\nlocal check:\n" + p.stdout.rstrip())
            if p.returncode != 0:
                print("\nABORT: local check failed on the new records; rolled back.")
                rollback()
                return 1
        else:
            print("WARN     checker not found at %s; skipped local check" % args.checker)

        if args.no_commit:
            print("\nWritten, not committed, on %s." % branch)
            print_next(plan, args, branch)
            return 0

        # ---- 5. commit -------------------------------------------------
        git(["add"] + rel, repo)
        names = ", ".join(e["resource_id"].rsplit("/", 1)[-1] for e in creates)
        body = "%s %s\nFrom %s\n%s" % (
            COMMIT_MARKER, ", ".join(e["resource_id"] for e in creates),
            os.path.basename(os.path.dirname(os.path.abspath(args.input))) + "/" +
            os.path.basename(args.input),
            "Contacts are the UNKNOWN placeholder; run spase-instrument-author-mapper "
            "next.")
        git(["commit", "-m", "Register missing Instrument records for %s: %s"
             % (obs_rec.split("/", 3)[-1] if obs_rec else "missing instruments", names),
             "-m", body], repo)
        print("\ncommitted on %s" % branch)
    except Exception as exc:  # leave the clone as we found it
        print("ABORT: %s" % exc)
        rollback()
        return 1

    print_next(plan, args, branch)

    # ---- 6. push ---------------------------------------------------------
    if args.no_push:
        print("not pushed (--no-push). To push:\n  git -C %s push -u %s %s"
              % (repo, args.remote, branch))
        return 0
    p = git(["push", "--force-with-lease", "-u", args.remote, branch], repo, check=False)
    if p.returncode != 0:
        print("\npush rejected; the commit is safe on %s locally.\n%s"
              % (branch, p.stderr.strip()))
        return 1
    print("pushed %s to %s" % (branch, args.remote))
    return 0


def print_next(plan, args, branch):
    src = plan.get("source_file") or "spase_records/<record-name>/author_candidates_enriched.json"
    print("\nnext: build the writer inputs for every instrument, these new records "
          "included:\n  python3 .claude/skills/spase-instrument-author-mapper/scripts/"
          "build_instrument_inputs.py --repo %s \\\n      --enriched %s"
          % (args.repo, src))


def report_validation(plan, creates, errors, notes):
    entries = plan.get("entries") or []
    skips = [e for e in entries if e.get("action") == "skip"]
    print("plan     : %d entries, %d create, %d skip"
          % (len(entries), len(creates), len(skips)))
    for e in skips:
        print("SKIP     %s -- %s" % (e.get("instrument"), e.get("skip_reason")))
    for e in creates:
        print("CREATE   %s  [%s]" % (e["resource_id"], ", ".join(e["_types"])))
        for f in as_list(e.get("flags")):
            print("         FLAG %s" % f)
    for n in notes:
        print("NOTE     %s" % n)
    for err in errors:
        print("ERROR    %s" % err)


if __name__ == "__main__":
    sys.exit(main())
