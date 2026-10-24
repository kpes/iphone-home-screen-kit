---
name: iphone-home-screen
description: Arranges an iPhone's home screen from a Mac over USB in whatever layout the user wants, putting apps and folders on chosen pages in a chosen order, pinning them to exact grid slots with blank spaces around them, and creating folders, with every write checked and verified. Can also rank apps by real use (Screen Time data synced to the Mac) to suggest what goes where. Use when the user wants their iPhone home screen organized, rearranged, set up, refreshed or checked; wants apps moved, grouped into folders, put in a specific spot, or a gap or blank row added; asks which apps they use most; or when a layout write, pin, gap or usage read behaves unexpectedly (gaps gone, icons packed together, an item in the wrong spot, no usage data, connection dropped), including after an iOS update.
license: MIT (see LICENSE)
compatibility: Requires macOS with Python 3 and the Xcode command line tools, one iPhone (not iPad) connected by USB and trusted, and, for usage ranking only, iPhone Screen Time "Share Across Devices" plus Full Disk Access for the app running the agent. Needs network to install its one dependency (pip); after that only the optional App Store genre lookups use it. Runs locally (e.g. Claude Code), not in cloud chat sandboxes.
metadata:
  author: Keith Pesavento
  version: "1.0.1"
  tested-ios: "27.0.1"
  tested-pymobiledevice3: "11.43.1"
---

# iPhone home screen

Arranges the user's iPhone home screen from their Mac, over USB through SpringBoard's layout service: any order, folders and blank spaces they want. It can also rank apps by real use, from Screen Time data synced to the Mac, to suggest a layout; that's optional. This uses undocumented Apple interfaces, so treat every write with care.

**Two folders:**
- **This skill's folder** holds the scripts (`scripts/`), references (`references/`) and templates (`assets/`). Run commands from here.
- **The user's data folder**, `~/iphone-home-screen` (or `$IPHONE_HOME_SCREEN_DIR`), called `$D` below, holds their `config.json`, `layout.md`, `pins.txt`, the venv `pmd/`, usage archive and rankings `data/`, and layout snapshots `layouts/`. Nothing personal goes in this skill's folder.

Set `D="${IPHONE_HOME_SCREEN_DIR:-$HOME/iphone-home-screen}"` in the shell first. Script names below (`rank.py`, `homescreen.py`, `arrange.py`, `push.py`) mean `scripts/<name>` run from this folder: phone commands (`homescreen.py`, `push.py` writes) with `"$D/pmd/bin/python" -B`, the others with `python3 -I -B`. Full command reference: [references/commands.md](references/commands.md). How it works and its limits: [references/how-it-works.md](references/how-it-works.md).

**If anything behaves unexpectedly, stop and read [references/troubleshooting.md](references/troubleshooting.md) before trying fixes.** Don't guess formats: copy what iOS itself writes.

## Before anything else
- **No `$D/config.json` or `$D/layout.md` yet** → do First-run setup below.
- **Otherwise** → read `$D/layout.md` (the layout this user chose) and follow it unless they ask for a change.

## First-run setup
1. Check the requirements in the `compatibility` field above with the user. **Full Disk Access is only for ranking:** it lets `rank.py` read the synced Screen Time data. Layout reads and writes, pins and backups all go over USB and don't need it. If they want ranking, it must be granted to the app running the agent, which must be restarted afterwards; they can turn it off again after each archive and ranking. Screen Time sharing needs a day or more before useful data appears. Without ranking, skip the device lookup in step 3 and the ranking in step 5, and build the layout from what they tell you.
2. `mkdir -p "$D/layouts" "$D/data" && python3 -m venv "$D/pmd" && "$D/pmd/bin/pip" install -r scripts/requirements.txt` (add `-c scripts/constraints.txt` for the exact tested versions; that needs Python 3.11 or newer). Then `"$D/pmd/bin/python" -B scripts/homescreen.py show` must print the phone, its grid, the dock and pages 1–2. **If it says the iOS version is NOT tested,** tell the user. `push.py` refuses pins on that version until it passes **both** control pin tests (app, then folder; troubleshooting reference, "After an iOS update" steps 2–3). Run each test with `--untested-ios-ok`; each confirmed test is recorded in `$D/tested-ios.txt`, and once both are, normal writes work without the flag. A grid other than 4×6 (Display Zoom) should work but is untested: use its slot numbers, and pass `--grid` to `arrange.py` and `push.py --check`.
3. `python3 -I -B scripts/rank.py --devices` lists synced devices, newest first, with each one's date range and top apps; it can't show device names. Ask which is their phone (usually the newest). If an older one is their previous phone, offer to include it too, for more history. Write `$D/config.json` from `assets/config.example.json` with those IDs and labels. `rank.py` needs this file before it will rank.
4. Dump the layout: `homescreen.py dump "$D/layouts/<date>-original.plist"`. If they placed gaps by hand, warn them that restoring this dump packs those gaps away; to record them, offer the layout-file backup in troubleshooting step 4 of "After an iOS update". Ask, showing their current dock:
   - **Which apps stay in the dock.** They're never ranked. Scripts don't edit the dock: to change it, the user drags apps on the phone, then you dump again.
   - **What else to keep out:** Settings, games, the app behind a widget they keep.
   - **Their country's App Store,** if not the US (`store_country` in `config.json`, e.g. `gb`), so genre lookups find their apps.
   - **Which widgets to keep, and their size** (small, medium or large; it decides how many rows they take).

   Dock apps and exclusions go in `config.json`; widgets go in `layout.md` (step 6).
5. **Ask how they want it organized.** Their own arrangement ("Maps next to Uber, a Travel folder, a blank row under the widget"), a layout suggested from usage ranking, or a mix. Respect their choice; ranking is a suggestion, never a requirement.
   - **Ranking** (if they want it): do refresh steps 1–2 (rank without `--since`, then vet). Before the first `--lookup`, ask: it sends their bundle IDs to Apple's App Store lookup, and without it games can't be recognized. Show the top 15.
   - **Offer a layout** and let them change it. A tested default for a usage-based layout, matching `assets/pins.example.txt`:
     - Page 1: a widget in rows 1–2, the next tier (ranks 9–12) in row 3, row 4 blank, ranks 5–8 in row 5 and ranks 1–4 in row 6, just above the dock.
     - Page 2: themed rows.
     - Page 3: the rest in category folders, grouped with gaps. Folders are created by writing them into the layout (see "Creating folders" in the commands reference); `arrange.py` only moves existing ones.
6. Write their choices to `$D/layout.md`: what goes where by page and row, the widgets kept, and the rules (e.g. "rank 1–4 → row 6"). Write the matching `$D/pins.txt` (format: `assets/pins.example.txt`).
7. Save a restore point (bottom of this file), then do refresh steps 3–8.

## Refresh procedure (a recipe: do every step)
For a usage-based layout. For their own arrangement, skip steps 1–2 and build what they describe, then do steps 3–8.
1. `homescreen.py show` → note the iOS version and grid; a new iOS version → control pin test first (see setup step 2). `rank.py --devices` → the phone's ID still matches `config.json`. Then `--archive`, then rank to `"$D/data/ranking-<today>.csv"` with `--lookup` and `--since <day after the last refresh>` (the date of the newest `$D/layouts/*-after.plist`), unless the user names a window. Use `--device <label>` to rank one phone.
2. **Vet the top ranks before using them:**
   - Any app flagged `(genre unknown: game?)` or with an empty `genre` → ask. An excluded genre must not reach the home screen.
   - Many opens on few days, or an app tied to a one-off event (a purchase, a trip, phone setup) → ask whether to skip it.
   - A top app missing from the layout dump is only in the App Library → ask the user to drag it onto the home screen, then dump again.
   - Re-rank with `--skip <bundle IDs>` for each app ruled out, so the ranks match what goes where.
3. Snapshot: `homescreen.py dump "$D/layouts/<YYYY-MM-DD>-before.plist"`. Never build from an older file.
4. Build each changed page with `arrange.py BEFORE NEW PAGE <items in screen order>`. A full page stays full: an arriving app takes the slot of the one that left. If that breaks a page's theme, say which rows are affected and offer to re-theme.
5. Update `$D/pins.txt` for the new apps, then `push.py --check BEFORE NEW --pins "$D/pins.txt"` (plus `--grid` if not 4×6) → it must print `OK: safe to push`. It also catches a changed dock, duplicate or out-of-range pins, and pins that would push a widget aside.
6. **Show the user** the new pages and pin changes, and get a yes before writing.
7. Write: `push.py NEW "$D/layouts/<date>-after.plist" --pins "$D/pins.txt"` (it requires `--pins`, `--pin` or `--no-pins`, and never overwrites a file). It refuses if the phone's layout no longer matches BEFORE (apps installed or removed since): dump again and rebuild. It saves the layout from just before the write, with the previous write's pins, as `<date>-after.autosave-before-<time>.plist` and prints the restore command; tell the user. It exits non-zero on any problem. `lost` and `added` must both be `[]`, and every pinned page must print `pins page N: CONFIRMED`. `FAILED` → stop and read the troubleshooting reference. `not provable` → ask the user to look at that page.
8. If apps came back onto pages from the App Library, remind the user to remove them by hand. Do it last, since any later write puts them back.

## Experiments and restores
`push.py` snapshots the layout before every write, but for experiments also save your own restore point first: dump the layout **and copy `$D/pins.txt` at the same moment**. Restore by pushing that dump with `--pins` set to that copy, and check that each pinned page prints `CONFIRMED`. Ask the user before a layout-file backup (`backup2`: about 8 minutes, and the phone may ask for its passcode). Name test layouts `<date>-test-*.plist`, never `-after.plist`, so they aren't mistaken for the last real refresh.
