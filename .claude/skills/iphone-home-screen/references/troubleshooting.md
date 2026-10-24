# Troubleshooting the iPhone home screen project

Read this before trying fixes. Work cheapest first, and **ask the user before each step marked (ask)**. Background: [how-it-works.md](how-it-works.md). Commands: [commands.md](commands.md). `$D` is the user's data folder (see `SKILL.md`).

## First: what changed?
Ask the user before touching anything:
- **The exact command they ran.** Did it use `--pins "$D/pins.txt"`? `--no-pins`, or an old version of the scripts without that check, packs every page, and that's the most common cause of "the gaps are gone".
- **Which Python:** the data folder's venv, `"$D/pmd/bin/pip" show pymobiledevice3` (the version in `scripts/requirements.txt`).
- **Whether the gaps were already gone before they wrote anything** (an iOS update can rewrite the layout) or only vanished after a write.
- **What they see now**, concretely: which page, which row, which item.

Then compare a fresh read-only dump with the last known-good layout (the newest `$D/layouts/*-after.plist`, else the latest restore point): items, order, the widget's `gridSize`, and how many items come before each item that moved. Something extra or missing earlier on a page shifts everything after it. **"Gaps gone" and "an item moved" can be separate causes:** packing alone doesn't move an item that has no gap before it.

## Symptom → likely cause → first check
| Symptom | Likely cause | First check |
|---|---|---|
| Gaps gone after a write | Write ran with `--no-pins` or an older script | Fresh dump → `--check` → (ask) write it again with `--pins "$D/pins.txt"` |
| Gaps gone, `--pins` was used | Pin format changed (e.g. after an iOS update) | Run the control pin test (below) |
| `push.py` prints `pins page N: FAILED` | Pins ignored (`as sent`) or a different layout than simulated (`unexpected order`) | `as sent`: run the control pin test. `unexpected order`: compare the readback with the sent file; a widget size or an extra item may differ. A widget out of place after an iOS update: the widget pin key may have changed (step 4) |
| A folder in the wrong slot | Something before it changed, or folder pin format changed | Compare dumps, then run the folder pin test |
| `rank.py`: "no usage events" or "cannot read" | Full Disk Access missing, Screen Time sharing off, or device ID changed | `rank.py --devices`, the app's Full Disk Access setting, Screen Time → Share Across Devices on the iPhone |
| `rank.py`: "no devices configured" | No `$D/config.json` yet | Do First-run setup in `SKILL.md` |
| Data starts later than `--since` | The archive step was skipped and the Mac aged the data out | Nothing recovers it. Rank the window that exists |
| The relay drops the connection | Unknown command, or the phone locked | Unlock the phone. Use only the documented commands |
| `arrange.py`: "not found" | The app is only in the App Library, or was renamed/deleted | Look for it in the dump; ask the user |
| Apps reappear on pages after a write | Expected: writes put App Library-only apps back | The user removes them by hand afterwards |
| `push.py`: "differs from the phone" | Apps installed or removed, or the dock changed, since the dump | Dump again and rebuild from that |
| `push.py`: "refusing to overwrite" | A file of that name exists (often a retry) | Pick a new AFTER name; never delete a snapshot to make room |
| Hidden or Focus pages changed | Untested: writes send only the visible layout's pages and new page IDs | Re-check them in Settings → Focus and the page editor |

## After an iOS update: re-check in this order
Save a restore point first. Each write test is one write followed by a restore.
1. **Read** the layout (`homescreen.py show`). Does the service still answer?
   `show` also prints the iOS version and the grid. `push.py` reads the grid from the phone on every write, so a different grid (Display Zoom) is handled, but `pins.txt` slot numbers must fit it (0 to columns×rows−1).
2. **Control: app pin (ask).** Dump a fresh layout first (`homescreen.py dump "$D/layouts/<date>-test-before.plist"`). Pick an app and an empty slot on its page (page 1 full? use a page with room). Rewrite the layout with only that pin: `"$D/pmd/bin/python" -B scripts/push.py "$D/layouts/<date>-test-before.plist" "$D/layouts/<date>-test-app.plist" --pin <page>:<bundle ID>:<slot>`. On an untested iOS, add `--untested-ios-ok` (only for these two tests). `push.py` sends the pinned app first and checks the readback: `pins page <page>: CONFIRMED` = app pins work, and the pass is recorded. `not provable` proves nothing: pick a slot the app doesn't already sit in. Restore afterwards with the restore command it printed (each write saves `<AFTER>.autosave-before-<time>.plist`).
3. **Folder pin (ask):** the same with a folder by name, also with `--untested-ios-ok`: `--pin <page>:<folder name>:<slot>` (`push.py` pins it as `folder:<a uniqueIdentifier it assigns>`). `CONFIRMED` = folder pins work. Once both tests are recorded in `$D/tested-ios.txt`, `show` reports the version as tested and normal writes don't need the flag. Restore afterwards. Widget pins (keyed by the widget's `displayIdentifier`) are added automatically on every pinned page with a widget, but aren't part of the version gate: on a new iOS, also run the app pin test on a page that has a widget, so its `CONFIRMED` covers the widget pin.
4. **If a pin test fails** (ask): the user drags the item into a gap by hand, then back up only the layout file: `"$D/pmd/bin/pymobiledevice3" backup2 backup --full --only-regex 'SpringBoard/IconState' --patch-manifest "$D/backup-tmp"` (read-only, about 8 minutes; the phone may ask for its passcode). Find `Library/SpringBoard/IconState.plist` in the backup's `Manifest.db`, compare its `listMetadata` with `assets/iconstate-pins-excerpt.md`, and **copy whatever iOS now writes**. This is how the `folder:` prefix was found, after six guessed keys failed. Delete `$D/backup-tmp` afterwards.
5. **Watch SpringBoard's log** during a write: `"$D/pmd/bin/pymobiledevice3" syslog live -pn SpringBoard`. A layout write shows up as `_SBXXSetIconState`, followed by "current icon state saved".

## Guardrails
- Restore at the end of every experiment, and say what was restored.
- Never write without `push.py --check` passing first.
- Positions are never reported by the service. `push.py` proves pins from the readback order; when it says `not provable`, confirm on the phone.
