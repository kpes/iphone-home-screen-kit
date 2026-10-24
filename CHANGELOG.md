# Changelog

## 1.1.0
- Fix: on a page with pins, a widget could land below the unpinned icons instead of where the
  layout put it, and `push.py` then reported the pins as FAILED. Seen on iOS 27.0.1 with the
  documented pattern (a widget on top, pins in the bottom rows). `push.py` now pins every widget on
  a pinned page at the slot the layout gives it, so SpringBoard has nothing left to decide.
- Widgets can be pinned: `PAGE:<widget ID>:SLOT`, the ID being the part after `#` in
  `homescreen.py show`. SpringBoard keys widget pins by `displayIdentifier`; the slot is the
  widget's top-left cell. `--check` refuses a widget pin that runs off the grid or over another pin.
- `--check` (and `push.py` before writing) refuses a widget that would start on row 2, 4 or 6, from a
  pin or from following an odd number of icon rows: iOS starts widgets only on rows 1, 3 and 5 and
  moved such a widget up a row.
  Tested with a medium widget on iOS 27.0.1; small and large widgets and Smart Stacks are untested.
- `homescreen.py show` prints a widget as `<bundle ID>#<ID>`; `arrange.py` takes that, the ID, or
  the bundle ID.
- The layout simulation counts every cell of a pinned widget, and tells two widgets from one app
  apart.

## 1.0.1
- Fix: `rank.py --archive` no longer overwrites archived usage files. The Mac prunes old days from
  inside the same files it keeps updating, so overwriting lost history; a changed file is now saved
  beside the old copy, and ranking merges them.

## 1.0.0
First public release.
- Arranges the home screen over USB in any layout, with blank spaces: apps and folders pinned to
  exact grid slots, verified on readback, plus new folders.
- Optionally ranks apps by days used, opens and time, from Screen Time data synced to the Mac.
- Safety: an offline check before writing, a live-layout comparison, an automatic snapshot (with the
  previous write's pins) before every write, no overwritten files, an iPhone-only guard, grid-aware
  pins, and an iOS-version gate with a per-user record of versions that passed the pin tests.
- Agent Skill with first-run setup, a monthly refresh procedure and troubleshooting. Installs as a
  Claude Code plugin (`/plugin install`), or by copying the skill folder for Codex and other agents.
- Tested on iOS 27.0.1 with pymobiledevice3 11.43.1.
