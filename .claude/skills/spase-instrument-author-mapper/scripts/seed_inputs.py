#!/usr/bin/env python3
"""
seed_inputs.py -- build an Instrument record's author input from the Observatory
run, so the instrument needs no second finder or enricher pass.

Used by build_instrument_inputs.py for every instrument of an Observatory, those
already registered and those the registrar has just created. For each one it
reads the Observatory's author_candidates_enriched.json and produces, in exactly
the format spase-record-writer reads:

    spase_records/<observatory-record-name>_<Acronym>/author_candidates_enriched.json

Nothing is looked up again: people, roles, sources, ORCID, affiliation, ROR and
the enrichment provenance are copied from the Observatory file.

Where the people come from
    Each candidate's `instrument_roles` entries for this instrument, matched by
    spase_record or by the instrument's short name. For a suite, entries for its
    components come too, because records are kept at suite level: a component paper's
    authors and links go on the suite's record. A component is recognised by the
    entry's `component` field, by a name in the suite's `components`, or by a
    spase_record that is one of the suite's component records.

What is kept out
    - roles that are not instrument-level
    - a person with no Author entry for the instrument (inclusion means authorship)

An Observatory file written before `instrument_roles` existed cannot be reused;
the Observatory's finder and enricher must be re-run first.

Three outcomes, each with its own file name so the next step is unambiguous:

    ready             author_candidates_enriched.json  -> run the writer on it
    needs_enrichment  author_candidates.json           -> run the enricher, then
                      (someone in it was never           the writer; the enricher
                      enriched)                          leaves people who already
                                                         carry enrichment alone
    needs_full_run    seed_candidates.json             -> run the finder on the
                      (the Observatory run's own         record; this file is only
                      result for this instrument is      a reference for that run
                      incomplete: paper not located,
                      selection uncertain, nobody found)

A file there is overwritten only if it is exactly what this script last wrote
(a .seed.sha256 beside it records that); anything edited, or produced by a later
finder or enricher run, is left alone.

The Observatory's writer_decisions.json rulings on possible duplicate people are
carried over for the people in each file, so the writer does not ask again.
"""

import copy
import hashlib
import json
import os
import re



def name_key(s):
    """Fold a name for comparison: 'ABC', 'abc', 'A.B.C.' all match."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

INSTRUMENT_LEVEL_ROLES = ["Author", "InstrumentLead", "FormerPI", "InstrumentScientist",
                          "CoPI", "DeputyPI", "CoInvestigator"]
SCOPE_ORDER = {"observatory": 0, "instrument": 1, "component": 2}
INCOMPLETE_REASON = re.compile(r"uncertain|not located|not found|not harvested", re.I)
SEED_MARKER = "seeded_from"


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def entry_keys(e):
    names = [e.get("instrument"), e.get("resource_name"),
             (e.get("resource_id") or "").rsplit("/", 1)[-1]] + as_list(e.get("alternate_names"))
    return {name_key(n) for n in names if name_key(n)}


def component_keys(e):
    """The suite's components, as the plan lists them."""
    return {name_key(n) for n in as_list(e.get("components")) if name_key(n)}


def belongs(item, keys, ckeys):
    """Does an instrument_roles or information_urls entry belong on this record?"""
    inst, comp = name_key(item.get("instrument")), name_key(item.get("component"))
    return inst in keys or (ckeys and inst in ckeys) or (ckeys and comp in ckeys)


def acronym(e):
    return (e.get("resource_id") or "").rsplit("/", 1)[-1]


def pending_for(enriched, e):
    keys, rid = entry_keys(e), e.get("resource_id")
    for p in enriched.get("pending_instrument_runs") or []:
        name = p.get("instrument") or ""
        head = re.split(r"[\s(]", name.strip(), 1)[0]
        if p.get("spase_record") == rid or name_key(name) in keys or name_key(head) in keys:
            return p
    return None


def _entries_for(cand, e, keys, ckeys):
    out = []
    components = set(as_list(e.get("component_records")))
    for ir in cand.get("instrument_roles") or []:
        rec = ir.get("spase_record")
        if rec and rec == e.get("resource_id"):
            out.append(ir)
        elif rec and rec in components:
            out.append(dict(ir, source_scope="component"))   # a component's own record
        elif belongs(ir, keys, ckeys):
            out.append(ir)
    return out


def build_seed(enriched, e, plan, today):
    """Return (seed_dict, status, reason, log, errors) for one 'create' entry."""
    log, errors = [], []
    keys, ckeys = entry_keys(e), component_keys(e)
    cands = enriched.get("candidates") or []
    legacy = not any("instrument_roles" in c for c in cands)

    by_name = {c.get("name"): c for c in cands}
    grouped = {}   # name -> [entries]
    if legacy:
        errors.append("%s: the Observatory file predates instrument_roles; re-run the "
                      "Observatory's finder and enricher before reusing it"
                      % e.get("instrument"))
        return None, None, None, log, errors
    for c in cands:
        got = _entries_for(c, e, keys, ckeys)
        if got:
            grouped[c.get("name")] = got

    out_cands = []
    for name, entries in grouped.items():
        c = by_name[name]
        kept = []
        for ir in entries:
            role, scope = ir.get("role"), ir.get("source_scope") or "instrument"
            if scope == "instrument" and name_key(ir.get("instrument")) in ckeys:
                scope = "component"   # finder named the component as the instrument
            if role not in INSTRUMENT_LEVEL_ROLES:
                log.append("ROLE OUT   %s: %r is not an instrument-level role; left out"
                           % (name, role))
                continue
            if not ir.get("source"):
                log.append("NO SOURCE  %s: %s entry has no source; left out" % (name, role))
                continue
            kept.append(dict(ir, source_scope=scope))
        # One entry per role; the suite-level source wins over a component's.
        kept.sort(key=lambda r: SCOPE_ORDER.get(r["source_scope"], 9))
        roles = []
        for ir in kept:
            same = [r for r in roles if r["role"] == ir["role"]]
            if not same:
                roles.append(dict(ir))
            elif ir["source"] not in same[0]["source"]:
                # A suite paper and a component paper: keep both in the Note.
                same[0]["source"] = same[0]["source"].rstrip(".") + "; " + ir["source"]
                if ir.get("confidence") == "Strong":
                    same[0]["confidence"] = "Strong"
        if not any(r["role"] == "Author" for r in roles):
            if kept:
                log.append("NO AUTHOR  %s: no Author entry for this instrument; left out"
                           % name)
            continue
        roles.sort(key=lambda r: INSTRUMENT_LEVEL_ROLES.index(r["role"]))
        n = copy.deepcopy(c)
        n["status"] = "included"
        n["exclusion_reason"] = None
        n["confidence"] = "Strong" if any(r.get("confidence") == "Strong" for r in roles) \
            else "Medium"
        n["qualifying_roles"] = [r["role"] for r in roles]
        n["role_evidence"] = [{"role": r["role"], "source": r["source"]} for r in roles]
        n["authorship_scope"] = min((r["source_scope"] for r in roles),
                                    key=lambda s: SCOPE_ORDER.get(s, 9))
        n["instrument_roles"] = []
        n[SEED_MARKER] = {"observatory_status": c.get("status"),
                          "observatory_exclusion_reason": c.get("exclusion_reason")}
        if any(r["source_scope"] == "component" for r in roles):
            log.append("COMPONENT  %s: author of a component paper within the suite"
                       % name)
        if c.get("status") != "included":
            log.append("TEAM DEPTH %s: excluded from the Observatory as team depth, an "
                       "author of this instrument" % name)
        if not c.get("enrichment"):
            log.append("NOT ENRICHED %s: the Observatory file has no ORCID or "
                       "affiliation lookup for this person" % name)
        out_cands.append(n)
    unenriched = [c["name"] for c in out_cands if not c.get("enrichment")]

    urls = [u for u in enriched.get("information_urls") or []
            if u.get("scope") == "instrument" and belongs(u, keys, ckeys)]

    pend = pending_for(enriched, e)
    if e.get("reuse") == "full_run":
        status, reason = "needs_full_run", e.get("reuse_reason") or "a full run was asked for"
    elif pend and INCOMPLETE_REASON.search(pend.get("reason") or ""):
        status, reason = "needs_full_run", "Observatory run: %s" % pend.get("reason")
    elif not out_cands:
        status, reason = "needs_full_run", "the Observatory run recorded no authors for it"
    elif unenriched:
        status, reason = "needs_enrichment", "%d of %d people were never enriched: %s" % (
            len(unenriched), len(out_cands), ", ".join(unenriched))
    else:
        status, reason = "ready", "Observatory run resolved this instrument's authors"

    seed = {
        "record": e["resource_id"],
        "date": today,
        "operating_span": enriched.get("operating_span"),
        "cmad": enriched.get("cmad"),
        "pending_instrument_runs": [],
        "information_urls": urls,
        "candidates": out_cands,
        "notes": [
            "Built from the Observatory run on %s (%s), not from a separate finder and "
            "enricher run on this record. People, roles, ORCID, affiliation and ROR "
            "are copied from that file." % (enriched.get("record"), enriched.get("date")),
            "operating_span is the Observatory's; affiliations were era-matched "
            "against it.",
        ],
        SEED_MARKER: {
            "observatory_record": enriched.get("record"),
            "observatory_run_date": enriched.get("date"),
            "source": "instrument_roles",
            "status": status,
            "reason": reason,
        },
    }
    return seed, status, reason, log, errors


def seed_dir(records_dir, plan_dir_name, e):
    return os.path.join(records_dir, "%s_%s" % (plan_dir_name, acronym(e)))


FILENAMES = {"ready": "author_candidates_enriched.json",
             "needs_enrichment": "author_candidates.json",
             "needs_full_run": "seed_candidates.json"}


def seed_filename(status):
    return FILENAMES[status]


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check_target(path):
    """Overwrite only what this script wrote and nobody has touched since."""
    if not os.path.exists(path):
        return None
    side = path + ".seed.sha256"
    if os.path.exists(side) and open(side).read().strip() == _sha(path):
        return None
    return ("%s already exists and is not the author mapper's unmodified output (a "
            "finder, enricher or curator has worked on it); not overwriting it. "
            "Move it aside to rebuild it" % path)


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(path + ".seed.sha256", "w") as fh:
        fh.write(_sha(path) + "\n")


def carry_decisions(obs_dir, target_dir, names):
    """Copy the Observatory's duplicate-person rulings for these names."""
    src = os.path.join(obs_dir, "writer_decisions.json")
    if not os.path.exists(src):
        return 0
    d = json.load(open(src, encoding="utf-8"))
    dst = os.path.join(target_dir, "writer_decisions.json")
    out = json.load(open(dst, encoding="utf-8")) if os.path.exists(dst) else {
        "_help": d.get("_help"), "links": {}, "creates": []}
    n = 0
    for name in names:
        if d.get("links", {}).get(name):
            if not out["links"].get(name):
                out["links"][name] = d["links"][name]
                n += 1
        elif name in (d.get("creates") or []) and name not in out["creates"]:
            out["creates"].append(name)
            n += 1
        for k in ("_candidates", "_rationale"):
            if name in (d.get(k) or {}):
                out.setdefault(k, {}).setdefault(name, d[k][name])
    if n:
        out["_carried_from"] = os.path.relpath(src, target_dir)
        json.dump(out, open(dst, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return n
