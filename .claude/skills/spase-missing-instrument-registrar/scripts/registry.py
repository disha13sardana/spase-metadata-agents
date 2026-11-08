#!/usr/bin/env python3
"""
registry.py -- index every SPASE Instrument record, under every naming authority.

Default source: the Heliophysics Instruments API plus spase-metadata.org.

1. The Heliophysics Instruments API (https://api.heliophysics.net/api/instruments/)
   lists every registered instrument, `{id, long_name, spase_id}`, across all
   authorities, in one request.
2. Each instrument's record is published at spase-metadata.org under its
   ResourceID: spase://ASWS/Instrument/Ground/Alice_Springs/Ionosonde is
   https://spase-metadata.org/ASWS/Instrument/Ground/Alice_Springs/Ionosonde.xml,
   and its <ObservatoryID> says which Observatory it belongs to.

Together they answer "which instruments belong to this Observatory, under any
authority and wherever they are filed". No GitHub token is needed. The first
build fetches every Instrument record once (a few thousand small files); after
that only instruments new to the API, and records older than 30 days, are
fetched again. Cached at ~/.cache/spase-registry/site-instruments.json; the API
list itself is cached for a day.

Alternative source (--source github): the hpde GitHub organisation
(https://github.com/hpde), one repository per naming authority, read through the
GitHub API; it detects changed files exactly by blob SHA, but needs a GitHub
token for its first build (60 unauthenticated calls an hour).

Offline / test mode: --registry-dir DIR, where each sub-directory of DIR is a
clone of an authority repository (or DIR is an hpde.io checkout, whose top-level
folders are authorities).

CLI:
    registry.py refresh
    registry.py lookup --observatory spase://SMWG/Observatory/<Path> [--name ABI ...]
    registry.py lookup --observatory ... --source github
    registry.py lookup --observatory ... --registry-dir ~/hpde-clones
"""

import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ORG = "hpde"
HELIO_API = os.environ.get("SPASE_HELIO_API", "https://api.heliophysics.net/api/instruments/")
HELIO_MAX_AGE = 24 * 3600
SITE = os.environ.get("SPASE_SITE", "https://spase-metadata.org")
SITE_MAX_AGE = 30 * 24 * 3600
SITE_WORKERS = 8
API = os.environ.get("SPASE_REGISTRY_API", "https://api.github.com")
RAW = os.environ.get("SPASE_REGISTRY_RAW", "https://raw.githubusercontent.com")
DEFAULT_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "spase-registry",
                             "instruments.json")
CACHE_VERSION = 1
USER_AGENT = "spase-missing-instrument-registrar"


# --------------------------------------------------------------------------
# shared helpers (also used by register_instruments.py)
# --------------------------------------------------------------------------

def name_key(s):
    """Fold a name for comparison: 'ABC', 'abc', 'A.B.C.' all match."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def observatory_key(rid):
    """The part of an Observatory ResourceID after the authority, folded.

    spase://SMWG/Observatory/Foo/Bar and spase://NASA/Observatory/Foo/Bar give
    the same key: the same mission registered under two authorities.
    """
    m = re.match(r"^spase://[^/]+/Observatory/(.+)$", (rid or "").strip())
    return m.group(1).strip("/").lower() if m else None


def parse_instrument(text):
    rid = re.search(r"<ResourceID>\s*([^<]+?)\s*</ResourceID>", text)
    obs = re.search(r"<ObservatoryID>\s*([^<]+?)\s*</ObservatoryID>", text)
    names = re.findall(r"<(?:ResourceName|AlternateName)>\s*([^<]+?)\s*</", text)
    if not rid:
        return None
    rid = rid.group(1)
    names.append(rid.rsplit("/", 1)[-1])
    return {"id": rid, "obs": obs.group(1) if obs else None,
            "names": sorted({n for n in names if n})}


# --------------------------------------------------------------------------
# GitHub API
# --------------------------------------------------------------------------

def github_token():
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    if shutil.which("gh"):
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return None


class Fetcher:
    def __init__(self, token=None, api=API, raw=RAW):
        self.token, self.api, self.raw = token, api.rstrip("/"), raw.rstrip("/")
        self.api_calls = 0

    def _get(self, url, accept=None, auth=True):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if accept:
            req.add_header("Accept", accept)
        if auth and self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
                    reset = e.headers.get("X-RateLimit-Reset")
                    raise RuntimeError(
                        "GitHub API rate limit reached%s. Set GITHUB_TOKEN (or log in "
                        "with `gh auth login`) and re-run; the work done so far is "
                        "cached." % (" until %s" % time.strftime(
                            "%H:%M", time.localtime(int(reset))) if reset else ""))
                if e.code in (404, 410):
                    raise
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("GET %s failed: %s" % (url, last))

    def api_json(self, path):
        self.api_calls += 1
        return json.loads(self._get(self.api + path,
                                    accept="application/vnd.github+json"))

    def raw_text(self, repo, branch, path):
        url = "%s/%s/%s/%s/%s" % (self.raw, ORG, repo, branch,
                                  urllib.request.quote(path))
        return self._get(url, auth=False).decode("utf-8", "replace")


def list_repos(f):
    repos, page = [], 1
    while True:
        batch = f.api_json("/orgs/%s/repos?per_page=100&page=%d" % (ORG, page))
        if not batch:
            break
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r.get("archived")]


def instrument_files(f, repo, branch):
    """{path: blob_sha} for every Instrument/**/*.xml, or None if no Instrument/."""
    root = f.api_json("/repos/%s/%s/git/trees/%s" % (ORG, repo, branch))
    inst = [t for t in root.get("tree", []) if t["path"] == "Instrument" and t["type"] == "tree"]
    if not inst:
        return None
    sub = f.api_json("/repos/%s/%s/git/trees/%s?recursive=1" % (ORG, repo, inst[0]["sha"]))
    if sub.get("truncated"):
        raise RuntimeError("the Instrument tree of hpde/%s is too large for one API "
                           "call; use --registry-dir with a local clone instead" % repo)
    return {"Instrument/" + t["path"]: t["sha"] for t in sub.get("tree", [])
            if t["type"] == "blob" and t["path"].endswith(".xml")}


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

def load_cache(path):
    try:
        c = json.load(open(path, encoding="utf-8"))
        if c.get("version") == CACHE_VERSION:
            return c
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "org": ORG, "repos": {}, "blobs": {}}


def refresh(cache_path=DEFAULT_CACHE, token=None, workers=16, log=print):
    """Bring the cached index up to date from the GitHub API. Returns the cache."""
    token = token if token is not None else github_token()
    f = Fetcher(token)
    if not token:
        log("registry: no GitHub token; the API allows 60 calls an hour")
    cache = load_cache(cache_path)
    repos = list_repos(f)
    seen = set()
    todo = []
    for r in repos:
        name, branch, pushed = r["name"], r.get("default_branch") or "master", r.get("pushed_at")
        seen.add(name)
        old = cache["repos"].get(name)
        if old and old.get("pushed_at") == pushed and old.get("branch") == branch:
            continue
        files = instrument_files(f, name, branch)
        cache["repos"][name] = {"branch": branch, "pushed_at": pushed,
                                "files": files or {}, "has_instruments": files is not None}
    for gone in set(cache["repos"]) - seen:
        del cache["repos"][gone]
    for name, info in cache["repos"].items():
        for path, sha in info["files"].items():
            if sha not in cache["blobs"]:
                todo.append((name, info["branch"], path, sha))
    if todo:
        log("registry: downloading %d new or changed Instrument files" % len(todo))
    failed = []

    def get(item):
        name, branch, path, sha = item
        try:
            return item, parse_instrument(f.raw_text(name, branch, path))
        except Exception as e:  # noqa: BLE001 -- reported below
            return item, e

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for item, res in ex.map(get, todo):
            if isinstance(res, Exception) or res is None:
                failed.append((item, res))
            else:
                cache["blobs"][item[3]] = res
    live = {sha for info in cache["repos"].values() for sha in info["files"].values()}
    cache["blobs"] = {k: v for k, v in cache["blobs"].items() if k in live}
    cache["refreshed"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cache["failed"] = ["hpde/%s/%s: %s" % (i[0], i[2], e) for i, e in failed]
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    tmp = cache_path + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, cache_path)
    log("registry: %d authority repositories with Instrument records, %d records, "
        "%d API calls%s" % (sum(1 for i in cache["repos"].values() if i["files"]),
                            len(live), f.api_calls,
                            ", %d files UNREADABLE" % len(failed) if failed else ""))
    return cache


def records_from_cache(cache):
    out = []
    for name, info in cache["repos"].items():
        for path, sha in info["files"].items():
            rec = cache["blobs"].get(sha)
            if rec:
                out.append(dict(rec, repo=name, path=path,
                                where="hpde/%s/%s" % (name, path)))
    return out, list(cache.get("failed") or [])


def records_from_dir(root):
    """Offline mode: root/<Authority>/Instrument/**/*.xml."""
    out, failed = [], []
    for f in glob.glob(os.path.join(root, "*", "Instrument", "**", "*.xml"), recursive=True):
        try:
            rec = parse_instrument(open(f, encoding="utf-8", errors="replace").read())
        except OSError as e:
            failed.append("%s: %s" % (f, e))
            continue
        if rec:
            rel = os.path.relpath(f, root)
            out.append(dict(rec, repo=rel.split(os.sep)[0],
                            path=rel.split(os.sep, 1)[1], where=f))
    return out, failed


def site_url(spase_id):
    path = spase_id.strip()[len("spase://"):]
    return "%s/%s.xml" % (SITE.rstrip("/"), urllib.request.quote(path))


def refresh_site(cache_dir=os.path.dirname(DEFAULT_CACHE), log=print,
                 max_age=SITE_MAX_AGE, workers=SITE_WORKERS):
    """Index every API-listed instrument by fetching its record from the site."""
    items = helio_instruments(cache_dir, log=log)
    path = os.path.join(cache_dir, "site-instruments.json")
    try:
        cache = json.load(open(path, encoding="utf-8"))
        assert cache.get("version") == CACHE_VERSION
    except (OSError, ValueError, AssertionError):
        cache = {"version": CACHE_VERSION, "records": {}}
    now = time.time()
    listed = {i["spase_id"].strip() for i in items}
    todo = [rid for rid in sorted(listed)
            if now - (cache["records"].get(rid) or {}).get("fetched", 0) > max_age]
    if todo:
        log("registry: fetching %d Instrument record(s) from %s" % (len(todo), SITE))
    f, failed = Fetcher(), []

    def get(rid):
        try:
            return rid, parse_instrument(f._get(site_url(rid), auth=False).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            return rid, RuntimeError("HTTP %s at %s" % (e.code, site_url(rid)))
        except Exception as e:  # noqa: BLE001 -- reported below
            return rid, e

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for rid, res in ex.map(get, todo):
            if isinstance(res, Exception) or res is None:
                failed.append("%s: %s" % (rid, res or "no ResourceID in the record"))
            else:
                cache["records"][rid] = dict(res, fetched=now)
    cache["records"] = {k: v for k, v in cache["records"].items() if k in listed}
    os.makedirs(cache_dir, exist_ok=True)
    tmp = path + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, path)
    log("registry: %d instruments listed by the API, %d records indexed%s"
        % (len(listed), len(cache["records"]),
           ", %d UNREADABLE" % len(failed) if failed else ""))
    out = [dict(r, repo=r["id"].split("/")[2], where=site_url(r["id"]))
           for r in cache["records"].values()]
    return out, failed


def load_records(registry_dir=None, cache_path=DEFAULT_CACHE, refresh_first=True,
                 log=print, source="site"):
    """(records, unreadable) from a local directory, the site or the GitHub API."""
    if registry_dir:
        return records_from_dir(os.path.expanduser(registry_dir))
    if source == "site":
        return refresh_site(os.path.dirname(cache_path), log=log)
    cache = refresh(cache_path, log=log) if refresh_first else load_cache(cache_path)
    return records_from_cache(cache)


# --------------------------------------------------------------------------
# Heliophysics Instruments API
# --------------------------------------------------------------------------

def helio_instruments(cache_dir=os.path.dirname(DEFAULT_CACHE), max_age=HELIO_MAX_AGE,
                      log=print):
    """Every instrument the Heliophysics API lists: [{id, long_name, spase_id}]."""
    path = os.path.join(cache_dir, "heliophysics-instruments.json")
    try:
        c = json.load(open(path, encoding="utf-8"))
        if time.time() - c.get("fetched", 0) < max_age:
            return c["items"]
    except (OSError, ValueError, KeyError):
        pass
    f = Fetcher()
    items = json.loads(f._get(HELIO_API, accept="application/json", auth=False))
    if isinstance(items, dict):            # tolerate a paginated wrapper
        items = items.get("results") or items.get("items") or []
    items = [i for i in items if isinstance(i, dict) and i.get("spase_id")]
    if not items:
        raise RuntimeError("the Heliophysics Instruments API returned no instruments")
    os.makedirs(cache_dir, exist_ok=True)
    json.dump({"fetched": time.time(), "url": HELIO_API, "items": items},
              open(path, "w", encoding="utf-8"))
    log("registry: Heliophysics Instruments API lists %d instruments" % len(items))
    return items


def instrument_path(rid):
    m = re.match(r"^spase://[^/]+/Instrument/(.+)$", (rid or "").strip())
    return m.group(1).strip("/").lower() if m else None


def helio_lookup(items, observatory, names=()):
    """API instruments filed under this Observatory's path, under any authority.

    The API has no ObservatoryID, so this goes by the path convention
    (Instrument/<ObservatoryPath>/...); the GitHub index covers records filed
    elsewhere.
    """
    okey = observatory_key(observatory)
    keys = {name_key(n) for n in names if name_key(n)}
    out = []
    for i in items:
        p = instrument_path(i["spase_id"])
        if okey and p and p.startswith(okey + "/"):
            mine = {name_key(i.get("long_name")), name_key(i["spase_id"].rsplit("/", 1)[-1])}
            out.append(dict(i, shared=sorted(keys & mine)))
    return sorted(out, key=lambda r: r["spase_id"])


def helio_exact(items, rid):
    want = (rid or "").strip().lower()
    return [i for i in items if i["spase_id"].strip().lower() == want]


def split_failures(failed, observatory):
    """Unreadable records that could belong to this Observatory, and the rest.

    A few records are published at a path that differs from their ResourceID,
    so the site has nothing at the address the ID gives. Only those filed under
    this Observatory's path matter for it; any other source of failure (the
    GitHub source names files, not IDs) is treated as relevant.
    """
    okey, mine, other = observatory_key(observatory), [], []
    for f in failed:
        rid = f.split(": ", 1)[0]
        p = instrument_path(rid)
        if p is None or (okey and p.startswith(okey + "/")):
            mine.append(f)
        else:
            other.append(f)
    return mine, other


def lookup(records, observatory, names=()):
    """Records of this Observatory under any authority, and which share a name."""
    okey = observatory_key(observatory)
    keys = {name_key(n) for n in names if name_key(n)}
    same_obs = []
    for r in records:
        if observatory_key(r.get("obs")) == okey:
            hit = dict(r, shared=sorted(keys & {name_key(n) for n in r["names"]}))
            same_obs.append(hit)
    return sorted(same_obs, key=lambda r: r["id"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("refresh", "lookup"):
        p = sub.add_parser(name)
        p.add_argument("--cache", default=DEFAULT_CACHE)
        p.add_argument("--registry-dir", default=None)
        p.add_argument("--source", choices=("site", "github"), default="site")
        if name == "lookup":
            p.add_argument("--observatory", required=True)
            p.add_argument("--name", action="append", default=[])
            p.add_argument("--no-refresh", action="store_true")
            p.add_argument("--no-instruments-api", action="store_true")
    a = ap.parse_args()
    if a.cmd == "refresh":
        if a.source == "site":
            refresh_site(os.path.dirname(a.cache))
        else:
            refresh(a.cache)
        return 0
    recs, failed = load_records(a.registry_dir, a.cache, not a.no_refresh, source=a.source)
    hits = lookup(recs, a.observatory, a.name)
    print("Instrument records for %s under any authority: %d" % (a.observatory, len(hits)))
    for h in hits:
        print("  %-55s %s%s" % (h["id"], ", ".join(h["names"]),
                                "   <- shares %s" % h["shared"] if h["shared"] else ""))
    mine, other = split_failures(failed, a.observatory)
    for x in mine:
        print("UNREADABLE  %s" % x)
    if other:
        print("(%d record(s) elsewhere in the registry are published at a path that "
              "differs from their ResourceID; none is filed under this Observatory)"
              % len(other))
    if not a.no_instruments_api and (a.registry_dir or a.source != "site"):
        items = helio_instruments(os.path.dirname(a.cache))
        api = helio_lookup(items, a.observatory, a.name)
        known = {h["id"].lower() for h in hits}
        print("Heliophysics Instruments API, filed under this Observatory's path: %d"
              % len(api))
        for h in api:
            print("  %-55s %s%s%s" % (h["spase_id"], h.get("long_name") or "",
                                      "   <- shares %s" % h["shared"] if h["shared"] else "",
                                      "   (not in the hpde index)"
                                      if h["spase_id"].lower() not in known else ""))
    return 1 if mine else 0


if __name__ == "__main__":
    sys.exit(main())
