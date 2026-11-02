---
name: farm
description: Rebuild the Skill Farm page from local skills and transcripts, then open it in the browser. Optional argument demo, fetch or reshuffle.
argument-hint: "[demo | fetch | reshuffle]"
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/build.py" *), Read, Write, Edit
---

Rebuild the Skill Farm page and open it.

Pick the flags from the argument "$ARGUMENTS":

- empty: `--plugin --open`
- `demo`: `--plugin --demo --open`, a page built from made-up data
- `fetch`: `--plugin --fetch --open`, also runs `git fetch` on skill repos and plugin marketplaces so update hints are current
- `reshuffle`: `--plugin --reshuffle --open`, gives every skill a new plant
- anything else: tell the user the accepted arguments and stop

First give new skills a Chinese display name. Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/build.py" --plugin --unnamed
```

It prints `names_file` and a list `unnamed`. If the list is empty, skip this step. Otherwise read `names_file` if it exists (a JSON object), add one entry per unnamed skill with its `invoke` as the key and a short natural Chinese name of 2 to 8 characters as the value, based on its description, keep every existing entry unchanged, and write the file back. It also prints `blurbs_file` and a list `no_blurb`. For each skill in `no_blurb`, add an entry to `blurbs_file` (a JSON object, read it first if it exists) with the `invoke` as the key and the value `{"zh": "...", "en": "..."}`: one plain sentence in each language saying what the skill does, at most about 16 Chinese characters or 8 English words, no brackets. Keep existing entries unchanged.

It also prints `tags_file`, `tag_vocab` (tags already in use, with counts), `tag_en` and a list `untagged`. For each untagged skill, add an entry to `tags_file` (a JSON object, read it first if it exists) with its `invoke` as the key and a list of one or two tags as the value. Reuse tags from `tag_vocab` whenever one fits; only create a new tag when none does, keep it short, write it in the same language as the existing tags, and add its English name to the `_英文` object in the same file. Never change or remove tags that are already there. Don't mention these steps in your reply unless one fails.

Then run exactly this command with the chosen flags:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/build.py" <flags>
```

Then reply in one or two short sentences: the summary line the script printed and where the page is. Your page, `farm.json` and `tags.json` live in `~/.claude/skill-farm/` unless `SKILL_FARM_HOME` points somewhere else. If the command fails, show the error and suggest checking that `python3` is version 3.9 or newer.
