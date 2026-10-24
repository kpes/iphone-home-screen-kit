# iPhone home screen kit

Arranges your iPhone home screen from your Mac, however you want it: your own order, folders and
blank spaces. Leave a row empty, or put an app or folder in any grid slot.

- **Arranges the layout you describe** (pages, folders, widgets) and writes it over USB, saving your
  current layout first so any change can be undone.
- **Pins apps and folders to exact grid slots**, leaving gaps, and reads the layout back to prove
  they landed.
- **Optionally ranks your apps** by how much you use them, from the Screen Time data your iPhone
  syncs to your Mac.
- **Just ask:** "put my travel apps in a folder on page two" or "refresh my home screen by how I
  use it".

It works in the Claude desktop app (as an extension), and in Claude Code, Codex and other agents
that run commands on your Mac (as an [Agent Skill](https://agentskills.io)).

> **Use at your own risk.** This relies on undocumented Apple interfaces, tested on iOS 27.0.1, and
> an iOS update can change them. Every write is checked first and read back, and you can always
> restore an earlier layout, but Apple doesn't support any of this.

## Install

### Claude desktop app
1. Download `iphone-home-screen.mcpb` from the
   [latest release](https://github.com/kpes/iphone-home-screen-kit/releases/latest).
2. Double-click it and choose **Install**. The first install takes a minute or two.
3. Connect and unlock your iPhone, then say **"show my home screen"** in a new chat.

### Claude Code
```text
/plugin marketplace add kpes/iphone-home-screen-kit
/plugin install iphone-home-screen@iphone-home-screen-kit
```
To update later, run `/plugin marketplace update iphone-home-screen-kit`.

### Codex and other agents
Copy the skill folder into your agent's skills folder (`~/.agents/skills/` for Codex and many
others):
```bash
git clone --depth 1 https://github.com/kpes/iphone-home-screen-kit /tmp/iphone-home-screen-kit
mkdir -p ~/.agents/skills && cp -R /tmp/iphone-home-screen-kit/.claude/skills/iphone-home-screen ~/.agents/skills/
```

### First use
Say **"set up my home screen"**. Claude checks what's needed, finds your phone, asks how you want
things organized and saves your choices. Later, ask for changes or say **"refresh my home screen"**.

## Requirements
- A Mac, and an iPhone (not iPad) connected by USB, trusted, and unlocked while you work. One phone
  at a time.
- For Claude Code and other agents: Python 3 and the Xcode command line tools
  (`xcode-select --install`).
- For usage ranking only: **Screen Time → Share Across Devices** on the iPhone, and **Full Disk
  Access** for the app running Claude (System Settings → Privacy & Security). Arranging needs
  neither.

It doesn't work in claude.ai in a browser, the Claude mobile apps or on Windows: they can't reach a
phone on your Mac's USB.

## Good to know
- **New iOS versions:** before the first real write on an untested version, Claude runs two quick
  pin tests.
- **Full Disk Access** applies to the whole app, not just this kit. Turn it off when you're not
  ranking.
- **Your data stays on your Mac**, in `~/iphone-home-screen`. Apart from installing its
  dependencies, the only network use is an optional App Store lookup that sends app IDs to Apple.
- **To remove everything:** uninstall the extension or plugin, delete `~/iphone-home-screen`, and
  turn off Full Disk Access. Your home screen stays as it is.
- **Legal:** not affiliated with or endorsed by Apple. MIT licensed, with no warranty. Uses
  [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) (GPL-3.0-or-later), which is
  installed separately, not bundled.

## Problems
A new iOS version is the most likely thing to break this. Please open an issue with the **iOS
compatibility** template, and remove anything personal first. For security issues, see
[SECURITY.md](SECURITY.md).

| iOS | Status |
|---|---|
| 27.0.1 | Tested |

Developing or releasing the kit: see [DEVELOPING.md](DEVELOPING.md).
