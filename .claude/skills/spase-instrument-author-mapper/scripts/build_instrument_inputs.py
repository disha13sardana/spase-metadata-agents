#!/usr/bin/env python3
"""
build_instrument_inputs.py -- build the record writer's input for every
instrument of an Observatory from the Observatory's own author run.

The Observatory run's `instrument_roles` already say who authored each
instrument, with ORCIDs, affiliations and links resolved. This script turns them
into one writer input per instrument, so the whole mission's instruments can be
written in one writer run, with no per-instrument finder or enricher runs.

Which instruments
    Every Instrument record of the Observatory under any naming authority,
    matched on ObservatoryID (the Heliophysics Instruments API lists them, and
    each record is read from spase-metadata.org; --registry-source github reads
    the hpde repositories instead), plus the skeleton records the registrar has
    just created (its instrument_registrations.json, if present).

Which ones get a file
    - A record under the Observatory's own authority, present in the clone on the
      base branch: a writer input (see seed_inputs.py for the three kinds).
    - A record under another authority (NOAA's SUVI on an SMWG Observatory, say):
      report only. Its authors are listed in the mission report for that
      authority's curators; nothing is written for it.
    - A component inside a suite (EXIS/XRS inside EXIS): no file of its own. Records
      are kept at suite level, so its authors and links go on the suite's input.
    - --skip RID=reason: left out, with the reason in the report (a platform
      pseudo-instrument such as an ephemeris record, for example).

Outputs
    spase_records/<record-name>_<Acronym>/<file>    one per writable instrument
    spase_records/<record-name>/instrument_inputs.json   the mission report

Nothing is pushed or committed: these are JSON files in the agents repository.
The clone is only read, never changed.

Usage:
    python3 build_instrument_inputs.py --repo ~/SMWG \\
        --enriched spase_records/<record-name>/author_candidates_enriched.json

    --base NAME        branch whose records count as present (default: the
                       registration branch if it exists, else the Observatory
                       writer's branch, else the default branch)
    --plan PATH        the registrar's plan (default: beside the enriched file)
    --skip RID=REASON  leave an instrument out (repeatable)
    --dry-run          print what would be written; write nothing
    --registry-dir DIR read the registry from local clones instead of the API
    --no-instruments-api   skip the Heliophysics Instruments API (tests only)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRAR = os.path.normpath(os.path.join(
    HERE, "..", "..", "spase-missing-instrument-registrar", "scripts"))
sys.path.insert(0, HERE)
sys.path.insert(0, REGISTRAR)
import registry  # noqa: E402
import seed_inputs  # noqa: E402

RID_RE = re.compile(r"^spase://([A-Za-z0-9_-]+)/(Instrument|Observatory)/([A-Za-z0-9._/-]+)$")


def git(args, repo, check=True):
    p = subprocess.run(["git", "-C", repo] + args, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p


def branch_exists(repo, b):
    return git(["rev-parse", "--verify", "--quiet", b], repo, check=False).returncode == 0


def on_branch(repo, branch, rid):
    m = RID_RE.match(rid)
    path = "%s/%s.xml" % (m.group(2), m.group(3))
    return git(["cat-file", "-e", "%s:%s" % (branch, path)], repo, check=False).returncode == 0


def default_branch(repo):
    p = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo, check=False)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip().split("/", 1)[-1]
    for b in ("master", "main"):
        if branch_exists(repo, b):
            return b
    return None


def ipath(rid):
    return registry.instrument_path(rid) or ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--enriched", required=True)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--base", default=None)
    ap.add_argument("--records-dir", default=None)
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--registry-dir", default=None)
    ap.add_argument("--registry-cache", default=registry.DEFAULT_CACHE)
    ap.add_argument("--registry-source", choices=("site", "github"), default="site")
    ap.add_argument("--no-instruments-api", action="store_true")
    args = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(args.repo))
    enriched_path = os.path.abspath(args.enriched)
    enriched = json.load(open(enriched_path, encoding="utf-8"))
    obs = enriched.get("record") or ""
    om = RID_RE.match(obs)
    if not om or om.group(2) != "Observatory":
        print("ABORT: %s is not an Observatory run (record %r)." % (enriched_path, obs))
        return 2
    authority = om.group(1)
    obs_dir = os.path.dirname(enriched_path)
    records_dir = os.path.abspath(args.records_dir or os.path.dirname(obs_dir))
    slug = re.sub(r"[^a-z0-9]+", "-", om.group(3).lower()).strip("-")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ---- base branch -----------------------------------------------------
    base = args.base
    if not base:
        for b in ("instrument-registration-%s" % slug, "author-enrichment-%s" % slug):
            if branch_exists(repo, b):
                base = b
                break
    if not base:
        base = default_branch(repo)
        print("WARN     neither instrument-registration-%s nor author-enrichment-%s "
              "exists; reading records on %s" % (slug, slug, base))
    print("base     : %s" % base)

    # ---- the Observatory's instruments, under any authority ---------------
    try:
        recs, failed = registry.load_records(args.registry_dir, args.registry_cache,
                                             log=lambda s: print(s),
                                             source=args.registry_source)
    except Exception as exc:  # noqa: BLE001
        print("ABORT: registry lookup failed: %s" % exc)
        return 2
    mine, other = registry.split_failures(failed, obs)
    if any(not f.startswith("spase://") for f in mine):
        print("ABORT: the registry index is incomplete; an instrument could be missed:\n  "
              + "\n  ".join(mine))
        return 2
    if other:
        print("note     : %d record(s) under other Observatories could not be read at "
              "their ResourceID's address" % len(other))
    found = {}
    for f in mine:   # filed under this Observatory but unreadable: still an instrument
        rid = f.split(": ", 1)[0]
        found[rid] = {"id": rid, "names": [rid.rsplit("/", 1)[-1]], "new": False,
                      "unreadable": True}
        print("WARN     %s is listed by the API but not published at the address its "
              "ResourceID gives; included by its path" % rid)
    for r in registry.lookup(recs, obs):
        found[r["id"]] = {"id": r["id"], "names": r["names"], "new": False}
    if not args.no_instruments_api:
        try:
            items = registry.helio_instruments(os.path.dirname(args.registry_cache),
                                               log=lambda s: print(s))
        except Exception as exc:  # noqa: BLE001
            print("ABORT: Heliophysics Instruments API check failed: %s" % exc)
            return 2
        for h in registry.helio_lookup(items, obs):
            if found.get(h["spase_id"], {}).get("unreadable") and h.get("long_name"):
                found[h["spase_id"]]["names"].insert(0, h["long_name"])
            found.setdefault(h["spase_id"], {"id": h["spase_id"], "new": False,
                                             "names": [h.get("long_name") or "",
                                                       h["spase_id"].rsplit("/", 1)[-1]]})
    for rid in (enriched.get("instrument_coverage") or {}).get("spase_instruments") or []:
        if isinstance(rid, str) and rid.startswith("spase://"):
            found.setdefault(rid, {"id": rid, "names": [rid.rsplit("/", 1)[-1]], "new": False})

    plan_path = args.plan or os.path.join(obs_dir, "instrument_registrations.json")
    plan = json.load(open(plan_path, encoding="utf-8")) if os.path.exists(plan_path) else {}
    for e in plan.get("entries") or []:
        if e.get("action") == "create" and e.get("resource_id"):
            found[e["resource_id"]] = {
                "id": e["resource_id"], "new": True,
                "names": [e.get("resource_name") or ""] + list(e.get("alternate_names") or []),
                "components": list(e.get("components") or []), "instrument": e.get("instrument")}

    skips = {}
    for s in args.skip:
        rid, _, why = s.partition("=")
        skips[rid.strip()] = why.strip() or "skipped"

    # ---- suites and their components ----------------------------------------
    components_of = {rid: [] for rid in found}
    component = {}
    for rid in found:
        p = ipath(rid)
        parents = [o for o in found if o != rid and ipath(o) and p.startswith(ipath(o) + "/")]
        if parents:
            suite = max(parents, key=lambda o: len(ipath(o)))
            component[rid] = suite
            components_of[suite].append(rid)

    # ---- build -----------------------------------------------------------
    rows, writes, errors = [], [], []
    for rid in sorted(found):
        info = found[rid]
        auth = rid.split("/")[2]
        row = {"resource_id": rid, "authority": auth, "new": info["new"]}
        if rid in component:
            row.update(action="component", suite=component[rid],
                       note="component of the suite: its authors and links go on %s" % component[rid])
            rows.append(row)
            continue
        if rid in skips:
            row.update(action="skipped", reason=skips[rid])
            rows.append(row)
            continue
        names = [n for n in info["names"] if n]
        comps = list(info.get("components") or [])
        for s in components_of[rid]:
            comps += [n for n in found[s]["names"] if n] + [s.rsplit("/", 1)[-1]]
        entry = {"instrument": info.get("instrument") or rid.rsplit("/", 1)[-1],
                 "resource_id": rid, "resource_name": names[0] if names else "",
                 "alternate_names": names[1:], "components": comps,
                 "component_records": components_of[rid]}
        seed, status, reason, log, errs = seed_inputs.build_seed(enriched, entry, plan, today)
        if errs:
            errors += errs
            continue
        people = [{"name": c["name"], "roles": c["qualifying_roles"],
                   "confidence": c["confidence"]} for c in seed["candidates"]]
        row.update(status=status, reason=reason, people=people,
                   links=len(seed["information_urls"]), log=log,
                   components=components_of[rid])
        if auth != authority:
            row["action"] = "report_only"
            row["note"] = ("under the %s authority: not written; these authors are for "
                           "%s's curators" % (auth, auth))
        elif not on_branch(repo, base, rid):
            row["action"] = "not_in_clone"
            row["note"] = ("not in your clone on %s; pull %s or check the base branch"
                           % (base, "the latest records" if not info["new"]
                              else "the registration branch"))
        else:
            row["action"] = "write"
            d = os.path.join(records_dir, "%s_%s" % (os.path.basename(obs_dir),
                                                      rid.rsplit("/", 1)[-1]))
            path = os.path.join(d, seed_inputs.seed_filename(status))
            problem = seed_inputs.check_target(path)
            if problem:
                errors.append("%s: %s" % (rid, problem))
            row["file"] = os.path.relpath(path, os.path.dirname(records_dir))
            writes.append((path, d, seed))
        rows.append(row)

    # ---- report ----------------------------------------------------------
    label = {"ready": "READY", "needs_enrichment": "ENRICH", "needs_full_run": "FULL RUN"}
    print("instruments of %s: %d\n" % (obs, len(rows)))
    for r in rows:
        rid = r["resource_id"]
        if r["action"] == "component":
            print("COMPONENT %-50s -> %s" % (rid, r["suite"]))
        elif r["action"] == "skipped":
            print("SKIPPED   %-50s %s" % (rid, r["reason"]))
        elif r["action"] == "report_only":
            print("REPORT    %-50s %d people, %d links (%s)" % (
                rid, len(r["people"]), r["links"], r["note"]))
            for p in r["people"]:
                print("          - %s: %s (%s)" % (p["name"], ", ".join(p["roles"]), p["confidence"]))
        elif r["action"] == "not_in_clone":
            print("MISSING   %-50s %s" % (rid, r["note"]))
        else:
            print("%-9s %-50s %d people, %d links%s -> %s" % (
                label[r["status"]], rid, len(r["people"]), r["links"],
                " (new)" if r["new"] else "", r["file"]))
            if r["status"] != "ready":
                print("          %s" % r["reason"])
        for line in r.get("log") or []:
            if not line.startswith(("TEAM DEPTH", "NOT ENRICHED")):
                print("          %s" % line)
    for e in errors:
        print("ERROR    %s" % e)
    if errors:
        print("\nNothing written.")
        return 1

    report_path = os.path.join(obs_dir, "instrument_inputs.json")
    report = {"observatory_record": obs, "date": today, "base": base, "instruments": rows,
              "notes": ["Records under another authority are report only: their authors "
                        "are listed here for that authority's curators.",
                        "Components of a suite have no input of their own; their authors and "
                        "links are on the suite's input."]}
    if args.dry_run:
        print("\n(dry run: nothing written)")
        return 0
    for path, d, seed in writes:
        seed_inputs.write_file(path, seed)
        seed_inputs.carry_decisions(obs_dir, d, [c["name"] for c in seed["candidates"]])
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\nwrote %d writer input(s) and %s"
          % (len(writes), os.path.relpath(report_path, os.path.dirname(records_dir))))
    ready = [r["file"] for r in rows if r.get("action") == "write" and r["status"] == "ready"]
    if ready:
        print("\nnext: one writer run for the ready instruments:\n"
              "  python3 .claude/skills/spase-record-writer/scripts/run_pipeline.py "
              "--repo <clone> \\\n%s      --base %s \\\n"
              "      --branch author-enrichment-%s-instruments --initials <initials>"
              % ("".join("      --input %s \\\n" % f for f in ready), base, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
