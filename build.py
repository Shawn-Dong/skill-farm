#!/usr/bin/env python3
"""
Skill Farm: scan every Claude Code skill on this computer, count how often each was
used from your local chat transcripts, and write skill-board.html.

Usage:
    python3 build.py              # build from your own data
    python3 build.py --open       # build and open in the browser
    python3 build.py --fetch      # also check git remotes for skill updates
    python3 build.py --demo       # build demo.html from made-up data, nothing personal
    python3 build.py --data-dir ~/somewhere   # keep the page, farm.json and tags.json there
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
ASSETS = HERE / "assets"
PLANTS = ASSETS / "plants"
REPO_THUMBS = ASSETS / "thumbs"
GREENHOUSE = ASSETS / "greenhouse" / "greenhouse-v1.png"
GROWTH = {"mid": 1, "mature": 5, "wilt": 30}
THUMB_PX = 256
QUIET = False
PLUGIN_HOME = CLAUDE / "skill-farm"

# Your own files live in the data dir. From a git clone that is the repo folder, as before.
# As a Claude Code plugin the code sits in a cache folder that is replaced on update,
# so the data goes to ~/.claude/skill-farm instead. SKILL_FARM_HOME or --data-dir override both.
DATA = HERE
OUT = DATA / "skill-board.html"
DEMO = DATA / "demo.html"
TAGS = DATA / "tags.json"
FARM = DATA / "farm.json"
NAMES = DATA / "names.json"
BLURBS = DATA / "blurbs.json"
THUMBS = DATA / "assets" / "thumbs"


def data_dir(flag=None, plugin=False):
    if flag:
        return Path(flag).expanduser().resolve()
    if os.environ.get("SKILL_FARM_HOME"):
        return Path(os.environ["SKILL_FARM_HOME"]).expanduser().resolve()
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin or (root and Path(root).resolve() == HERE) or (CLAUDE / "plugins") in HERE.parents:
        return PLUGIN_HOME
    return HERE


def use_data_dir(d):
    global DATA, OUT, DEMO, TAGS, FARM, THUMBS, NAMES, BLURBS
    DATA = d
    OUT, DEMO, TAGS, FARM, NAMES = d / "skill-board.html", d / "demo.html", d / "tags.json", d / "farm.json", d / "names.json"
    BLURBS = d / "blurbs.json"
    THUMBS = d / "assets" / "thumbs"
    THUMBS.mkdir(parents=True, exist_ok=True)


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
                s = read_skill(f, "plugin", {"k": "plugin", "plugin": plugin, "v": e.get("version", "?"), "mkt": key.partition("@")[2]}, prefix=f"{plugin}:")
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


CORRECTION = re.compile(
    r"不对|不是这个|不是这样|不是让你|别用|不要用|不用这个|用错|错了|搞错|停下|停一下|先停|"
    r"\bwrong\b|\bnot that\b|\bnot this one\b|\bstop\b|\bdon'?t use\b|\bdo not use\b|\bthat'?s not\b", re.I)


def typed_prompt(d):
    """The text the user actually typed in this transcript entry, or None for tool results, meta and commands."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            return None
        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    if not isinstance(c, str):
        return None
    c = c.strip()
    if not c or c.startswith(("<", "[Request interrupted", "[Image", "Caveat:")):
        return None
    return c


def usage():
    """One pass over every transcript: Skill calls, the injected skill listings and the user's own prompts."""
    counts = defaultdict(int)
    last = {}
    projects = defaultdict(set)
    names = {}
    events = []
    raw = {"sess_calls": defaultdict(set), "sess_listed": defaultdict(set), "sess_proj": {},
           "prompts": defaultdict(list), "listings": [], "mis": []}
    base = CLAUDE / "projects"
    for f in base.rglob("*.jsonl"):
        parts = f.relative_to(base).parts
        proj = parts[0]
        main = len(parts) == 2
        sid = f.stem if main else parts[1]
        pending = []
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if proj not in names:
                        cwd = re.search(r'"cwd":"([^"]+)"', line)
                        if cwd and re.sub(r"[^A-Za-z0-9]", "-", cwd.group(1)) == proj:
                            names[proj] = cwd.group(1).replace(str(HOME), "~") or "~"
                    if '"name":"Skill"' in line:
                        ts = re.search(r'"timestamp":"([^"]+)"', line)
                        for m in re.finditer(r'"name":"Skill","input":\{"skill":"([^"]+)"', line):
                            k = m.group(1)
                            counts[k] += 1
                            if ts:
                                events.append((ts.group(1), k, proj))
                            projects[k].add(proj)
                            raw["sess_calls"][sid].add(k)
                            if main:
                                pending.append(k)
                            if ts and ts.group(1) > last.get(k, ""):
                                last[k] = ts.group(1)
                        continue
                    if '"skill_listing"' in line:
                        try:
                            d = json.loads(line)
                            a = d.get("attachment") or {}
                            if a.get("type") == "skill_listing":
                                raw["sess_listed"][sid].update(a.get("names") or [])
                                raw["listings"].append((d.get("timestamp", ""), bool(a.get("isInitial")),
                                                        a.get("names") or [], a.get("content") or ""))
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        continue
                    if not main or '"type":"user"' not in line or '"tool_use_id"' in line or '"isMeta":true' in line:
                        continue
                    if "<command-name>" in line:
                        for m in re.finditer(r"<command-name>/?([^<\s]+)</command-name>", line):
                            raw["sess_calls"][sid].add(m.group(1))
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    p = typed_prompt(d)
                    if not p:
                        continue
                    ts = d.get("timestamp", "")
                    raw["sess_proj"][sid] = proj
                    raw["prompts"][sid].append((ts, p[:1500]))
                    if pending and CORRECTION.search(p[:160]):
                        for k in dict.fromkeys(pending):
                            raw["mis"].append((k, ts, proj, p))
                    pending = []
        except OSError:
            pass
    raw["events"] = events
    raw["names"] = names
    recent = [{"ts": t, "invoke": k, "project": names.get(p, p)} for t, k, p in sorted(events, reverse=True)[:30]]
    return counts, last, {k: {names.get(p, p) for p in v} for k, v in projects.items()}, recent, raw


# Diagnosis (phase 2). Everything below works on the raw data that usage() collected in its single pass.
CONTEXT = {}
CJK = re.compile(r"[⺀-鿿가-힯豈-﫿＀-￯]")


def est_tokens(text):
    """Rough token estimate: one token per CJK character, plus one per four other characters."""
    cjk = len(CJK.findall(text))
    return round((len(text) - cjk) / 4 + cjk)


def split_listing(content, names):
    """Cut a skill_listing body ("- name: description" lines) into the exact text injected for each skill."""
    starts = []
    for n in names:
        if content.startswith(f"- {n}:"):
            starts.append((0, n))
        else:
            i = content.find(f"\n- {n}:")
            if i >= 0:
                starts.append((i + 1, n))
    starts.sort()
    out = {}
    for j, (i, n) in enumerate(starts):
        end = starts[j + 1][0] if j + 1 < len(starts) else len(content)
        out[n] = content[i:end].rstrip("\n")
    return out


def snippet(text, at, width=80):
    """About `width` characters of text around position `at`, with … where it was cut."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    lo = max(0, min(at - width // 3, len(text) - width))
    return ("…" if lo else "") + text[lo:lo + width].strip() + ("…" if lo + width < len(text) else "")


QUOTED = re.compile(r'"([^"\n]{2,60})"|“([^”\n]{2,60})”|「([^」\n]{2,60})」|‘([^’\n]{2,60})’')
TRIGGER_STOP = {"which", "where", "there", "these", "those", "would", "could", "every", "other", "using", "first",
                "write", "create", "files", "notes", "short", "answer", "check", "local", "under", "until", "always",
                "should", "before", "after", "about", "their", "users", "skill", "skills", "claude", "asked", "asks"}


def trigger_rules(skills):
    """For each skill the user owns: quoted trigger phrases in its description, short Chinese phrases in its
    "Use when ..." list, and description words that no other skill's description uses."""
    df = defaultdict(int)
    vocab = {}
    for s in skills:
        w = set(re.findall(r"[a-z][a-z0-9-]{4,}", (s["description"] or "").lower())) - TRIGGER_STOP
        vocab[s["id"]] = w
        for x in w:
            df[x] += 1
    rules = {}
    for s in skills:
        if s["source"] not in ("user", "project", "codex"):
            continue
        phrases = []
        for m in QUOTED.finditer(s["description"] or ""):
            q = next(g for g in m.groups() if g).strip().lower()
            parts = [p.strip() for p in re.split(r"…|\.\.\.|<[^>]*>|&lt;[^&]*&gt;", q) if p.strip()]
            parts = [p for p in parts if len(CJK.findall(p)) >= 2 or len(p) >= 5]
            if parts:
                phrases.append(parts)
        when = re.search(r"use (?:it |this )?(?:when|whenever)|trigger|当用户|用户说", s["description"] or "", re.I)
        for seg in re.split(r"[,，、;；]", (s["description"] or "")[when.start():] if when else ""):
            seg = seg.strip(" .。\"'“”")
            if 3 <= len(CJK.findall(seg)) and len(seg) <= 12 and not re.search(r"[A-Za-z]", seg):
                phrases.append([seg])
        rules[s["id"]] = (phrases, {x for x in vocab[s["id"]] if df[x] == 1})
    return rules


def match_prompt(prompt, rule):
    """Position where the prompt strongly matches the skill, or -1. A trigger phrase (all of its parts) counts;
    otherwise a prompt of at most 600 characters needs three or more words unique to this skill."""
    low = prompt.lower()
    for parts in rule[0]:
        pos = [low.find(p) for p in parts]
        if all(i >= 0 for i in pos):
            return pos[0]
    if len(prompt) <= 600 and len(rule[1]) >= 3:
        found = [m.start() for k in rule[1] for m in [re.search(r"\b" + re.escape(k) + r"\b", low)] if m]
        if len(found) >= 3:
            return min(found)
    return -1


def diagnose(skills, raw, now=None):
    """Attach context cost, missed and wrong triggers, co-use and an 8-week trend to each skill dict."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    pname = lambda p: raw["names"].get(p, p)
    keymap = {}
    for s in skills:
        keymap.setdefault(s["invoke"], s)
    for s in skills:
        keymap.setdefault(s["name"], s)

    listings = sorted(raw["listings"], key=lambda x: x[0])
    latest = next((x for x in reversed(listings) if x[1]), None)
    text = {}
    for _, _, nm, content in listings:
        text.update(split_listing(content, nm))
    cur = split_listing(latest[3], latest[2]) if latest else {}
    for s in skills:
        t = cur.get(s["invoke"]) or text.get(s["invoke"])
        if t is None:
            s["ctx"] = None
            continue
        body = t.split(":", 1)[1].strip() if ":" in t else ""
        trunc = body.endswith(("…", "...")) and len(s["description"]) > len(body)
        s["ctx"] = {"tok": est_tokens(t + "\n"), "chars": len(t), "trunc": trunc, "cur": s["invoke"] in cur}
    CONTEXT.clear()
    if latest:
        CONTEXT.update({"tok": sum(est_tokens(t + "\n") for t in cur.values()), "n": len(cur), "ts": latest[0],
                        "trunc": sum(1 for s in skills if s.get("ctx") and s["ctx"]["trunc"])})

    week = datetime.timedelta(days=7)
    for s in skills:
        s["weeks"] = [0] * 8
    for ts, k, _ in raw["events"]:
        s = keymap.get(k)
        try:
            age = now - datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if s and 0 <= age / week < 8:
            s["weeks"][7 - int(age / week)] += 1

    pairs = defaultdict(int)
    for calls in raw["sess_calls"].values():
        got = sorted({keymap[k]["invoke"] for k in calls if k in keymap})
        for i, a in enumerate(got):
            for b in got[i + 1:]:
                pairs[(a, b)] += 1
    co = defaultdict(list)
    for (a, b), n in pairs.items():
        co[a].append([b, n])
        co[b].append([a, n])
    for s in skills:
        s["co"] = sorted(co.get(s["invoke"], []), key=lambda x: (-x[1], x[0]))[:4]

    mis = defaultdict(list)
    for k, ts, p, q in sorted(raw["mis"], key=lambda x: x[1], reverse=True):
        if k in keymap:
            mis[keymap[k]["id"]].append({"q": snippet(q, CORRECTION.search(q[:160]).start()), "ts": ts, "project": pname(p)})
    for s in skills:
        m = mis.get(s["id"])
        s["mis"] = {"n": len(m), "ex": m[:3]} if m else None

    rules = trigger_rules(skills)
    for s in skills:
        s["missed"] = None
        rule = rules.get(s["id"])
        if not rule or not (rule[0] or rule[1]):
            continue
        keys = {s["invoke"], s["name"]}
        hits = []
        for sid, prompts in raw["prompts"].items():
            if not keys & raw["sess_listed"].get(sid, set()) or keys & raw["sess_calls"].get(sid, set()):
                continue
            for ts, p in prompts:
                at = match_prompt(p, rule)
                if at >= 0:
                    hits.append({"q": snippet(p, at), "ts": ts, "project": pname(raw["sess_proj"].get(sid, ""))})
                    break
        if hits:
            hits.sort(key=lambda h: h["ts"], reverse=True)
            s["missed"] = {"n": len(hits), "ex": hits[:3]}


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
        shipped = REPO_THUMBS / out.name
        if THUMBS != REPO_THUMBS and shipped.exists():
            shutil.copyfile(shipped, out)
        elif shutil.which("sips"):
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
    farm["_说明"] = "每个 skill 种的是哪盆植物。可以手动改成 assets/plants 里的任意文件名；删掉一行就会重新分配。growth 里 mid 和 mature 是长到幼株和成熟各需要用几次，wilt 是用过的 skill 隔多少天没用就开始枯萎。"
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


DEMO_CO = [("meeting-notes", "anthropic-skills:docx", 6), ("meeting-notes", "anthropic-skills:pdf", 3),
           ("code-tutor", "code-review", 4), ("release-checklist", "code-review", 3), ("release-checklist", "lint-kit:auto-fix", 2),
           ("figma:design-to-code", "lint-kit:auto-fix", 2), ("anthropic-skills:pdf", "anthropic-skills:docx", 5),
           ("anthropic-skills:xlsx", "anthropic-skills:pdf", 2), ("api-docs", "code-review", 1), ("simplify", "code-review", 2)]
DEMO_MISSED = {
    "meeting-notes": (3, [("can you pull out the action items from this call transcript", 4, DEMO_PROJECTS[2]),
                          ("帮我把今天站会的录音整理成纪要，谁负责什么写清楚", 11, DEMO_PROJECTS[2]),
                          ("summarize the decisions from the planning meeting notes below", 26, DEMO_PROJECTS[0])]),
    "code-tutor": (1, [("what does this regex do, explain it like I'm new to Python", 9, DEMO_PROJECTS[3])]),
}
DEMO_MIS = {
    "anthropic-skills:docx": (2, [("不对，我要的是 PDF，不是 Word 文件", 5, DEMO_PROJECTS[2]),
                                  ("wrong format, I wanted a markdown file", 18, DEMO_PROJECTS[0])]),
    "figma:design-to-code": (1, [("not that, I only wanted a quick sketch of the layout", 13, DEMO_PROJECTS[1])]),
}


def demo_diagnosis(skills, rnd, now):
    """Made-up context cost, trend, co-use and trigger examples for demo.html. Never real prompts."""
    iso = lambda days: (now - datetime.timedelta(days=days, hours=rnd.randint(1, 20))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    co = defaultdict(list)
    for a, b, n in DEMO_CO:
        co[a].append([b, n])
        co[b].append([a, n])
    for s in skills:
        text = f"- {s['invoke']}: {s.get('description_en') or s['description']}"
        s["ctx"] = {"tok": est_tokens(text) + (rnd.randint(40, 160) if s["source"] == "builtin" else 0), "chars": len(text),
                    "trunc": s["invoke"] == "api-docs", "cur": s["source"] != "codex"}
        s["weeks"] = [0] * 8
        if s["last_used"]:
            age = (now - datetime.datetime.fromisoformat(s["last_used"].replace("Z", "+00:00"))).days // 7
            for _ in range(s["uses"] * 2 // 3):
                i = rnd.randint(age, age + 6)
                if i < 8:
                    s["weeks"][7 - i] += 1
            if age < 8:
                s["weeks"][7 - age] = max(1, s["weeks"][7 - age])
        s["co"] = sorted(co.get(s["invoke"], []), key=lambda x: -x[1])[:4]
        s["missed"] = s["mis"] = None
        for key, table in (("missed", DEMO_MISSED), ("mis", DEMO_MIS)):
            if s["invoke"] in table:
                n, ex = table[s["invoke"]]
                s[key] = {"n": n, "ex": [{"q": q, "ts": iso(d), "project": p} for q, d, p in ex]}
    cur = [s for s in skills if s["ctx"]["cur"]]
    CONTEXT.clear()
    CONTEXT.update({"tok": sum(s["ctx"]["tok"] for s in cur), "n": len(cur), "ts": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "trunc": sum(1 for s in cur if s["ctx"]["trunc"])})


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
    demo_diagnosis(skills, rnd, now)
    ghosts = [{"invoke": "old-helper", "uses": 4, "last_used": (now - datetime.timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}]
    return skills, ghosts, recent[:30], sum(s["uses"] for s in skills)


NAME_ZH = {
    "anthropic-skills:built-in-browser": "内置浏览器操作", "anthropic-skills:chrome-browser": "Chrome 浏览器操作",
    "anthropic-skills:computer-use": "操作电脑桌面", "anthropic-skills:consolidate-memory": "整理记忆",
    "anthropic-skills:deep-research": "深度调研", "anthropic-skills:docs": "在线文档", "anthropic-skills:docx": "Word 文档",
    "anthropic-skills:explain-usage": "用量解读", "anthropic-skills:google-workspace": "Google 文档表格",
    "anthropic-skills:import-memory": "导入记忆", "anthropic-skills:morning": "晨间简报", "anthropic-skills:pdf": "PDF 处理",
    "anthropic-skills:pptx": "PPT 演示文稿", "anthropic-skills:setup-claude": "Claude 上手设置",
    "anthropic-skills:setup-cowork": "协作空间设置", "anthropic-skills:skill-creator": "Skill 制作",
    "anthropic-skills:xlsx": "Excel 表格",
    "artifact-design": "网页设计规范", "artifact-capabilities": "网页运行能力", "artifact-diagramming": "网页示意图",
    "dataviz": "数据图表", "claude-api": "Claude API 参考", "update-config": "修改配置", "keybindings-help": "快捷键设置",
    "code-review": "代码审查", "simplify": "代码精简", "schedule": "定时任务", "loop": "循环执行", "run": "运行应用",
    "init": "生成 CLAUDE.md", "security-review": "安全审查", "fewer-permission-prompts": "减少权限弹窗",
    "workflow-authoring": "多 agent 工作流", "plugin-authoring": "插件制作",
    "figma:figma-code-connect": "Figma 代码映射", "figma:figma-create-new-file": "新建 Figma 文件",
    "figma:figma-design-to-code": "Figma 转代码", "figma:figma-generate-design": "生成 Figma 设计",
    "figma:figma-generate-diagram": "Figma 示意图", "figma:figma-generate-library": "Figma 组件库",
    "figma:figma-implement-motion": "Figma 动效实现", "figma:figma-swiftui": "Figma 与 SwiftUI",
    "figma:figma-use": "Figma 基础操作", "figma:figma-use-figjam": "FigJam 白板", "figma:figma-use-motion": "Figma 动效",
    "figma:figma-use-slides": "Figma 幻灯片", "impeccable:impeccable": "界面打磨",
    "meeting-notes": "会议纪要", "code-tutor": "代码讲解", "tiny": "精简文字", "release-checklist": "发布检查",
    "api-docs": "API 文档", "figma:design-to-code": "Figma 转代码", "figma:make-diagram": "Figma 画图",
    "figma:make-flowchart": "Figma 流程图", "lint-kit:auto-fix": "自动修复", "repo-summary": "仓库速览",
}


BLURB = {
    "anthropic-skills:built-in-browser": ("用应用内置的浏览器读网页、点按钮", "Browse with the app's built-in browser"),
    "anthropic-skills:chrome-browser": ("在你自己的 Chrome 里操作网页", "Drive pages in your own Chrome"),
    "anthropic-skills:computer-use": ("截屏并操作电脑上的应用", "See and control apps on your computer"),
    "anthropic-skills:consolidate-memory": ("合并重复记忆，清理过期内容", "Tidy up and merge saved memories"),
    "anthropic-skills:deep-research": ("多来源调研并写成报告", "Research many sources into one report"),
    "anthropic-skills:docs": ("写可以分享和评论的在线文档", "Write docs people can share and comment on"),
    "anthropic-skills:docx": ("创建和编辑 Word 文档", "Create and edit Word documents"),
    "anthropic-skills:explain-usage": ("用图解释 token 都用在了哪", "Explain where your tokens went"),
    "anthropic-skills:google-workspace": ("修改 Google 文档、表格和幻灯片", "Edit Google Docs, Sheets and Slides"),
    "anthropic-skills:import-memory": ("从别的 AI 助手导入记忆", "Import memory from another assistant"),
    "anthropic-skills:morning": ("生成每天的晨间简报", "Your daily morning brief"),
    "anthropic-skills:pdf": ("读取、合并、填写和生成 PDF", "Read, merge, fill and create PDFs"),
    "anthropic-skills:pptx": ("创建和编辑 PPT", "Create and edit slide decks"),
    "anthropic-skills:setup-claude": ("按角色安装插件、连接工具", "Guided setup for plugins and tools"),
    "anthropic-skills:setup-cowork": ("设置协作空间", "Set up a shared workspace"),
    "anthropic-skills:skill-creator": ("编写、改进和测试 skill", "Write, improve and test skills"),
    "anthropic-skills:xlsx": ("创建和编辑 Excel 表格", "Create and edit spreadsheets"),
    "figma:figma-code-connect": ("把 Figma 组件对应到代码", "Map Figma components to code"),
    "figma:figma-create-new-file": ("新建空白 Figma 文件", "Create a blank Figma file"),
    "figma:figma-design-to-code": ("把 Figma 设计做成代码", "Turn a Figma design into code"),
    "figma:figma-generate-design": ("把页面画进 Figma", "Build a screen in Figma"),
    "figma:figma-generate-diagram": ("在 FigJam 里画图表", "Draw diagrams in FigJam"),
    "figma:figma-generate-library": ("在 Figma 里搭设计系统", "Build a design system in Figma"),
    "figma:figma-implement-motion": ("把 Figma 动效写成代码", "Turn Figma motion into code"),
    "figma:figma-swiftui": ("Figma 和 SwiftUI 互相转换", "Move between Figma and SwiftUI"),
    "figma:figma-use": ("用代码修改 Figma 文件", "Script changes in a Figma file"),
    "figma:figma-use-figjam": ("在 FigJam 白板里操作", "Work in FigJam boards"),
    "figma:figma-use-motion": ("给 Figma 里的元素加动画", "Animate nodes in Figma"),
    "figma:figma-use-slides": ("在 Figma 幻灯片里操作", "Work in Figma Slides"),
    "impeccable:impeccable": ("设计、审查和打磨界面", "Design, critique and polish interfaces"),
    "meeting-notes": ("把会议记录整理成纪要", "Turn a meeting transcript into notes"),
    "code-tutor": ("一步步讲解一段代码", "Explain code step by step"),
    "tiny": ("把文字改短", "Make text shorter"),
    "release-checklist": ("发版前逐项检查", "Walk the release checklist"),
    "api-docs": ("根据代码写 API 文档", "Write API docs from the code"),
    "figma:design-to-code": ("把 Figma 设计做成代码", "Turn a Figma design into code"),
    "figma:make-diagram": ("在 Figma 里画示意图", "Draw a diagram in Figma"),
    "figma:make-flowchart": ("在 Figma 里画流程图", "Draw a flowchart in Figma"),
    "lint-kit:auto-fix": ("跑 lint 并自动修复", "Run linters and fix what they can"),
    "repo-summary": ("快速看懂一个陌生仓库", "Get the gist of an unfamiliar repo"),
}


def blurbs(skills, personal=True):
    """One-line intros for cards: blurbs.json in the data folder wins, then the built-in list, then built-in skill notes."""
    own = {}
    if personal:
        try:
            own = json.loads(BLURBS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    for s in skills:
        o = own.get(s["invoke"]) or own.get(s["name"]) or {}
        zh, en = BLURB.get(s["invoke"], (None, None))
        if s.get("bundled"):
            zh, en = zh or s["description"], en or s.get("description_en")
        s["blurb_zh"], s["blurb_en"] = o.get("zh") or zh, o.get("en") or en
    return [s for s in skills if not (s["blurb_zh"] and s["blurb_en"])]


def untagged(skills):
    """Skills with no tag yet, plus the tags already in use, so new tags can reuse the same words."""
    try:
        tags = json.loads(TAGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        tags = {}
    vocab = defaultdict(int)
    for k, v in tags.items():
        if not k.startswith("_") and isinstance(v, list):
            for x in v:
                vocab[x] += 1
    tagged = {k for k, v in tags.items() if not k.startswith("_") and v}
    return {"tags_file": str(TAGS), "tag_vocab": dict(sorted(vocab.items(), key=lambda kv: -kv[1])),
            "tag_en": tags.get("_英文", {}),
            "untagged": [{"invoke": s["invoke"], "description": (s.get("description_en") or s["description"])[:200]}
                         for s in skills if s["invoke"] not in tagged and s["name"] not in tagged]}


def zh_names(skills, personal=True):
    """Chinese display names: names.json in the data folder wins over the built-in list."""
    own = {}
    if personal:
        try:
            own = json.loads(NAMES.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    for s in skills:
        s["name_zh"] = own.get(s["invoke"]) or own.get(s["name"]) or NAME_ZH.get(s["invoke"]) or None
    return [s for s in skills if not s["name_zh"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="Open the page when done")
    ap.add_argument("--reshuffle", action="store_true", help="Reassign every skill's plant evenly across all assets")
    ap.add_argument("--fetch", action="store_true", help="Fetch git remotes first so update checks are current")
    ap.add_argument("--demo", action="store_true", help="Build demo.html from made-up data instead of your own")
    ap.add_argument("--data-dir", help="Folder for skill-board.html, farm.json, tags.json and thumbnails")
    ap.add_argument("--plugin", action="store_true", help="Use the plugin data folder ~/.claude/skill-farm")
    ap.add_argument("--quiet", action="store_true", help="Print nothing unless something fails")
    ap.add_argument("--unnamed", action="store_true", help="List skills that still lack a Chinese display name, as JSON, and exit")
    a = ap.parse_args()
    global QUIET
    QUIET = a.quiet
    use_data_dir(data_dir(a.data_dir, a.plugin))
    if a.demo:
        skills, ghosts, recent, total = demo_data()
        growth = plant_skills(skills, plant_assets(), persist=False)
        zh_names(skills, personal=False)
        blurbs(skills, personal=False)
        return write(DEMO, skills, ghosts, recent, total, growth, {}, a.open)
    skills = scan()
    if a.unnamed:
        print(json.dumps({"names_file": str(NAMES), "unnamed": [{"invoke": s["invoke"], "description": s["description"][:160]}
                                                              for s in zh_names(skills)],
                          "blurbs_file": str(BLURBS), "no_blurb": [{"invoke": s["invoke"], "description": s["description"][:300]}
                                                                 for s in blurbs(skills)],
                          **untagged(skills)}, ensure_ascii=False, indent=1))
        return
    zh_names(skills)
    blurbs(skills)
    counts, last, projects, recent, raw = usage()
    known = set()
    for s in skills:
        keys = {s["invoke"], s["name"]}
        s["uses"] = sum(counts.get(k, 0) for k in keys)
        s["last_used"] = max((last.get(k, "") for k in keys), default="") or None
        s["used_in"] = sorted({p for k in keys for p in projects.get(k, set())})
        known |= keys
    diagnose(skills, raw)
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
        "platform": sys.platform,
        "context": CONTEXT,
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, out)
    if not QUIET:
        print(f"{len(skills)} skills, {total} calls, {len(data['warnings'])} warnings -> {out}")
    if open_it:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
