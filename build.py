#!/usr/bin/env python3
"""
Skill Farm: scan every Claude Code skill on this computer, count how often each was
used from your local chat transcripts, and write skill-board.html.

Usage:
    python3 build.py              # build from your own data
    python3 build.py --open       # build and open in the browser
    python3 build.py --fetch      # also check git remotes for skill updates
    python3 build.py --demo       # build demo.html from made-up data, nothing personal
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import random
import shutil
import subprocess
import sys
import webbrowser
from collections import defaultdict
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"
CODEX_SKILLS = HOME / ".codex" / "skills"
APP_SKILLS = HOME / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions" / "skills-plugin"
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUT = HERE / "skill-board.html"
DEMO = HERE / "demo.html"
TAGS = HERE / "tags.json"
ASSETS = HERE / "assets"
PLANTS = ASSETS / "plants"
THUMBS = ASSETS / "thumbs"
GREENHOUSE = ASSETS / "greenhouse" / "greenhouse-v1.png"
GROWTH = {"mid": 1, "mature": 5}
FARM = HERE / "farm.json"
THUMB_PX = 256


def front_matter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.S)
    if not m:
        return None, text
    fm = {}
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            fm[key] = kv.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            fm[key] += " " + line.strip()
    for k, v in fm.items():
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        fm[k] = "" if v in (">", ">-", "|", "|-") else v
    return fm, text[m.end():]


def read_skill(path, source, scope, prefix=""):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm, body = front_matter(text)
    folder = path.parent.name
    problems = []
    if fm is None:
        problems.append("no_fm")
        fm = {}
    name = fm.get("name") or folder
    if not fm.get("name"):
        problems.append("no_name")
    if not fm.get("description"):
        problems.append("no_desc")
    elif len(fm["description"]) < 40:
        problems.append("short_desc")
    st = path.stat()
    return {
        "id": f"{source}:{prefix}{name}:{path}",
        "name": name,
        "invoke": f"{prefix}{name}",
        "source": source,
        "scope": scope,
        "description": fm.get("description", ""),
        "path": str(path).replace(str(HOME), "~"),
        "dir": str(path.parent),
        "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
        "lines": text.count("\n") + 1,
        "files": sum(1 for _ in path.parent.rglob("*") if _.is_file()),
        "body": text[:60000],
        "problems": problems,
    }


def project_dirs():
    """Every working directory that appears in a Claude Code transcript."""
    cwds = set()
    for f in (CLAUDE / "projects").glob("*/*.jsonl"):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    m = re.search(r'"cwd":"([^"]+)"', line)
                    if m:
                        cwds.add(m.group(1))
                        break
                    if i > 50:
                        break
        except OSError:
            pass
    roots = set()
    for c in cwds:
        p = Path(c)
        for q in [p, *p.parents]:
            if (q / ".claude" / "skills").is_dir() and q != HOME:
                roots.add(q)
                break
    return sorted(roots)


BUILTIN = {
    "artifact-design": ("发布网页 Artifact 前的设计规范", "Design rules before publishing a web Artifact"),
    "artifact-capabilities": ("给 Artifact 页面加运行时能力，比如存数据、问 Claude", "Give an Artifact page runtime abilities, like storing data or asking Claude"),
    "artifact-diagramming": ("在 Artifact 里画示意图", "Draw diagrams inside an Artifact"),
    "dataviz": ("画图表、看板时的配色和图表规范", "Color and chart rules for charts and dashboards"),
    "claude-api": ("Claude API 和 Anthropic SDK 参考", "Claude API and Anthropic SDK reference"),
    "update-config": ("改 Claude Code 的 settings.json、权限和 hooks", "Edit Claude Code settings.json, permissions and hooks"),
    "keybindings-help": ("自定义快捷键", "Customize keyboard shortcuts"),
    "code-review": ("审查代码改动找 bug", "Review code changes for bugs"),
    "simplify": ("清理和简化改过的代码", "Clean up and simplify changed code"),
    "schedule": ("定时运行的云端 agent", "Cloud agents that run on a schedule"),
    "loop": ("按间隔重复执行一个任务", "Repeat a task on an interval"),
    "run": ("启动并操作项目里的应用", "Launch and drive the project's app"),
    "init": ("生成 CLAUDE.md", "Generate a CLAUDE.md"),
    "security-review": ("安全审查当前分支改动", "Security review of the current branch"),
    "fewer-permission-prompts": ("减少权限确认弹窗", "Cut down permission prompts"),
    "workflow-authoring": ("编写多 agent 工作流脚本", "Write multi-agent workflow scripts"),
    "plugin-authoring": ("给 Claude 自己做插件和 hooks", "Build plugins and hooks for Claude itself"),
}


def builtins():
    out = []
    for name, (zh, en) in BUILTIN.items():
        out.append({"id": f"builtin:{name}", "name": name, "invoke": name, "source": "builtin",
                    "scope": {"k": "builtin"}, "description": zh, "description_en": en, "path": "",
                    "dir": "", "modified": "", "lines": 0, "files": 0, "body": "", "bundled": True, "problems": []})
    return out


def scan():
    skills = []
    user = CLAUDE / "skills"
    for d in sorted(user.iterdir()) if user.is_dir() else []:
        if d.name == "synced":
            continue
        f = d / "SKILL.md"
        if f.exists():
            s = read_skill(f, "user", {"k": "all"})
            if s:
                s["linked"] = str(d.resolve()).replace(str(HOME), "~") if d.is_symlink() else None
                skills.append(s)

    for root in project_dirs():
        for f in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
            s = read_skill(f, "project", {"k": "project", "path": str(root).replace(str(HOME), "~")})
            if s:
                skills.append(s)

    installed = {}
    try:
        installed = json.loads((CLAUDE / "plugins" / "installed_plugins.json").read_text()).get("plugins", {})
    except (OSError, json.JSONDecodeError):
        pass
    for key, entries in installed.items():
        plugin = key.split("@")[0]
        for e in entries[-1:]:
            base = Path(e.get("installPath", ""))
            for f in sorted(base.glob("skills/*/SKILL.md")):
                s = read_skill(f, "plugin", {"k": "plugin", "plugin": plugin, "v": e.get("version", "?")}, prefix=f"{plugin}:")
                if s:
                    skills.append(s)

    for f in sorted(CODEX_SKILLS.glob("[!.]*/SKILL.md")) if CODEX_SKILLS.is_dir() else []:
        s = read_skill(f, "codex", {"k": "codex"})
        if s:
            skills.append(s)

    app_dirs = sorted(APP_SKILLS.glob("*/*/skills"), key=lambda p: p.stat().st_mtime) if APP_SKILLS.is_dir() else []
    if app_dirs:
        for f in sorted(app_dirs[-1].glob("*/SKILL.md")):
            s = read_skill(f, "anthropic", {"k": "anthropic"}, prefix="anthropic-skills:")
            if s:
                skills.append(s)
    return skills + builtins()


def usage():
    counts = defaultdict(int)
    last = {}
    projects = defaultdict(set)
    names = {}
    events = []
    for f in (CLAUDE / "projects").rglob("*.jsonl"):
        proj = f.relative_to(CLAUDE / "projects").parts[0]
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if proj not in names:
                        cwd = re.search(r'"cwd":"([^"]+)"', line)
                        if cwd and re.sub(r"[^A-Za-z0-9]", "-", cwd.group(1)) == proj:
                            names[proj] = cwd.group(1).replace(str(HOME), "~") or "~"
                    if '"name":"Skill"' not in line:
                        continue
                    ts = re.search(r'"timestamp":"([^"]+)"', line)
                    for m in re.finditer(r'"name":"Skill","input":\{"skill":"([^"]+)"', line):
                        k = m.group(1)
                        counts[k] += 1
                        if ts:
                            events.append((ts.group(1), k, proj))
                        projects[k].add(proj)
                        if ts and ts.group(1) > last.get(k, ""):
                            last[k] = ts.group(1)
        except OSError:
            pass
    recent = [{"ts": t, "invoke": k, "project": names.get(p, p)} for t, k, p in sorted(events, reverse=True)[:30]]
    return counts, last, {k: {names.get(p, p) for p in v} for k, v in projects.items()}, recent


def git(d, *args, timeout=10):
    try:
        r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def updates(skills, fetch=False):
    """Mark skills whose upstream is newer. Uses only what is already on disk unless fetch=True."""
    try:
        installed = json.loads((CLAUDE / "plugins" / "installed_plugins.json").read_text()).get("plugins", {})
        known = json.loads((CLAUDE / "plugins" / "known_marketplaces.json").read_text())
    except (OSError, json.JSONDecodeError):
        installed, known = {}, {}
    plug = {}
    for key, entries in installed.items():
        name, _, mkt = key.partition("@")
        inst = entries[-1]
        loc = Path(known.get(mkt, {}).get("installLocation", ""))
        text = None
        if (loc / ".git").exists():
            if fetch:
                git(loc, "fetch", "--quiet", timeout=120)
            text = git(loc, "show", "@{u}:.claude-plugin/marketplace.json")
        try:
            listing = json.loads(text or (loc / ".claude-plugin" / "marketplace.json").read_text()).get("plugins", [])
        except (OSError, json.JSONDecodeError):
            continue
        p = next((x for x in listing if x.get("name") == name), None)
        if not p:
            continue
        fresh = ("now" if fetch else "last") if text else "date"
        date = known.get(mkt, {}).get("lastUpdated", "")[:10]
        if p.get("version") and inst.get("version") and p["version"] != inst["version"]:
            plug[name] = {"k": "plugin", "new": p["version"], "old": inst["version"], "fresh": fresh, "date": date}
    repos = {}
    for s in skills:
        if s["source"] == "plugin":
            u = plug.get(s["invoke"].split(":")[0])
            if u:
                s["update"] = u
        elif s["source"] in ("user", "project", "codex") and s["dir"]:
            root = git(Path(s["dir"]).resolve(), "rev-parse", "--show-toplevel")
            if not root:
                continue
            if root not in repos:
                if fetch:
                    git(root, "fetch", "--quiet", timeout=120)
                behind = git(root, "rev-list", "--count", "HEAD..@{u}")
                repos[root] = int(behind) if behind and behind.isdigit() else 0
            if repos[root]:
                s["update"] = {"k": "git", "n": repos[root], "root": root.replace(str(HOME), "~")}


def thumb(src, px=THUMB_PX):
    """A small PNG copy of an asset in assets/thumbs, remade only when the source changes."""
    out = THUMBS / (src.parent.name + "-" + src.stem + ".png")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        if shutil.which("sips"):
            subprocess.run(["sips", "-s", "format", "png", "-Z", str(px), str(src), "--out", str(out)], capture_output=True)
        else:
            shutil.copyfile(src, out)
    return f"assets/thumbs/{out.name}" if out.exists() else None


def plant_assets():
    """Every mature plant in assets/plants, plus the seed and sapling images it grows through."""
    names, mids = {}, {}
    try:
        for p in json.loads((ASSETS / "prompts.json").read_text(encoding="utf-8")):
            names[p["file"]] = p.get("name", "")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    try:
        for g in json.loads((ASSETS / "growth-map.json").read_text(encoding="utf-8")):
            mids[g["id"]] = g.get("intermediate", "")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    THUMBS.mkdir(parents=True, exist_ok=True)
    seed_src = ASSETS / "growth" / "s00-seeded-soil.png"
    seed = thumb(seed_src) if seed_src.exists() else None
    out = {}
    for src in sorted(PLANTS.glob("*")):
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        mature = thumb(src)
        if not mature:
            continue
        mid_src = ASSETS / mids.get(src.stem, "")
        en = src.stem.split("-", 1)[-1].replace("-", " ").title()
        out[src.name] = {"src": mature, "mid": thumb(mid_src) if mid_src.is_file() else mature, "seed": seed or mature,
                         "name": names.get(src.name) or en, "name_en": en}
    return out


def plant_skills(skills, assets, reshuffle=False, persist=True):
    """Give every skill one plant and remember it in farm.json, so adding new assets never reshuffles old ones."""
    try:
        farm = json.loads(FARM.read_text(encoding="utf-8")) if persist else {}
    except (OSError, json.JSONDecodeError):
        farm = {}
    chosen = {} if reshuffle else {k: v for k, v in farm.get("plants", {}).items() if v in assets}
    count = defaultdict(int)
    for v in chosen.values():
        count[v] += 1
    for s in sorted(skills, key=lambda s: (-s["uses"], s["invoke"])):
        if s["invoke"] not in chosen and assets:
            h = lambda a: hashlib.md5((s["invoke"] + a).encode()).hexdigest()
            pick = min(assets, key=lambda a: (count[a], h(a)))
            chosen[s["invoke"]] = pick
            count[pick] += 1
        a = assets.get(chosen.get(s["invoke"]))
        s["plant"] = a
    farm["_说明"] = "每个 skill 种的是哪盆植物。可以手动改成 assets/plants 里的任意文件名；删掉一行就会重新分配。growth 是长到幼株和成熟各需要用几次。"
    farm["growth"] = {**GROWTH, **farm.get("growth", {})}
    farm["plants"] = dict(sorted(chosen.items()))
    if persist:
        FARM.write_text(json.dumps(farm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return farm["growth"]


def words(s):
    return set(w for w in re.findall(r"[a-z]{4,}", s.lower())) - {
        "when", "with", "this", "that", "user", "skill", "skills", "from", "into", "only", "also", "uses",
        "used", "your", "they", "their", "file", "files", "claude", "should", "before", "after", "about"}


def warnings(skills):
    out = []
    by_name = defaultdict(list)
    for s in skills:
        by_name[s["name"]].append(s)
    for name, group in by_name.items():
        srcs = {g["source"] for g in group}
        if len(group) > 1 and len(srcs) > 1:
            out.append({"code": "dup", "skills": [g["id"] for g in group], "name": name, "n": len(group)})
    seen = set()
    for i, a in enumerate(skills):
        for b in skills[i + 1:]:
            if a["name"] == b["name"]:
                continue
            wa, wb = words(a["description"]), words(b["description"])
            if len(wa) < 6 or len(wb) < 6:
                continue
            j = len(wa & wb) / len(wa | wb)
            if j >= 0.33 and (a["id"], b["id"]) not in seen:
                seen.add((a["id"], b["id"]))
                out.append({"code": "similar", "skills": [a["id"], b["id"]], "a": a["invoke"], "b": b["invoke"], "pct": round(j * 100)})
    for s in skills:
        for p in s["problems"]:
            out.append({"code": "format", "skills": [s["id"]], "skill": s["invoke"], "problem": p})
    return out


DEMO_SKILLS = [
    ("user", "meeting-notes", "Turn a meeting transcript into short notes with decisions, owners and next steps. Use when the user pastes a transcript or asks for minutes.", 23, ["Notes"]),
    ("user", "code-tutor", "Explain a piece of code step by step for a beginner, with a small example for every new idea. Use when the user asks what some code does.", 12, ["Learning"]),
    ("user", "tiny", "Make text shorter.", 0, []),
    ("project", "release-checklist", "Walk through the release checklist for this repo: changelog, version bump, tag, and smoke test. Use before cutting a release.", 7, ["Shipping"]),
    ("project", "api-docs", "Write or update reference docs for the public API from the source code and docstrings. Use when endpoints change.", 3, ["Docs"]),
    ("plugin", "figma:design-to-code", "Implement a Figma design as production code. Use when the user shares a Figma link and wants it built as a page or component.", 9, ["Design"]),
    ("plugin", "figma:make-diagram", "Create a diagram in Figma from a description. Use when the user wants a flowchart or architecture diagram drawn in Figma.", 0, ["Design"]),
    ("plugin", "figma:make-flowchart", "Create a flowchart in Figma from a description. Use when the user wants a flowchart or architecture diagram drawn in Figma.", 0, ["Design"]),
    ("plugin", "lint-kit:auto-fix", "Run the project's linters and fix what can be fixed automatically, then summarize what is left. Use after large edits.", 5, []),
    ("anthropic", "anthropic-skills:pdf", "Read, fill, merge, split or create PDF files. Use whenever the user mentions a PDF or asks to produce one.", 17, ["Docs"]),
    ("anthropic", "anthropic-skills:docx", "Create, read and edit Word documents. Use whenever the user asks for a .docx file.", 11, ["Docs"]),
    ("anthropic", "anthropic-skills:xlsx", "Create, read and edit spreadsheets. Use whenever a spreadsheet is the main input or output.", 4, []),
    ("anthropic", "anthropic-skills:pptx", "Create, read and edit slide decks. Use whenever a .pptx file is involved.", 2, []),
    ("anthropic", "anthropic-skills:skill-creator", "Create new skills, improve existing ones and measure how well they trigger.", 1, []),
    ("anthropic", "anthropic-skills:deep-research", "Research a topic across many sources and write a cited report.", 0, []),
    ("builtin", "code-review", "", 6, []),
    ("builtin", "simplify", "", 2, []),
    ("builtin", "claude-api", "", 1, []),
    ("builtin", "init", "", 0, []),
    ("builtin", "security-review", "", 0, []),
    ("builtin", "loop", "", 0, []),
    ("codex", "repo-summary", "Summarize an unfamiliar repository: layout, entry points, how to run it and where the tests are.", 0, []),
]
DEMO_PROJECTS = ["~/projects/blog", "~/projects/shop-app", "~/notes", "~/projects/cli-tool"]


def demo_data():
    """Made-up skills and usage, so screenshots and first runs show nothing personal."""
    rnd = random.Random(7)
    now = datetime.datetime.now(datetime.timezone.utc)
    builtin = {b["name"]: b for b in builtins()}
    skills, recent = [], []
    for src, invoke, desc, uses, tags in DEMO_SKILLS:
        name = invoke.split(":")[-1]
        if src == "builtin":
            s = dict(builtin[name])
        else:
            scope = {"user": {"k": "all"}, "project": {"k": "project", "path": DEMO_PROJECTS[1]},
                     "plugin": {"k": "plugin", "plugin": invoke.split(":")[0], "v": "1.2.0"},
                     "anthropic": {"k": "anthropic"}, "codex": {"k": "codex"}}[src]
            body = f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\nDemo skill used for screenshots.\n"
            s = {"id": f"{src}:{invoke}", "name": name, "invoke": invoke, "source": src, "scope": scope,
                 "description": desc, "path": f"~/demo/{name}/SKILL.md", "dir": "", "linked": None,
                 "modified": (now - datetime.timedelta(days=rnd.randint(2, 90))).strftime("%Y-%m-%dT%H:%M"),
                 "lines": rnd.randint(30, 200), "files": rnd.randint(1, 6), "body": body,
                 "problems": ["short_desc"] if len(desc) < 40 else []}
        last = now - datetime.timedelta(days=rnd.choice([0, 0, 1, 3, 6, 12, 30, 70])) if uses else None
        s.update({"uses": uses, "last_used": last.strftime("%Y-%m-%dT%H:%M:%S.000Z") if last else None,
                  "used_in": sorted(rnd.sample(DEMO_PROJECTS, min(uses, rnd.randint(1, 3)))) if uses else [], "tags": tags})
        skills.append(s)
        for _ in range(min(uses, 3)):
            t = now - datetime.timedelta(hours=rnd.randint(1, 24 * 9))
            recent.append({"ts": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "invoke": invoke, "project": rnd.choice(DEMO_PROJECTS)})
    for s in skills:
        if s["invoke"] == "lint-kit:auto-fix":
            s["update"] = {"k": "plugin", "new": "1.4.0", "old": "1.2.0", "fresh": "last", "date": ""}
    recent.sort(key=lambda e: e["ts"], reverse=True)
    ghosts = [{"invoke": "old-helper", "uses": 4, "last_used": (now - datetime.timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}]
    return skills, ghosts, recent[:30], sum(s["uses"] for s in skills)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="Open the page when done")
    ap.add_argument("--reshuffle", action="store_true", help="Reassign every skill's plant evenly across all assets")
    ap.add_argument("--fetch", action="store_true", help="Fetch git remotes first so update checks are current")
    ap.add_argument("--demo", action="store_true", help="Build demo.html from made-up data instead of your own")
    a = ap.parse_args()
    if a.demo:
        skills, ghosts, recent, total = demo_data()
        growth = plant_skills(skills, plant_assets(), persist=False)
        return write(DEMO, skills, ghosts, recent, total, growth, {}, a.open)
    skills = scan()
    counts, last, projects, recent = usage()
    known = set()
    for s in skills:
        keys = {s["invoke"], s["name"]}
        s["uses"] = sum(counts.get(k, 0) for k in keys)
        s["last_used"] = max((last.get(k, "") for k in keys), default="") or None
        s["used_in"] = sorted({p for k in keys for p in projects.get(k, set())})
        known |= keys
    try:
        tags = json.loads(TAGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        tags = {}
        if TAGS.exists():
            print(f"tags.json 读不了，先跳过标签：{e}", file=sys.stderr)
    for s in skills:
        s["tags"] = list(dict.fromkeys(tags.get(s["invoke"], []) + tags.get(s["name"], [])))
    tag_en = tags.get("_英文", {}) if isinstance(tags.get("_英文"), dict) else {}
    updates(skills, a.fetch)
    growth = plant_skills(skills, plant_assets(), a.reshuffle)
    ghosts = [{"invoke": k, "uses": v, "last_used": last.get(k)} for k, v in counts.items()
              if k not in known and k.split(":")[-1] not in known]
    write(OUT, skills, ghosts, recent, sum(counts.values()), growth, tag_en, a.open)


def write(out, skills, ghosts, recent, total, growth, tag_en, open_it=False):
    data = {
        "generated": datetime.datetime.now().isoformat(timespec="minutes"),
        "skills": skills,
        "warnings": warnings(skills),
        "ghosts": sorted(ghosts, key=lambda g: -g["uses"]),
        "total_calls": total,
        "recent": recent,
        "tag_en": tag_en,
        "growth": growth,
        "greenhouse": thumb(GREENHOUSE, 480) if GREENHOUSE.exists() else None,
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out.write_text(page, encoding="utf-8")
    print(f"{len(skills)} skills, {total} calls, {len(data['warnings'])} warnings -> {out}")
    if open_it:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
