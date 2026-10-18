#!/usr/bin/env python3
"""troymeekhof.com site tool. Standard library only.

The files in this repo ARE the website and the single source of truth.
Nothing regenerates them. Every change is a small edit to the live file.

  python3 _src/site.py check                  whole-site sanity: links, JSON-LD, sitemap, banned text
  python3 _src/site.py guard [--base SHA]     regression guard for commits since BASE (default HEAD~1):
                                              blocks deleted pages, pages reverted to an older version,
                                              and big content drops, unless the commit message says so
  python3 _src/site.py replace FILE OLD NEW   exact, single-occurrence text replace with a diff printout
  python3 _src/site.py stage OUTDIR           copy the public files (what GitHub Pages serves) to OUTDIR

Override tokens (put in the commit message, only when Troy asked for it):
  [allow-delete]  a public file is intentionally removed
  [allow-revert]  a file is intentionally restored to an earlier version
  [allow-shrink]  a page intentionally loses more than 20% of its text (e.g. retired to a redirect stub)
"""
import difflib, hashlib, html, json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://troymeekhof.com"
SHRINK_LIMIT = 0.20      # fraction of main-text words a page may lose without [allow-shrink]
SHRINK_MIN_WORDS = 40    # ignore tiny absolute changes

BANNED = [  # carried over from build.py's validator
    (r"Filmmaker\W+Marketer\W+(?:The\s+)?Cybertruck Guy", "banned tagline"),
    (r"real people, real stories", "retired tagline"),
    (r"stucco|\b1915\b", "house thread"),
    (r"Torque News", "Torque News"),
    (r"tnmeekhof@gmail\.com", "private email"),
    (r"\[(?:VIDEO EMBED|PLACEHOLDER|NUMBER|RUNTIME|YEAR|COUPLE|VENUE|BUDGET|SEASON|CAMERA)[^\]]*\]", "bracketed placeholder"),
    (r"Troy to (?:supply|confirm)", "placeholder note"),
    (r"500 clicks|50 to 500", "wrong Treadstone traffic figure (true: 20+ to 300+ clicks a day)"),
    (r"Search Gap|1,197|1,997|3,497", "retired GRMC product/pricing"),
    (r"maxresdefault", "YouTube maxres thumbnail (use hqdefault)"),
]


def is_public(rel):
    """Mirror GitHub Pages/Jekyll defaults: anything with a path part starting with '.' or '_' is not served."""
    parts = Path(rel).parts
    return not any(p.startswith((".", "_")) for p in parts) and rel not in ("CLAUDE.md", "README.md")


def public_files(root=ROOT):
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if is_public(rel):
                out.append(rel)
    return out


def main_words(text):
    m = re.search(r"<main[^>]*>(.*?)</main>", text, re.S)
    body = m.group(1) if m else text
    body = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", body, flags=re.S)
    return len(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, errors="replace")
    if check and r.returncode:
        sys.exit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


# ---------------------------------------------------------------- check
def cmd_check():
    problems = []
    files = public_files()
    fileset = set(files)
    htmls = [f for f in files if f.endswith(".html")]

    def exists(target):
        t = target.split("#")[0].split("?")[0]
        if not t or t == "/":
            return "index.html" in fileset
        t = t.lstrip("/")
        return t in fileset or (t.rstrip("/") + "/index.html") in fileset

    for f in htmls:
        t = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        for block in re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', t, re.S):
            try:
                json.loads(block)
            except json.JSONDecodeError as e:
                problems.append("%s: broken JSON-LD (%s)" % (f, e))
        for ref in re.findall(r'(?:href|src)="([^"]+)"', t):
            if ref.startswith(SITE):
                ref = ref[len(SITE):] or "/"
            if ref.startswith("/") and not ref.startswith("//") and not exists(ref):
                problems.append("%s: broken link %s" % (f, ref))
        for rx, what in BANNED:
            m = re.search(rx, t, re.I)
            if m:
                problems.append("%s: banned text (%s): %r" % (f, what, m.group(0)))
        if f != "404.html" and "<title>" not in t:
            problems.append("%s: no <title>" % f)
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        for loc in re.findall(r"<loc>([^<]+)</loc>", sm.read_text(encoding="utf-8")):
            path = loc.replace(SITE, "") or "/"
            if not exists(path):
                problems.append("sitemap.xml: %s does not exist" % loc)
                continue
            page = (ROOT / (path.lstrip("/") + ("index.html" if path.endswith("/") else ""))).read_text(encoding="utf-8", errors="replace")
            if re.search(r'<meta name="robots" content="[^"]*noindex', page):
                problems.append("sitemap.xml lists a noindex page: %s" % loc)
    for extra in ("llms.txt", "rss.xml"):
        p = ROOT / extra
        if p.exists():
            t = p.read_text(encoding="utf-8")
            for url in re.findall(re.escape(SITE) + r"(/[^\s<\"')]*)", t):
                if not exists(url):
                    problems.append("%s: points to missing page %s" % (extra, url))
            for rx, what in BANNED:
                if re.search(rx, t, re.I):
                    problems.append("%s: banned text (%s)" % (extra, what))
    report("check", problems, "%d public files, %d pages" % (len(files), len(htmls)))


def _lines(rev, path):
    return git("show", "%s:%s" % (rev, path)).splitlines()


def built_from_old_copy(path, base, head, depth=15):
    """Return the short sha of an older version this change is closer to than BASE, or None.
    Catches the classic mistake: start from a stale copy, make a small edit, overwrite the live file."""
    new = _lines(head, path)
    cur = _lines(base, path)
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(new)
    sm.set_seq1(cur)
    base_ratio = sm.ratio()
    revs = git("log", "--format=%H", "-n", str(depth + 1), base, "--", path).split()[1:]
    for rev in revs:
        try:
            old = _lines(rev, path)
        except SystemExit:
            continue
        if old == cur:
            continue
        sm.set_seq1(old)
        r = sm.ratio()
        if r > 0.6 and r > base_ratio + 0.02:
            return rev[:7]
    return None


# ---------------------------------------------------------------- guard
def cmd_guard(base):
    head = git("rev-parse", "HEAD").strip()
    if not base or set(base) == {"0"}:
        base = git("rev-parse", "HEAD~1", check=False).strip()
        if not base:
            print("guard: first commit, nothing to compare")
            return
    if git("cat-file", "-t", base, check=False).strip() != "commit":
        base = git("rev-parse", "HEAD~1").strip()
    msgs = git("log", "--format=%B", "%s..%s" % (base, head))
    allow = {t for t in ("allow-delete", "allow-revert", "allow-shrink") if "[%s]" % t in msgs}
    problems, notes = [], []
    for line in git("diff", "--name-status", "--no-renames", base, head).splitlines():
        status, path = line.split("\t", 1)
        if not is_public(path):
            continue
        if status == "D":
            (notes if "allow-delete" in allow else problems).append("deleted public file: %s" % path)
            continue
        if status != "M":
            continue
        new_blob = git("rev-parse", "%s:%s" % (head, path)).strip()
        old_blob = git("rev-parse", "%s:%s" % (base, path)).strip()
        history = set(git("log", "--format=", "--raw", "--no-abbrev", base, "--", path).split())
        history.discard(old_blob)
        if new_blob in history:
            (notes if "allow-revert" in allow else problems).append(
                "%s was put back to an OLDER version (content matches a previous commit). "
                "Edit the current live file instead of restoring an old copy." % path)
        else:
            stale = built_from_old_copy(path, base, head)
            if stale:
                (notes if "allow-revert" in allow else problems).append(
                    "%s looks like it was edited from an OLD copy (closer to commit %s than to the live version it replaced). "
                    "Start again from the current live file." % (path, stale))
        if path.endswith(".html"):
            before = main_words(git("show", "%s:%s" % (base, path)))
            after = main_words(git("show", "%s:%s" % (head, path)))
            lost = before - after
            if before and lost > SHRINK_MIN_WORDS and lost / before > SHRINK_LIMIT:
                (notes if "allow-shrink" in allow else problems).append(
                    "%s lost %d of %d words (%.0f%%)" % (path, lost, before, 100 * lost / before))
    before_n = len([l for l in git("ls-tree", "-r", "--name-only", base).splitlines() if is_public(l) and l.endswith(".html")])
    after_n = len([l for l in git("ls-tree", "-r", "--name-only", head).splitlines() if is_public(l) and l.endswith(".html")])
    if after_n < before_n and "allow-delete" not in allow:
        problems.append("page count dropped from %d to %d" % (before_n, after_n))
    for n in notes:
        print("allowed by commit message:", n)
    report("guard", problems, "%s..%s" % (base[:7], head[:7]))


# ---------------------------------------------------------------- replace
def cmd_replace(path, old, new):
    p = ROOT / path
    t = p.read_text(encoding="utf-8")
    n = t.count(old)
    if n != 1:
        sys.exit("replace: expected exactly 1 match in %s, found %d. Nothing changed." % (path, n))
    u = t.replace(old, new)
    p.write_text(u, encoding="utf-8")
    sys.stdout.writelines(difflib.unified_diff(t.splitlines(True), u.splitlines(True), "a/" + path, "b/" + path, n=0))
    print("\nsha256 before %s\nsha256 after  %s" % (hashlib.sha256(t.encode()).hexdigest(), hashlib.sha256(u.encode()).hexdigest()))


# ---------------------------------------------------------------- stage
def cmd_stage(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    for rel in public_files():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    print("staged %d public files into %s" % (len(public_files()), out))


def report(name, problems, detail):
    if problems:
        print("%s FAILED (%s):" % (name, detail))
        for p in problems:
            print("  -", p)
        print("\nFix the problem, or if Troy asked for this exact change, add the matching [allow-...] token to the commit message.")
        sys.exit(1)
    print("%s OK (%s)" % (name, detail))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
    elif a[0] == "check":
        cmd_check()
    elif a[0] == "guard":
        cmd_guard(a[a.index("--base") + 1] if "--base" in a else "")
    elif a[0] == "replace" and len(a) == 4:
        cmd_replace(*a[1:])
    elif a[0] == "stage" and len(a) == 2:
        cmd_stage(a[1])
    else:
        sys.exit(__doc__)
