# How it works

- **Usage data.** The iPhone syncs app-focus events to the Mac's Biome store,
  `~/Library/Biome/streams/restricted/App.InFocus/remote/<device ID>/`, in SEGB files of protobuf
  records (bundle ID, start or end, timestamp). Reading it needs Full Disk Access; nothing else
  in the skill does, since layout reads and writes go over USB. Archived copies in `$D/data/raw` can
  be ranked without it.
  `scripts/infocus.py` decodes the records. `scripts/rank.py` builds sessions per device (each
  capped at 4 hours) and scores apps: the geometric mean of their rank by days used, opens and hours.
- **The layout service.** `com.apple.springboardservices` reads and writes the layout as a list of
  pages, through pymobiledevice3. On the phone it's a relay process, `springboardservicesrelay`,
  that maps a fixed set of commands to SpringBoard routines (`getIconState` → `_SBXXGetIconState`).
  Unknown commands drop the connection silently. `formatVersion` 1–10 all return the same layout.
- **Gaps.** The plain list format packs icons to the left. Sending `setIconState` a *dictionary* in
  SpringBoard's on-disk shape (`buttonBar`, `iconLists`, `listUniqueIdentifiers`, `listMetadata`)
  lets items be pinned. `fixedLocations` maps an app's bundle ID, or `"folder:<uniqueIdentifier>"`
  for a folder, to a slot from 0 to 23 on a 4×6 grid. SpringBoard keeps page and folder IDs we
  supply. Unpinned items fill the first free slot in list order. See
  `assets/iconstate-pins-excerpt.md`.
- **Proof.** The service never reports positions, but it lists each page in slot order. `push.py`
  sends pinned items first, in reverse slot order, so a page that reads back sorted proves its pins.
- **A plain write clears every pin.** Pass all the pins on every write.

## Limits
- iPhone only (an iPad's grid and widgets differ), one phone connected at a time, and only from
  an agent running on the Mac itself: cloud chat sandboxes can't reach the Mac's files or USB.
- The App Store genre lookup uses `store_country` from `config.json` (default `us`). Apps missing
  from that store come back without a genre and are flagged for the user to judge.
- The service can't remove apps from the home screen. Any write puts App Library-only apps back on
  a page, so remove apps by hand, as the last step.
- The scripts don't edit the dock. Change it on the phone, then dump the layout again; the dock
  you send is written back as it was read.
- Widgets can be kept, moved and pinned (by the ID after `#` in `show`). On a page with pins,
  `push.py` pins each widget where the layout puts it: left unpinned, SpringBoard may move it
  below unpinned icons. Adding new widgets is untested.
- Hidden pages and Focus-specific pages are untested: each write sends new page IDs and only the
  layout's main keys, so they may not survive a write. Check them after the first write.
- Usage time is estimated from app-switch events, and the Mac keeps only about 4 weeks of it. Run
  `rank.py --archive` every few weeks for longer windows.
- Tested on iOS 27.0.1 with pymobiledevice3 11.43.1. An iOS update can change any of this; the
  troubleshooting reference says what to re-check.
