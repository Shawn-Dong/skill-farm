# Skill Farm

See every Claude Code skill on your computer as a potted plant. Skills you use grow, skills you never touch stay as seeded soil, and skills that clash get flagged with a fix.

Everything runs locally. One Python script reads your skill folders and your local Claude Code transcripts, then writes a single HTML page. Nothing is uploaded anywhere.

[中文说明](#中文说明)

![Card view](docs/cards-en.png)

![Farm view](docs/farm-en.png)

## Why

If you use Claude Code a lot, skills pile up in six different places: your own, project folders, plugins, the ones built into Claude, the ones bundled with Claude Code, and Codex. You rarely know which ones Claude actually reaches for, which ones never fire, and which ones have descriptions so similar that Claude may pick the wrong one.

Skill Farm answers three questions from your real usage:

- Which skills are working for me, and how often?
- Which ones have never been used?
- Which ones need attention: similar descriptions, broken front matter, a newer version upstream, or a skill you used before that is gone now?

## What you get

- **Every skill in one place.** Your own skills, project skills, plugin skills, skills built into Claude, skills bundled with Claude Code, and Codex skills.
- **Growth from real usage.** Counts come from your local transcripts in `~/.claude/projects`. A skill with no uses is seeded soil, 1 to 4 uses is a seedling, 5 or more is a mature plant. 40 plant kinds, so most skills get their own.
- **Problems with a fix.** A small mark on the card opens the problem and concrete steps to resolve it. You can ignore a warning you're fine with.
- **Update hints.** Plugins with a newer version in their marketplace, and git-based skills that are behind their remote.
- **Filters.** By source, by the project a skill was used in, and by your own tags.
- **Recent activity.** A timeline of the last skill calls and where they happened.
- **Two views, two palettes, two languages.** Cards or farm, peach or baby blue, Chinese or English.

## Quick start

Requires Python 3.9 or newer. No packages to install.

```bash
git clone https://github.com/Shawn-Dong/skill-farm.git
cd skill-farm
python3 build.py --open
```

That writes `skill-board.html` next to the script and opens it. Run it again any time to refresh.

To look around without your own data first:

```bash
python3 build.py --demo --open
```

### Options

| Flag | What it does |
|---|---|
| `--open` | Open the page in your browser when done |
| `--fetch` | Fetch git remotes first so update hints are current. Slower, uses the network |
| `--reshuffle` | Reassign plants evenly across all plant kinds |
| `--demo` | Build `demo.html` from made-up data instead of yours |

The page also reads `?lang=en`, `?lang=zh`, `?view=farm` and `?theme=blue` from the URL.

## Make it yours

- **Tags.** Copy `tags.example.json` to `tags.json` and list tags per skill. Add English names under `_英文` if you write tags in Chinese.
- **Plants.** `farm.json` remembers which plant each skill got. Change any entry to another file in `assets/plants`, or delete a line to have it reassigned. `growth` sets how many uses it takes to become a seedling and a mature plant.
- **More art.** Drop new transparent PNGs into `assets/plants`, add their sapling stage to `assets/growth-map.json`, and rebuild. Existing assignments stay put; new plants go to new skills first.

## How it works

`build.py` scans these places for `SKILL.md` files:

- `~/.claude/skills` for your own skills
- `.claude/skills` in every project folder that appears in your transcripts
- installed plugins listed in `~/.claude/plugins/installed_plugins.json`
- the skills that ship with the Claude desktop app, when found
- `~/.codex/skills`

Usage comes from the `Skill` tool calls recorded in `~/.claude/projects/**/*.jsonl`. The result is injected into `template.html` and saved as `skill-board.html`. Thumbnails are made with `sips` on macOS; on other systems the source images are used as they are.

## Privacy

- Your data never leaves your computer. The script makes no network calls unless you pass `--fetch`, which only runs `git fetch` on your own skill repos and plugin marketplaces.
- `skill-board.html`, `farm.json` and `tags.json` contain your own data. They're in `.gitignore`. Don't commit or share them.
- The page loads two web fonts, LXGW WenKai from jsDelivr and Fraunces from Google Fonts. Without a network it falls back to system fonts.

## Limits

- The transcript format is not a public API. A Claude Code update may change it, and counts can break until the script is updated.
- Counts only include skills Claude called through the `Skill` tool, not skills you read by hand.
- Tested on macOS. Linux and Windows should work, but the desktop app skill folder is only looked up on macOS.

## Credits

- Plant, growth and greenhouse images were generated with an AI image model for this project and are released with it under the MIT license.
- Fonts: [LXGW WenKai](https://github.com/lxgw/LxgwWenKai) and [Fraunces](https://github.com/undercasetype/Fraunces), both under the SIL Open Font License.

This is an independent project. It is not made by or affiliated with Anthropic.

## License

MIT

---

## 中文说明

把电脑上所有的 Claude Code skill 种成一盆盆植物。用得越多长得越好，从没用过的就是一盆刚播种的土，描述打架或者格式有问题的会标出来，并告诉你怎么改。

全部在本机运行。一个 Python 脚本读取 skill 文件夹和本地的 Claude Code 对话记录，生成一个 HTML 页面，不上传任何东西。

![中文与天蓝配色](docs/cards-zh-blue.png)

**它回答三个问题**

- 哪些 skill 真的在替我干活，各用了几次？
- 哪些从来没被用过？
- 哪些需要处理：描述太像、格式有问题、上游有新版、以前用过但现在找不到了？

**开始用**

需要 Python 3.9 或更新版本，不用装任何包。

```bash
git clone https://github.com/Shawn-Dong/skill-farm.git
cd skill-farm
python3 build.py --open
```

想先看看效果，可以用示例数据：

```bash
python3 build.py --demo --open
```

**自定义**

- 标签：把 `tags.example.json` 复制成 `tags.json`，按 skill 写标签。
- 盆栽：`farm.json` 记着每个 skill 种的是哪盆，可以手动改；`growth` 设置长成幼苗和成熟各需要用几次。
- 新素材：把透明背景的 PNG 放进 `assets/plants`，在 `assets/growth-map.json` 里写上对应的幼苗图，重新运行即可。

**隐私**

`skill-board.html`、`farm.json`、`tags.json` 里是你自己的数据，已经写进 `.gitignore`，不要提交或分享。只有加了 `--fetch` 才会联网，而且只是对你自己的 skill 仓库和插件市场运行 `git fetch`。

本项目是个人作品，不是 Anthropic 官方出品，与 Anthropic 没有关联。
