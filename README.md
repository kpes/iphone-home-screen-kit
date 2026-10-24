# iPhone home screen skill

An [Agent Skill](https://agentskills.io) that arranges your iPhone home screen by script, from your
Mac, however you want it: your own order, folders and blank spaces. Leave a row empty, or put an app
or folder in any grid slot.

- **Arranges the layout you describe** (pages, folders, widgets) and writes it over USB, after an
  offline check that no icon will be lost, saving the previous layout before every write.
- **Pins apps and folders to exact grid slots**, leaving gaps, and **proves the pins landed** by
  reading the layout back.
- **Optionally ranks your apps** by days used, number of opens and time spent, from the Screen Time
  data your iPhone syncs to your Mac, to suggest what goes where.
- **Sets itself up and troubleshoots:** just ask your agent, e.g. "put my travel apps in a folder on
  page two" or "refresh my home screen by how I use it".

> **Use at your own risk.** This relies on undocumented Apple interfaces (the SpringBoard layout
> service and the on-disk icon state format), tested on iOS 27.0.1 with pymobiledevice3 11.43.1.
> Any iOS update can change them. Every write is checked first and read back, and you can restore
> an earlier layout at any time, but Apple doesn't support any of this.

## Install
Install it once, for your user, and it's available in every session. You don't need to open a
project folder: your settings and data live in `~/iphone-home-screen/`, wherever you start.

### Claude Code: terminal, or the Code tab in the Claude desktop app (recommended)
Install it as a plugin. In Claude Code, run:
```text
/plugin marketplace add kpes/iphone-home-screen-kit
/plugin install iphone-home-screen@iphone-home-screen-kit
```
Or from your shell: `claude plugin marketplace add kpes/iphone-home-screen-kit`, then
`claude plugin install iphone-home-screen@iphone-home-screen-kit`. To update later, run
`/plugin marketplace update iphone-home-screen-kit`.

**Without the plugin system**, copy the skill folder into your personal skills:
```bash
git clone --depth 1 https://github.com/kpes/iphone-home-screen-kit /tmp/iphone-home-screen-kit
mkdir -p ~/.claude/skills && cp -R /tmp/iphone-home-screen-kit/.claude/skills/iphone-home-screen ~/.claude/skills/
```

### Codex
Copy the skill folder into `~/.agents/skills/`. Codex picks it up automatically; restart it if not.
```bash
git clone --depth 1 https://github.com/kpes/iphone-home-screen-kit /tmp/iphone-home-screen-kit
mkdir -p ~/.agents/skills && cp -R /tmp/iphone-home-screen-kit/.claude/skills/iphone-home-screen ~/.agents/skills/
```

### Other agents
Any agent that supports [Agent Skills](https://agentskills.io) **and can run commands on your
Mac**: copy the `iphone-home-screen` folder (above) into the folder your agent loads skills from.
Many read `~/.agents/skills/`; check your agent's docs.

**Not supported:** the regular Claude chat (claude.ai, or the chat in the desktop app). Skills there
run in a cloud sandbox that can't reach your Mac's files or a USB-connected iPhone.

### First use
Say **"set up my home screen"**. The skill checks the requirements, installs its one dependency
into your data folder, finds your phone, asks how you want things organized, and saves your
choices. Later, ask for changes ("make a Travel folder on page two") or **"refresh my home screen"**.

## Where it works, and where it doesn't
- **Works:** agents that run on your Mac and can run commands there: Claude Code (terminal, or
  the Code tab in the Claude desktop app, with or without a project folder) and Codex.
- **Doesn't work:** the regular Claude chat, on claude.ai or in the desktop app. Skills there run
  in a cloud sandbox with no access to your Mac's files or a USB-connected phone.
- **iPhone only.** An iPad's grid and widgets differ, and it hasn't been tested.
- **One phone at a time.** The scripts talk to the first iPhone on USB.
- **Tested on iOS 27.0.1.** On any other version, the skill runs two quick pin tests (an app and a
  folder) before its first real write, and the scripts refuse to write pins until both pass.
- **Display Zoom** (larger icons) should work, since the scripts read the phone's grid size, but it
  hasn't been tested yet.

## Requirements
- A Mac with Python 3.9 or newer and the Xcode command line tools (`xcode-select --install`). Phone
  writes were tested with Python 3.15; the offline tests also pass on the system Python 3.9, but
  phone use on 3.9 is untested. The pinned versions in `constraints.txt` need Python 3.11 or newer.
- An iPhone on USB, trusted by the Mac, unlocked while you work.
- **For usage ranking only:**
  - On the iPhone, **Settings → Screen Time → Share Across Devices** on, so usage syncs to the Mac. It
    takes a day or more before useful data appears, and the Mac keeps about 4 weeks of it.
  - **Full Disk Access** (System Settings → Privacy & Security) for the app running your agent
    (Terminal, or the Claude app), restarted after you grant it. It's needed only to read that synced
    usage data, which macOS protects. Layout reads and writes, pins and backups go over USB and don't
    need it, so you can turn it on just while ranking, or skip ranking and arrange things yourself.

## What's in the skill
| Path | What it is |
|---|---|
| `SKILL.md` | Setup, the refresh procedure and restore points |
| `scripts/` | `rank.py` (usage ranking), `homescreen.py` (read the layout), `arrange.py` (build a page), `push.py` (check, write with pins, verify), `infocus.py` (usage decoder) |
| `references/` | `commands.md`, `how-it-works.md`, `troubleshooting.md` |
| `assets/` | Example `config.json`, an example pin file, and an excerpt of iOS's pin format |

`.claude-plugin/` makes the repo a Claude Code plugin and marketplace whose one skill is that folder.
The repo also has `tests/` (offline tests, no phone needed: `python3 -B -m unittest discover -s tests`)
and a CI workflow that runs them and the official `skills-ref validate`.

Your settings, usage archive and layout snapshots live in `~/iphone-home-screen/` (or
`$IPHONE_HOME_SCREEN_DIR`), outside the skill.

## Legal and safety
- **Not affiliated with or endorsed by Apple.** iPhone, iOS, Xcode and Screen Time are trademarks
  of Apple Inc., used here only to describe what this works with.
- **No warranty.** This kit is MIT-licensed (see `LICENSE`) and provided as is. It writes to your
  phone's home screen through undocumented interfaces. Save a restore point before experimenting,
  and use it at your own risk.
- **Dependency license.** It depends on [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
  (GPL-3.0-or-later), which you install separately and which isn't included here. If you
  redistribute this kit bundled with pymobiledevice3, the bundle must follow the GPL.
- **Full Disk Access is broad.** It's granted to the whole app running your agent (Terminal or the
  Claude app), not just this skill, so anything that app runs can read protected data such as Mail
  and Messages. Grant it only to an app you trust, and turn it off again in System Settings →
  Privacy & Security → Full Disk Access whenever you're not using it.
- **Work devices.** Ranking needs Full Disk Access, and troubleshooting may make local backups. Check your
  organization's IT policy before using it on a managed Mac or iPhone.
- **Your data stays local.** Usage data, layouts and settings stay on your Mac, in your data folder
  (`~/iphone-home-screen` by default), never in the skill or this repo. The only network call is the
  optional App Store genre lookup (`--lookup`), which sends app bundle IDs to Apple. The usage
  archive (`data/raw/`) keeps growing each time you archive; delete old files whenever you like.
- **Removing everything:** delete the skill folder and `~/iphone-home-screen`, and turn off Full Disk
  Access for the app. Your home screen stays as it was last written.

## Reporting problems
A new iOS version is the most likely thing to break this. If the pin tests fail, or a write doesn't
come back as sent, please open an issue with the **iOS compatibility** template: your iOS version,
iPhone model, the `homescreen.py show` first line and what the pin tests printed. Remove device IDs
and anything personal first. Issues are welcome; replies may be slow. For anything security-related,
see [SECURITY.md](SECURITY.md).

| iOS | Status |
|---|---|
| 27.0.1 | Tested: app and folder pins confirmed |

Built with [pymobiledevice3](https://github.com/doronz88/pymobiledevice3).
