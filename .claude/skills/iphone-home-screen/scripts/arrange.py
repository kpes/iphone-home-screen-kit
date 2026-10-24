"""Set one page to an exact list of items, pulling each from wherever it is now.

  python3 -I -B scripts/arrange.py BEFORE OUT PAGE ITEM...

PAGE 1 is the first home screen page (0 is the dock). ITEM is a bundle ID or a folder's
name, with or without the brackets `homescreen.py show` prints ("Utilities" or
"[Utilities]"). A widget can be given as `show` prints it (bundle ID#ID), by its ID, or by
its bundle ID. An app inside a folder is taken out of it, even when that folder is
also in the list. Items displaced from PAGE go to the front of the next page. Emptied
folders and pages are dropped. Stops if the page would hold more than 24 slots.
"""
import os, plistlib, sys

SLOTS = 24  # 4 columns x 6 rows; --grid COLSxROWS overrides (e.g. Display Zoom)
WIDGET_SLOTS = {'small': 4, 'medium': 8, 'large': 16, 'extraLarge': 16}


def key(it):
    return it.get('bundleIdentifier') or it.get('displayName')


def names(it):
    """Every way ITEM can be given: a widget also by `show`'s bundle ID#ID, or by its ID alone."""
    if it.get('elementType') == 'widget':
        ident = it.get('displayIdentifier')
        return [f"{it.get('bundleIdentifier')}#{ident}", ident, key(it)]
    return [key(it)]


def is_folder(it):
    return it.get('iconLists') is not None and 'bundleIdentifier' not in it


def slots(it):
    return WIDGET_SLOTS.get(it.get('gridSize'), 1) if it.get('elementType') == 'widget' else 1


def main(src, dst, page, *items):
    page = int(page)
    if os.path.exists(dst):
        sys.exit(f'refusing to overwrite {dst}: choose a new name')
    # One argument may hold several items on separate lines ("$TOP" from awk in zsh).
    items = [line.strip() for arg in items for line in arg.splitlines() if line.strip()]
    items = [i[1:-1] if i.startswith('[') and i.endswith(']') else i for i in items]
    state = plistlib.load(open(src, 'rb'))
    if not 1 <= page <= len(state):
        sys.exit(f'page {page}: use 1-{len(state) - 1} for an existing page, or {len(state)} for a new last page '
                 '(0 is the dock, which the scripts never edit)')
    if page == len(state):
        state.append([])
    wanted, pulled = set(items), {}

    def strip(lst):
        out = []
        for it in lst:
            if is_folder(it):
                # Look inside first, so a listed app can leave a folder that is itself listed.
                it['iconLists'] = [l for l in (strip(l) for l in it['iconLists']) if l]
            k = next((n for n in names(it) if n in wanted and n not in pulled), None)
            if k is not None:
                pulled[k] = it
                continue
            if is_folder(it) and not it['iconLists']:
                continue
            out.append(it)
        return out

    state[1:] = [strip(p) for p in state[1:]]
    missing = [i for i in items if i not in pulled]
    if missing:
        sys.exit(f'not found: {missing}')
    used = sum(slots(pulled[i]) for i in items)
    if used > SLOTS:
        sys.exit(f'page {page} would need {used} slots; only {SLOTS} fit (grid from `homescreen.py show`; pass --grid)')
    leftover = state[page]
    state[page] = [pulled[i] for i in items]
    if leftover:
        if page + 1 < len(state):
            state[page + 1] = leftover + state[page + 1]
        else:
            state.append(leftover)
    state[1:] = [p for p in state[1:] if p]
    plistlib.dump(state, open(dst, 'wb'))
    print(f'page {page} ({used}/{SLOTS} slots):', [key(i) for i in state[page]])
    print('displaced to next page:', [key(i) for i in leftover])
    print('page sizes:', [len(p) for p in state[1:]])


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--grid' in args:
        try:
            g = args[args.index('--grid') + 1]
            c, r = (int(x) for x in g.lower().split('x'))
        except (IndexError, ValueError):
            sys.exit('--grid needs COLSxROWS, e.g. --grid 4x6')
        SLOTS = c * r
        del args[args.index('--grid'):args.index('--grid') + 2]  # only the flag and its value
    main(*args)
