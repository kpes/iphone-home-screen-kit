# Commands

Run these from the skill's folder. `D` is the user's data folder: `~/iphone-home-screen`, or
`$IPHONE_HOME_SCREEN_DIR` if set. `rank.py` finds it on its own; the other scripts take every
path as an argument. `python3 -I -B` is enough for the usage scripts; anything that talks to the
phone needs the venv's `"$D/pmd/bin/python" -B`.

```bash
D=${IPHONE_HOME_SCREEN_DIR:-~/iphone-home-screen}
mkdir -p "$D/layouts" "$D/data" && python3 -m venv "$D/pmd" && "$D/pmd/bin/pip" install -r scripts/requirements.txt
#   optional: add -c scripts/constraints.txt for the exact tested versions (resolved on Python 3.15)
cp assets/config.example.json "$D/config.json"     # then edit it
python3 -I -B scripts/rank.py --devices            # find your phone's ID → config.json
python3 -I -B scripts/rank.py --archive            # keep a copy of usage data (every few weeks; never overwrites)
python3 -I -B scripts/rank.py "$D/data/ranking-2026-11-01.csv" --lookup
"$D/pmd/bin/python" -B scripts/homescreen.py dump "$D/layouts/2026-11-01-before.plist"
python3 -I -B scripts/arrange.py "$D/layouts/2026-11-01-before.plist" "$D/layouts/2026-11-01-new.plist" 1 \
    <widget bundle ID> <app or folder> ...          # set page 1 to exactly these, in screen order
python3 -I -B scripts/push.py --check "$D/layouts/2026-11-01-before.plist" "$D/layouts/2026-11-01-new.plist" \
    --pins "$D/pins.txt"
"$D/pmd/bin/python" -B scripts/push.py "$D/layouts/2026-11-01-new.plist" "$D/layouts/2026-11-01-after.plist" \
    --pins "$D/pins.txt"
```

- **`rank.py`** options: `--since/--until` (date window), `--device` (one phone), `--skip` (leave
  out apps the user ruled out), `--top`, `--lookup` (fetch App Store genres; sends bundle IDs to
  Apple). Excluded apps stay in the CSV, with the reason.
- **`homescreen.py`**: `show` prints the phone's model, iOS version (and whether it's tested) and grid,
  then the dock and pages 1–2. `dump OUT` saves the full layout. Both are read-only. They talk to the
  first iPhone on USB, so connect one at a time.
- **`arrange.py`** takes apps by bundle ID and folders by name, with or without brackets. Page 1
  is the first home screen page; page 0 (the dock) is refused, and one past the last page adds a page. It takes an app out of a
  folder when the app is listed. Displaced items go to the front of the next page. It stops if a
  page would overflow 24 slots (`--grid 4x5` for another grid).
- **`push.py --check`** confirms that no app or widget is lost, added or duplicated (folders are
  reported separately), that every page fits, and that the dock is unchanged. With `--pins` it also
  validates the pins: real pages and slots, no slot or item twice, nothing left without room, no
  widget pushed aside, and no pinned widget off the grid or over another pin. Pass `--grid 4x5` if `show` reports a grid other than 4×6.
- **`push.py`** writes, reads back and compares. It needs exactly one of `--pins FILE` (format:
  `assets/pins.example.txt`), `--pin PAGE:ITEM:SLOT` (repeatable) or `--no-pins`, and prints
  `pins page N: CONFIRMED`, `FAILED` or `not provable` per pinned page. On each pinned page it also
  pins every widget where the layout puts it (and says so). Before writing it refuses a
  non-iPhone, an existing AFTER, pins or pages that don't fit the phone's grid, pins on an iOS version
  that hasn't passed both pin tests (unless `--untested-ios-ok`; each confirmed app or folder test is
  then recorded in `$D/tested-ios.txt`), an empty pins file, and any mismatch with the live layout. It saves the live layout as
  `<AFTER>.autosave-before-<time>.plist`, with the previous write's pins (from `last-write.pins.txt`
  beside AFTER), and prints the restore command. After a good write it saves the pins it used as `<AFTER>.pins.txt`
  and `last-write.pins.txt`. It exits non-zero if anything was lost or added, or a pin didn't land.
- **Restore point:** every write makes one automatically. For experiments, also dump the layout and
  copy `$D/pins.txt` yourself. To restore, push that dump with `--pins` pointing at that copy (or
  `--no-pins` if there were none). `homescreen.py dump` and `arrange.py` also refuse to overwrite files.

## Creating folders
`arrange.py` moves existing folders; a new folder is created by writing it into a layout. Build it
from a fresh dump, then `push.py --check` and write as usual (the folder's apps leave their old spots):
```python
import plistlib
D = __import__('os').path.expanduser('~/iphone-home-screen')
st = plistlib.load(open(f'{D}/layouts/2026-11-01-before.plist', 'rb'))
want = ['com.example.app1', 'com.example.app2']           # bundle IDs to put in the folder
apps = [it for page in st[1:] for it in page if it.get('bundleIdentifier') in want]
for page in st[1:]:
    page[:] = [it for it in page if it.get('bundleIdentifier') not in want]
folder = {'displayName': 'Travel', 'listType': 'folder', 'iconLists': [apps[i:i + 9] for i in range(0, len(apps), 9)]}
st[3].append(folder)                                      # page 3, at the end
plistlib.dump(st, open(f'{D}/layouts/2026-11-01-new.plist', 'wb'))
```
Folder pages hold 9 apps (3×3). Apps already inside other folders need `arrange.py`-style removal
first (or build from a dump where they're loose).
