"""Write a layout to the phone, read it back, and report any difference.

  python3 -I -B scripts/push.py --check BEFORE NEW [--grid 4x6] [--pins FILE]
                                    compare two layouts offline (no phone), and validate pins
  "$D/pmd/bin/python" -B scripts/push.py SENT AFTER (--pins FILE | --pin P:I:S ... | --no-pins)
                                    [--untested-ios-ok]
                                    write SENT to the phone, save the readback to AFTER

--pins FILE reads one PAGE:ITEM:SLOT per line (# starts a comment). $D/pins.txt holds the
current layout's pins; pass it on every write, or the pages pack back together.

Always dump the live layout first (homescreen.py dump) and build SENT from that, not from
an old file: apps installed since would otherwise be re-placed by iOS.

One of --pins, --pin or --no-pins is required, so a typo can't silently drop the gaps.
Before writing, push.py:
- refuses anything but an iPhone, and refuses to overwrite AFTER or any snapshot;
- reads the phone's grid (columns x rows) and refuses pins or pages that don't fit it;
- refuses pins on an iOS version that hasn't passed the pin tests (homescreen.ios_tested),
  unless --untested-ios-ok; a passing run with that flag records the version as tested;
- compares SENT with the live layout and refuses if apps came or went, or the dock differs;
- saves the live layout as <AFTER>.autosave-before-<time>.plist, plus the pins of the last
  write (last-write.pins.txt beside AFTER), and prints the restore command.
It exits non-zero if anything was lost or added, or a pin didn't land.

--pin puts an app, folder or widget in a fixed grid slot, leaving gaps. Slots count from 0, left
to right, top to bottom (0-23 on a 4x6 grid; a widget's slot is its top-left cell, and a medium
widget at slot 0 covers the first two rows). Give an app by bundle ID, a folder by its name
(e.g. 1:Utilities:23), a widget by its ID (after the # in `homescreen.py show`). It sends the
layout in SpringBoard's on-disk shape with `listMetadata` -> `fixedLocations`: apps are keyed by
bundle ID, widgets by displayIdentifier, folders by "folder:<uniqueIdentifier>", with a
uniqueIdentifier we assign (SpringBoard keeps it). Unpinned items fill the remaining slots in
order. On a page with pins, each unpinned widget is pinned where the layout puts it, because
SpringBoard may otherwise move it below unpinned icons. Pinned items are sent first, in reverse
slot order, so the readback, which lists each page in slot order, proves the pins.
"""
import asyncio, copy, os, plistlib, shutil, sys, uuid
from collections import Counter, defaultdict

DEFAULT_GRID = (4, 6)  # columns, rows: an iPhone without Display Zoom


def ids(x, c, folders=None):
    """Count every app and widget (leaves) in a layout; folder names go to FOLDERS if given.
    Folders are containers: creating, renaming or emptying one isn't a lost or added item."""
    if isinstance(x, dict):
        if x.get('iconLists') is not None and 'bundleIdentifier' not in x:
            if folders is not None and x.get('displayName'):
                folders[x['displayName']] += 1
        elif x.get('elementType') == 'widget':
            c['widget:' + str(x.get('displayIdentifier') or x.get('bundleIdentifier'))] += 1
        else:
            c[x.get('bundleIdentifier') or x.get('displayIdentifier') or x.get('displayName')] += 1
        for l in x.get('iconLists') or []:
            ids(l, c, folders)
    elif isinstance(x, list):
        for i in x:
            ids(i, c, folders)
    return c


def is_widget(it):
    return it.get('elementType') == 'widget'


def name(it):
    if is_widget(it):  # one app can have several widgets: the ID tells them apart
        return f"{it.get('bundleIdentifier')}#{it.get('displayIdentifier')}"
    return it.get('bundleIdentifier') or '[%s]' % it.get('displayName')


def key(it):
    """What a pin names: an app's bundle ID, a folder's name, a widget's displayIdentifier."""
    if is_widget(it):
        return it.get('displayIdentifier')
    return it.get('bundleIdentifier') or it.get('displayName')


WIDGET_SHAPE = {'small': (2, 2), 'medium': (4, 2), 'large': (4, 4), 'extraLarge': (4, 4)}  # cols, rows


def shape(it, cols):
    if not is_widget(it):
        return 1, 1
    w, h = WIDGET_SHAPE.get(it.get('gridSize'), (1, 1))
    return min(w, cols), h


def cells(slot, w, h, cols):
    """The grid cells an item of W x H covers with its top-left corner at SLOT."""
    r, c = divmod(slot, cols)
    return [(r + dr) * cols + c + dc for dr in range(h) for dc in range(w)]


def fits(slot, w, h, grid):
    cols, rows = grid
    r, c = divmod(slot, cols)
    return c + w <= cols and r + h <= rows


def aligned(slot, cols):
    """Can a widget start here? SpringBoard puts widgets on row pairs (rows 1, 3, 5... counting
    from 1): a medium widget pinned to row 2 showed on row 1 instead (iOS 27.0.1). Small widgets
    are assumed to take the left or right half of a row pair (untested)."""
    r, c = divmod(slot, cols)
    return r % 2 == 0 and c % 2 == 0


def page_slots(page, cols):
    return sum(w * h for w, h in (shape(i, cols) for i in page))


def compare(before, new, grid=DEFAULT_GRID, pins=(), quiet=False):
    """Does NEW keep exactly BEFORE's apps and widgets, the same dock, and fit the grid, with valid
    pins? Folders are containers, so new or emptied folders are reported but don't fail."""
    cols, rows = grid
    fa, fb = Counter(), Counter()
    a = ids(before, Counter(), fa)
    b = ids(new, Counter(), fb)
    lost, added = list((a - b).elements()), list((b - a).elements())
    dupes = [k for k, n in b.items() if n > 1]
    over = {p: n for p, n in ((p, page_slots(page, cols)) for p, page in enumerate(new[1:], 1)) if n > cols * rows}
    dock_changed = [name(i) for i in before[0]] != [name(i) for i in new[0]]
    pin_errors = validate_pins(new, pins, grid) if pins else []
    if not quiet:
        print('items before/new:', sum(a.values()), sum(b.values()), '| lost:', lost, '| added:', added,
              '| duplicated:', dupes, f'| pages over {cols * rows} slots:', over or 'none',
              '| dock:', 'CHANGED (scripts must not edit the dock)' if dock_changed else 'unchanged')
        if fa != fb:
            print('folders new:', sorted((fb - fa).elements()) or 'none',
                  '| folders gone:', sorted((fa - fb).elements()) or 'none')
        for e in pin_errors:
            print('pin problem:', e)
    return not (lost or added or dupes or over or dock_changed or pin_errors)


def check(before_path, new_path, grid=DEFAULT_GRID, pins=()):
    """Offline: compare two layout files (see compare)."""
    ok = compare(plistlib.load(open(before_path, 'rb')), plistlib.load(open(new_path, 'rb')), grid, pins)
    print('OK: safe to push' if ok else 'NOT OK: fix the layout before pushing')
    return ok


def validate_pins(state, pins, grid=DEFAULT_GRID, check_widgets=True):
    """Problems with PINS against STATE: bad pages or slots, items not on their page, two pins on
    one slot or one item, a pinned widget that runs off the grid or over another pin, and pins
    that leave something (e.g. a widget) nowhere to go."""
    cols, rows = grid
    errors, seen_slot, seen_item, covered = [], set(), set(), {}
    for page, item, slot in pins:
        if not 1 <= page < len(state):
            errors.append(f'{page}:{item}:{slot}: page {page} is not a home screen page (1-{len(state) - 1})')
            continue
        if not 0 <= slot < cols * rows:
            errors.append(f'{page}:{item}:{slot}: slot outside 0-{cols * rows - 1} on a {cols}x{rows} grid')
        if (page, slot) in seen_slot:
            errors.append(f'{page}:{item}:{slot}: another pin already uses page {page} slot {slot}')
        if (page, item.strip('[]')) in seen_item:
            errors.append(f'{page}:{item}:{slot}: {item} is pinned twice')
        seen_slot.add((page, slot)); seen_item.add((page, item.strip('[]')))
        it = next((i for i in state[page] if key(i) == item.strip('[]')), None)
        if it is None:
            widget = next((i for i in state[page] if is_widget(i) and i.get('bundleIdentifier') == item), None)
            errors.append(f'{page}:{item}:{slot}: {item} is not on page {page}' + (
                f' (it is a widget: pin it by its ID, {page}:{widget.get("displayIdentifier")}:{slot})' if widget else ''))
            continue
        w, h = shape(it, cols)
        if not 0 <= slot < cols * rows:
            continue
        if not fits(slot, w, h, grid):
            errors.append(f'{page}:{item}:{slot}: a {it.get("gridSize")} widget at slot {slot} runs off the {cols}x{rows} grid')
            continue
        for x in cells(slot, w, h, cols):
            other = covered.get((page, x))
            if other and other[1] != slot:  # the same slot twice is reported above
                errors.append(f'{page}:{item}:{slot}: overlaps the pinned {other[0]} at slot {other[1]}')
                break
        for x in cells(slot, w, h, cols):
            covered.setdefault((page, x), (item, slot))
    if not errors and check_widgets:
        for page in {p for p, _, _ in pins}:
            page_pins = {i.strip('[]'): s for p, i, s in pins if p == page}
            placed = positions(state[page], page_pins, grid)
            missing = [name(i) for i in state[page] if name(i) not in placed]
            if missing:
                errors.append(f'page {page}: with these pins, nowhere left for {missing} (a pin under a widget?)')
            natural = positions(state[page], {}, grid)
            for it in state[page]:
                if not is_widget(it) or name(it) not in placed:
                    continue
                r, c = divmod(placed[name(it)], cols)
                if not aligned(placed[name(it)], cols):
                    errors.append(f'page {page}: the widget {name(it)} would start on row {r + 1}'
                                  + (f', column {c + 1}' if c % 2 else '') + ', but iOS starts widgets only on '
                                  'rows 1, 3, 5 (columns 1 or 3) and would move it: list it first, or after '
                                  'whole pairs of rows, or pin it to such a slot')
                    continue
                if key(it) not in page_pins and placed[name(it)] != natural.get(name(it)):
                    errors.append(f'page {page}: a pin sits where the widget {name(it)} goes (slot '
                                  f'{natural.get(name(it))}), which would push it to slot {placed[name(it)]}')
    return errors


def with_pins(state, pins, grid=DEFAULT_GRID):
    """Wrap a service-format layout in the on-disk shape with fixed slots for PINS.

    pins: list of (page, item, slot), item being a bundle ID, a folder name or a widget's
    displayIdentifier; page 1 is the first home screen page.
    """
    cols, rows = grid
    state = copy.deepcopy(state)
    pages = state[1:]
    page_ids = [str(uuid.uuid4()).upper() for _ in pages]
    fixed = defaultdict(dict)
    # Order-dependent checks (widgets) ran on the original order in compare(); STATE here may be
    # reordered for verification, so only the order-free checks repeat.
    errors = validate_pins(state, pins, grid, check_widgets=False)
    if errors:
        sys.exit('refusing pins:\n  ' + '\n  '.join(errors))
    for page, item, slot in pins:
        app = next((it for it in pages[page - 1] if it.get('bundleIdentifier') == item and not is_widget(it)), None)
        widget = next((it for it in pages[page - 1] if is_widget(it) and it.get('displayIdentifier') == item), None)
        folder = next((it for it in pages[page - 1] if it.get('iconLists') is not None
                       and 'bundleIdentifier' not in it and it.get('displayName') == item.strip('[]')), None)
        if app or widget:
            # SpringBoard keys a widget pin by the widget's displayIdentifier (its bundle ID is ignored).
            fixed[page_ids[page - 1]][item] = slot
        elif folder:
            # SpringBoard keys folder pins as "folder:<uniqueIdentifier>" and keeps an ID we supply.
            folder['uniqueIdentifier'] = str(uuid.uuid4()).upper()
            folder['listUniqueIdentifiers'] = [str(uuid.uuid4()).upper() for _ in folder['iconLists']]
            fixed[page_ids[page - 1]][f"folder:{folder['uniqueIdentifier']}"] = slot
        else:
            sys.exit(f'--pin: no app, folder or widget named {item} on page {page}')
    return {
        'buttonBar': state[0],
        'iconLists': pages,
        'listUniqueIdentifiers': page_ids,
        'listMetadata': {pid: {'fixedLocationsGridColumns': cols, 'fixedLocationsGridRows': rows,
                               'fixedLocations': f} for pid, f in fixed.items()},
    }


def with_widget_pins(state, pins, grid=DEFAULT_GRID):
    """PINS plus a pin for every unpinned widget on a page that has pins, at the slot the layout
    gives it (see positions). Left unpinned, a widget can land below the unpinned icons instead
    (seen on iOS 27.0.1, with no rule we could predict), so these pins leave SpringBoard no choice."""
    extra = []
    for page in sorted({p for p, _, _ in pins}):
        page_pins = {i.strip('[]'): s for p, i, s in pins if p == page}
        at = positions(state[page], page_pins, grid)
        extra += [(page, key(it), at[name(it)]) for it in state[page]
                  if is_widget(it) and key(it) not in page_pins and name(it) in at]
    return list(pins) + extra


def pinned_first(state, pins):
    """Put each page's pinned items first, in reverse slot order, so the readback can prove the pins
    even on a page where everything is pinned (see verify)."""
    state = copy.deepcopy(state)
    for page in {p for p, _, _ in pins}:
        slot = {item.strip('[]'): s for p, item, s in pins if p == page}
        items = state[page]
        pinned = sorted((i for i in items if key(i) in slot), key=lambda i: -slot[key(i)])
        state[page] = pinned + [i for i in items if key(i) not in slot]
    return state


def expected_order(items, page_pins, grid=DEFAULT_GRID):
    """Item names in slot order, which is how the service lists a page (see positions)."""
    at = positions(items, page_pins, grid)
    return sorted(at, key=at.get)


def positions(items, page_pins, grid=DEFAULT_GRID):
    """Simulate SpringBoard: pinned items take their slots (a widget every cell it covers, from its
    top-left slot), the rest fill the first free space in list order. Returns {item name: slot};
    an item that doesn't fit is left out. Matches the phone when every widget on a pinned page is
    pinned too (with_widget_pins); an unpinned widget may land elsewhere."""
    cols, rows = grid
    free = [True] * (cols * rows)
    at = {}
    for it in items:
        if key(it) in page_pins:
            s = at[name(it)] = page_pins[key(it)]
            for x in cells(s, *shape(it, cols), cols):
                if x < cols * rows:
                    free[x] = False
    for it in items:
        if key(it) in page_pins:
            continue
        w, h = shape(it, cols)
        for s in range(cols * rows):
            if fits(s, w, h, grid) and all(free[x] for x in cells(s, w, h, cols)):
                for x in cells(s, w, h, cols):
                    free[x] = False
                at[name(it)] = s
                break
    return at


def verify(sent, live, pins, grid=DEFAULT_GRID, proven=None):
    """Readback is in slot order. Pinned items were sent first, so a page that reads back as the
    simulated slot order proves its pins; one that reads back as sent means they were ignored.
    PROVEN, if given, collects 'app', 'folder' and/or 'widget' for pins on CONFIRMED pages only."""
    ok = True
    for page in sorted({p for p, _, _ in pins}):
        page_pins = {item.strip('[]'): slot for p, item, slot in pins if p == page}
        want = expected_order(sent[page], page_pins, grid)
        got, as_sent = [name(i) for i in live[page]], [name(i) for i in sent[page]]
        if want == as_sent:
            print(f'pins page {page}: not provable from order (pins already in list order); check the phone')
        elif got == want:
            print(f'pins page {page}: CONFIRMED ({len(page_pins)} pinned items landed in their slots)')
            if proven is not None:
                for it in sent[page]:
                    if key(it) in page_pins:
                        proven.add('widget' if is_widget(it) else 'app' if it.get('bundleIdentifier') else 'folder')
        else:
            ok = False
            print(f'pins page {page}: FAILED, read back {"as sent (pins ignored)" if got == as_sent else "in an unexpected order"}')
    return ok


def parse_pins(args):
    pins = []
    for a in args:
        try:
            page, rest = a.split(':', 1)
            item, slot = rest.rsplit(':', 1)  # folder names may contain colons
            pins.append((int(page), item, int(slot)))
        except ValueError:
            sys.exit(f'bad pin {a!r}: expected PAGE:ITEM:SLOT, e.g. 1:com.example.app:23 or 3:Travel:4')
    return pins


def read_pins_file(path):
    try:
        lines = open(path).read().splitlines()
    except OSError as e:
        sys.exit(f'cannot read pins file {path}: {e.strerror}')
    return [l.split('#')[0].strip() for l in lines if l.split('#')[0].strip()]


def _hs():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import homescreen  # needs pymobiledevice3; imported only when talking to the phone
    except ImportError:
        sys.exit('pymobiledevice3 is not installed for this Python: run this with "$D/pmd/bin/python" '
                 '(see the setup in SKILL.md)')
    return homescreen


async def phone():
    """Connect, and return (springboard service, device info)."""
    hs = _hs()
    ld, sb = await hs.connect()
    return sb, await hs.device_info(ld, sb)


def names(state):
    return [[name(i) for i in page] for page in state]


async def go(sent, sb=None):
    """Write SENT, then read back until the layout stops changing (up to ~10 s)."""
    hs = _hs()
    if sb is None:
        sb = await hs.service()
    await hs.maybe(sb.set_icon_state(sent))
    last = None
    for _ in range(10):
        await asyncio.sleep(1)
        live = await hs.maybe(sb.get_icon_state(format_version='2'))
        if last is not None and names(live) == names(last):
            return live
        last = live
    return last


def new_file(path):
    """Refuse to overwrite: a retry must never replace an earlier snapshot."""
    if os.path.exists(path):
        sys.exit(f'refusing to overwrite {path}: choose a new name')
    return path


def main(argv):
    import argparse, datetime
    ap = argparse.ArgumentParser(prog='push.py', description='Write a layout to the phone and verify it.',
                                 allow_abbrev=False)
    ap.add_argument('sent', help='the layout to write (built from a fresh homescreen.py dump)')
    ap.add_argument('after', help='where to save the layout read back after the write (must not exist)')
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument('--pins', metavar='FILE', help='pins file (PAGE:ITEM:SLOT lines); the usual choice')
    how.add_argument('--pin', action='append', metavar='PAGE:ITEM:SLOT', help='a single pin (repeatable)')
    how.add_argument('--no-pins', action='store_true', help='write with no pins: every page packs to the left')
    ap.add_argument('--untested-ios-ok', action='store_true',
                    help='allow pins on an iOS version not yet confirmed (for the control pin test)')
    a = ap.parse_args(argv)

    sent = plistlib.load(open(a.sent, 'rb'))
    specs = list(a.pin or [])
    if a.pins:
        specs += read_pins_file(a.pins)
    pins = parse_pins(specs)
    if (a.pins or a.pin) and not pins:
        sys.exit(f'no pins found in {a.pins}: refusing, because writing with no pins packs every page. '
                 'Use --no-pins if that is really what you want.')
    new_file(a.after)
    base = a.after.rsplit('.plist', 1)[0]
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    snap = new_file(f'{base}.autosave-before-{stamp}.plist')
    last_pins = os.path.join(os.path.dirname(os.path.abspath(a.after)), 'last-write.pins.txt')
    hs = _hs()  # only now: every offline check above runs without pymobiledevice3

    async def run():
        sb, info = await phone()
        grid = (info['columns'], info['rows'])
        print('phone:', hs.describe(info))
        if info['class'] != 'iPhone':
            sys.exit(f"refusing to write: this is a {info['class']}, and the skill supports iPhone only")
        if pins and not hs.ios_tested(info['ios']) and not a.untested_ios_ok:
            sys.exit(f"refusing to write pins on iOS {info['ios']}, which hasn't passed the pin tests: run the "
                     "control pin tests in references/troubleshooting.md with --untested-ios-ok")

        # Compare with what's on the phone right now: refuse if apps came or went since the snapshot.
        before = await hs.maybe(sb.get_icon_state(format_version='2'))
        if not compare(before, sent, grid, pins, quiet=True):
            print('the layout to send differs from the phone (or is invalid):')
            compare(before, sent, grid, pins)
            sys.exit('refusing to write: dump the layout again and rebuild from that')

        all_pins = with_widget_pins(sent, pins, grid) if pins else pins
        for page, item, slot in all_pins[len(pins):]:
            print(f'pinning widget {item} at page {page} slot {slot}, where the layout puts it')
        to_send = pinned_first(sent, all_pins) if pins else sent
        payload = with_pins(to_send, all_pins, grid) if pins else to_send

        # Safety net: snapshot the live layout, and the pins of the last write, before changing anything.
        plistlib.dump(before, open(snap, 'wb'))
        snap_pins = None
        if os.path.exists(last_pins):
            snap_pins = f'{base}.autosave-before-{stamp}.pins.txt'
            shutil.copy(last_pins, snap_pins)
        # Flushed: if this run is stopped while writing, the caller must still see where the snapshot is.
        print(f'saved the layout from before this write: {snap}', flush=True)
        print(f'  to restore: "{sys.executable}" -B {os.path.abspath(__file__)} {snap} <new name>.plist '
              + (f'--pins {snap_pins}' if snap_pins else '--no-pins')
              + ('' if snap_pins else '  (no record of earlier pins here, so gaps would pack)'), flush=True)

        live = await go(payload, sb)
        return to_send, live, grid, info, all_pins

    to_send, live, grid, info, all_pins = asyncio.run(run())
    plistlib.dump(live, open(a.after, 'wb'))
    sa, sl = ids(to_send, Counter()), ids(live, Counter())
    lost, added = list((sa - sl).elements()), list((sl - sa).elements())
    print('items sent/live:', sum(sa.values()), sum(sl.values()), '| lost:', lost, '| added:', added)
    print('pages sent/live:', len(to_send) - 1, len(live) - 1)
    ok = not (lost or added)
    proven = set()
    if pins:
        ok = verify(to_send, live, all_pins, grid, proven) and ok
    if ok:
        # Record the pins now in effect, so the next write's snapshot can restore them.
        open(f'{base}.pins.txt', 'w').write('\n'.join(specs) + '\n')
        open(last_pins, 'w').write('\n'.join(specs) + '\n')
    if ok and a.untested_ios_ok and proven and not hs.ios_tested(info['ios']):
        hs.record_ios_pass(info['ios'], proven)
        done = hs.ios_kinds_passed(info['ios'])
        print(f"recorded iOS {info['ios']} pin test passes: {', '.join(sorted(done))}"
              + ('' if {'app', 'folder'} <= done else ' (run the other pin test too before real writes)'))
    if not ok:
        sys.exit('the write did not come back as sent: see references/troubleshooting.md')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--check']:
        import argparse
        ap = argparse.ArgumentParser(prog='push.py --check', allow_abbrev=False)
        ap.add_argument('before'); ap.add_argument('new')
        ap.add_argument('--grid', default='4x6', help='COLSxROWS, from homescreen.py show')
        ap.add_argument('--pins', metavar='FILE', help='also validate this pins file against NEW')
        c = ap.parse_args(sys.argv[2:])
        try:
            grid = tuple(int(x) for x in c.grid.lower().split('x'))
            assert len(grid) == 2
        except (ValueError, AssertionError):
            sys.exit('--grid needs COLSxROWS, e.g. --grid 4x6')
        pins = parse_pins(read_pins_file(c.pins)) if c.pins else ()
        sys.exit(0 if check(c.before, c.new, grid, pins) else 1)
    main(sys.argv[1:])
