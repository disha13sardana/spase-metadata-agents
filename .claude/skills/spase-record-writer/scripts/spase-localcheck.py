#!/usr/bin/env python3
"""
spase-localcheck.py -- fast, dependency-free pre-flight checks for SPASE records.

This APPROXIMATES `spase-refcheck`. It is a fast local loop, not a substitute
for CI. Run CI before opening a PR.

Checks performed per file:
  1. XML well-formedness
  2. ResourceID matches the file's path on disk
  3. Every spase:// reference in the same authority resolves to a file
  4. Version element vs xsi:schemaLocation agreement (warning only)

Usage:
    python3 spase-localcheck.py Observatory/GOES
    python3 spase-localcheck.py Observatory/GOES/16.xml Person/
    python3 spase-localcheck.py --repo-root ~/SMWG Observatory/GOES
    python3 spase-localcheck.py --quiet Observatory        # errors/warnings only

Exit code is 1 if any ERROR was found, else 0 (usable in a git hook or CI).
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

# References that intentionally point at retired IDs; not resolvable by design.
NON_RESOLVING_ELEMENTS = {"PriorID"}

SPASE_PREFIX = "spase://"
SCHEMA_VER_RE = re.compile(r"spase-(\d+)_(\d+)_(\d+)\.xsd")


def strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def find_repo_root(start):
    """Walk upward looking for a .git directory."""
    cur = os.path.abspath(start)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def collect_xml_files(targets):
    files = []
    for t in targets:
        if os.path.isdir(t):
            for dirpath, dirnames, filenames in os.walk(t):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                for fn in sorted(filenames):
                    if fn.lower().endswith(".xml"):
                        files.append(os.path.join(dirpath, fn))
        elif os.path.isfile(t):
            files.append(t)
        else:
            print("  [ERROR] no such path: %s" % t)
    return sorted(set(files))


def id_to_path(resource_id, repo_root):
    """spase://SMWG/Person/Jane.Doe -> <repo_root>/Person/Jane.Doe.xml"""
    body = resource_id[len(SPASE_PREFIX):]
    parts = body.split("/", 1)
    if len(parts) != 2:
        return None, None
    authority, rest = parts
    return authority, os.path.join(repo_root, rest + ".xml")


def check_file(path, repo_root, repo_authority):
    """Return (errors, warnings, info) as lists of strings."""
    errors, warnings, info = [], [], []

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return (["not well-formed XML: %s" % e], [], [])
    root = tree.getroot()

    # --- ResourceID vs path -------------------------------------------------
    own_ids = [el for el in root.iter() if strip_ns(el.tag) == "ResourceID"]
    if not own_ids:
        errors.append("no ResourceID element found")
    else:
        rid = (own_ids[0].text or "").strip()
        if not rid.startswith(SPASE_PREFIX):
            errors.append("ResourceID missing spase:// prefix: %r" % rid)
        else:
            authority, expected = id_to_path(rid, repo_root)
            if expected is None:
                errors.append("malformed ResourceID: %r" % rid)
            elif os.path.abspath(expected) != os.path.abspath(path):
                errors.append(
                    "ResourceID/path mismatch: %s implies %s"
                    % (rid, os.path.relpath(expected, repo_root))
                )
        if len(own_ids) > 1:
            info.append("%d ResourceID elements present" % len(own_ids))

    # --- schemaLocation vs Version -----------------------------------------
    schema_loc = ""
    for k, v in root.attrib.items():
        if strip_ns(k) == "schemaLocation":
            schema_loc = v
    ver_el = [el for el in root.iter() if strip_ns(el.tag) == "Version"]
    declared = ver_el[0].text.strip() if ver_el and ver_el[0].text else ""
    m = SCHEMA_VER_RE.search(schema_loc)
    if m and declared:
        schema_ver = ".".join(m.groups())
        d = declared.split(".")
        s = schema_ver.split(".")
        if d[:2] != s[:2]:
            warnings.append(
                "Version %s but schemaLocation points at spase-%s.xsd"
                % (declared, schema_ver.replace(".", "_"))
            )

    # --- references ---------------------------------------------------------
    for el in root.iter():
        name = strip_ns(el.tag)
        text = (el.text or "").strip()
        if not text.startswith(SPASE_PREFIX):
            continue
        if name in NON_RESOLVING_ELEMENTS:
            info.append("%s (not resolved by design): %s" % (name, text))
            continue

        authority, target = id_to_path(text, repo_root)
        if target is None:
            errors.append("%s malformed: %r" % (name, text))
            continue
        if authority != repo_authority:
            info.append(
                "%s -> external authority %r, not checked: %s"
                % (name, authority, text)
            )
            continue
        if "UNKNOWN" in text:
            warnings.append("%s is a placeholder: %s" % (name, text))
        if not os.path.isfile(target):
            errors.append(
                "%s dangling: %s (expected %s)"
                % (name, text, os.path.relpath(target, repo_root))
            )

    return errors, warnings, info


def main():
    ap = argparse.ArgumentParser(
        description="Fast local SPASE reference checks (approximates spase-refcheck)."
    )
    ap.add_argument("targets", nargs="+", help="XML files and/or directories")
    ap.add_argument("--repo-root", default=None,
                    help="repo root (default: nearest ancestor containing .git)")
    ap.add_argument("--authority", default="SMWG",
                    help="authority resolved locally (default: SMWG)")
    ap.add_argument("--quiet", action="store_true",
                    help="only print files with errors or warnings")
    args = ap.parse_args()

    repo_root = args.repo_root or find_repo_root(args.targets[0])
    if not repo_root:
        print("Could not locate repo root; pass --repo-root explicitly.")
        return 2
    repo_root = os.path.abspath(os.path.expanduser(repo_root))

    files = collect_xml_files(args.targets)
    if not files:
        print("No XML files found.")
        return 2

    print("repo root : %s" % repo_root)
    print("authority : %s" % args.authority)
    print("files     : %d\n" % len(files))

    n_err = n_warn = n_clean = 0
    for f in files:
        errors, warnings, info = check_file(f, repo_root, args.authority)
        rel = os.path.relpath(f, repo_root)
        if errors:
            n_err += 1
        elif warnings:
            n_warn += 1
        else:
            n_clean += 1

        if args.quiet and not errors and not warnings:
            continue

        status = "ERROR" if errors else ("WARN " if warnings else "ok   ")
        print("[%s] %s" % (status, rel))
        for e in errors:
            print("    ERROR  %s" % e)
        for w in warnings:
            print("    WARN   %s" % w)
        if not args.quiet:
            for i in info:
                print("    info   %s" % i)

    print("\n%d ok, %d with warnings, %d with errors" % (n_clean, n_warn, n_err))
    print("NOTE: approximates spase-refcheck. Run CI before opening a PR.")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
