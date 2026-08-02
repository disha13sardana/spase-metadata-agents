#!/usr/bin/env python3
"""
run_pipeline.py -- end-to-end application of enriched candidates to a SPASE clone.

Does the whole sequence in one command:
    clean-tree check -> branch -> baseline validation -> write -> re-validate
    -> abort+rollback on new errors -> commit -> push

Collision decisions are persisted per record in a decisions JSON file, so each
record is answered once rather than re-typed on every run.

Usage:
    python3 run_pipeline.py --repo ~/SMWG \
        --input spase_records/GOES_16/author_candidates_enriched.json \
        --initials DS

    # after filling in the decisions file it prints on first run:
    python3 run_pipeline.py --repo ~/SMWG --input ... --initials DS

    # batch over several records:
    python3 run_pipeline.py --repo ~/SMWG --initials DS \
        --input spase_records/GOES_16/author_candidates_enriched.json \
        --input spase_records/GOES_17/author_candidates_enriched.json

Flags:
    --no-push        stop after commit
    --no-commit      stop after writing (leaves changes unstaged)
    --branch NAME    override the derived branch name
    --checker PATH   path to spase-localcheck.py (default: alongside this file)

Exit codes: 0 success, 1 aborted, 2 usage error.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRITER = os.path.join(HERE, "write_records.py")


def run(cmd, cwd=None, check=True, quiet=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if not quiet and p.stdout:
        print(p.stdout.rstrip())
    if p.returncode != 0 and check and p.stderr:
        print(p.stderr.rstrip())
    return p


def git(args, cwd, check=True, quiet=True):
    return run(["git"] + args, cwd=cwd, check=check, quiet=quiet)


def record_slug(input_path, data):
    """GOES_16 from the directory name, else from the ResourceID."""
    d = os.path.basename(os.path.dirname(os.path.abspath(input_path)))
    if d and d not in (".", "spase_records"):
        return d
    rid = data.get("record", "")
    return re.sub(r"[^A-Za-z0-9]+", "_", rid.split("/", 2)[-1]).strip("_") or "record"


def parse_errors(text):
    """Set of 'file :: message' lines from the checker output."""
    out, current = set(), None
    for line in text.splitlines():
        m = re.match(r"\[(?:ERROR|WARN |ok   )\] (.+)", line)
        if m:
            current = m.group(1)
        elif line.strip().startswith("ERROR ") and current:
            out.add("%s :: %s" % (current, line.strip()))
    return out


def check(checker, repo, targets):
    p = subprocess.run([sys.executable, checker, "--quiet"] + targets,
                       cwd=repo, capture_output=True, text=True)
    return parse_errors(p.stdout), p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--input", action="append", required=True,
                    help="enriched JSON; repeat for batch runs")
    ap.add_argument("--initials", default="")
    ap.add_argument("--branch", default=None)
    ap.add_argument("--checker", default=os.path.join(HERE, "spase-localcheck.py"))
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--remote", default="origin")
    args = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(args.repo))
    checker = os.path.abspath(os.path.expanduser(args.checker))
    if not os.path.isfile(checker):
        print("checker not found: %s (pass --checker)" % checker)
        return 2
    if not os.path.isdir(os.path.join(repo, ".git")):
        print("not a git repo: %s" % repo)
        return 2

    # ---- 1. clean tree ----------------------------------------------------
    dirty = git(["status", "--porcelain"], repo).stdout.strip()
    if dirty:
        print("ABORT: working tree is not clean. Commit or stash first:\n")
        print(dirty)
        return 1

    inputs = [os.path.abspath(os.path.expanduser(i)) for i in args.input]
    for i in inputs:
        if not os.path.isfile(i):
            print("input not found: %s" % i)
            return 2

    first = json.load(open(inputs[0], encoding="utf-8"))
    slug = record_slug(inputs[0], first)
    branch = args.branch or ("author-enrichment-%s" % slug.lower().replace("_", "-"))
    if len(inputs) > 1 and not args.branch:
        branch = "author-enrichment-batch-%d-records" % len(inputs)

    start_branch = git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()

    # ---- 2. branch --------------------------------------------------------
    exists = git(["rev-parse", "--verify", branch], repo, check=False).returncode == 0
    git(["checkout", branch] if exists else ["checkout", "-b", branch], repo)
    print("branch   : %s%s" % (branch, " (existing)" if exists else " (new)"))

    # ---- 3. baseline ------------------------------------------------------
    targets = []
    for i in inputs:
        rid = json.load(open(i, encoding="utf-8")).get("record", "")
        if rid.startswith("spase://"):
            targets.append(rid[len("spase://"):].split("/", 1)[1] + ".xml")
    targets.append("Person")
    base_errors, _ = check(checker, repo, targets)
    print("baseline : %d pre-existing error(s)" % len(base_errors))

    # ---- 4. write ---------------------------------------------------------
    wrote_any = False
    for i in inputs:
        data = json.load(open(i, encoding="utf-8"))
        s = record_slug(i, data)
        decisions = os.path.join(os.path.dirname(i), "writer_decisions.json")
        print("\n=== %s ===" % s)
        cmd = [sys.executable, WRITER, "--repo", repo, "--input", i,
               "--decisions", decisions]
        if args.initials:
            cmd += ["--initials", args.initials]
        p = run(cmd)
        if p.returncode != 0:
            print("\nABORT: writer stopped on %s. Rolling back." % s)
            git(["checkout", "--", "."], repo)
            git(["clean", "-fd", "Person"], repo)
            if not exists:
                git(["checkout", start_branch], repo)
                git(["branch", "-D", branch], repo)
            print("\nResolve the flagged names in:\n  %s\nthen re-run this command."
                  % decisions)
            return 1
        wrote_any = True

    if not wrote_any:
        print("nothing written")
        return 1

    # ---- 5. re-validate ---------------------------------------------------
    new_errors, out = check(checker, repo, targets)
    introduced = new_errors - base_errors
    print("\nvalidation: %d error(s) total, %d introduced by this run"
          % (len(new_errors), len(introduced)))
    if introduced:
        print("\nABORT: this run introduced new errors. Rolling back.\n")
        for e in sorted(introduced):
            print("  " + e)
        git(["checkout", "--", "."], repo)
        git(["clean", "-fd", "Person"], repo)
        if not exists:
            git(["checkout", start_branch], repo)
            git(["branch", "-D", branch], repo)
        return 1

    print("\n" + git(["diff", "--stat"], repo).stdout.rstrip())
    untracked = git(["ls-files", "-o", "--exclude-standard"], repo).stdout.strip()
    if untracked:
        print("new files: %d" % len(untracked.splitlines()))

    if args.no_commit:
        print("\n--no-commit: changes left in the working tree.")
        return 0

    # ---- 6. commit --------------------------------------------------------
    git(["add", "-A"] + [t for t in targets], repo)
    msg = ("%s: add mission Contacts with Author and qualifying roles\n\n"
           "Applied enriched author candidates: Contact blocks on the "
           "observatory record, Person records created and updated with "
           "affiliation, ORCID and ROR, and schemaLocation corrected to match "
           "the declared SPASE Version." % slug.replace("_", " "))
    c = git(["commit", "-m", msg], repo, check=False, quiet=False)
    if c.returncode != 0:
        print("commit failed")
        return 1
    print("committed on %s" % branch)

    if args.no_push:
        print("--no-push: stopping. Push with:\n  git push -u %s %s"
              % (args.remote, branch))
        return 0

    # ---- 7. push ----------------------------------------------------------
    if branch in ("master", "main"):
        print("refusing to push to %s" % branch)
        return 1
    p = git(["push", "-u", args.remote, branch], repo, check=False, quiet=False)
    if p.returncode != 0:
        print("\npush failed; the commit is safe on %s locally." % branch)
        return 1
    print("pushed %s to %s" % (branch, args.remote))
    print("Open a PR from that branch when the diff and divergence log look right.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
