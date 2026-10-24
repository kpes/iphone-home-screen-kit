"""The MCP server's tools, without the MCP layer (server.py adds that).

Standard library only, so the offline tests run anywhere. Everything that talks to the phone, or
that the skill's scripts already do, runs those scripts as subprocesses with the arguments their
command line takes, so this server makes exactly the checks the skill makes; above all, every write
goes through push.py (live-layout compare, iPhone guard, iOS gate, snapshot with pins, readback).

On top of push.py, a write needs a confirmation token from check_layout: the token is bound to the
exact files and pins that passed the offline check, is used once, and expires after TOKEN_TTL.

Files: every layout lives in <data folder>/layouts, and tools take bare file names, never paths.
New files get dated names and nothing is ever overwritten.
"""
import contextlib, datetime, hashlib, io, json, os, plistlib, re, secrets, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, '.claude', 'skills', 'iphone-home-screen')
SCRIPTS = os.path.join(SKILL, 'scripts')
sys.path.insert(0, SCRIPTS)
import push  # noqa: E402  (pure functions; imports pymobiledevice3 only when talking to the phone)

TOKEN_TTL = 10 * 60  # seconds a confirmation token stays valid
PENDING = {}         # token -> what check_layout approved
SESSION = {}         # what the last show_layout learned: 'grid' ("4x6"), 'phone'
PHONE = threading.Lock()  # one phone, one operation at a time


class Refused(Exception):
    """A tool refused, or a script failed: the message says why and what to do."""


def home_dir():
    # Read on every call, not at import, so a changed setting takes effect without a restart.
    return os.path.expanduser(os.environ.get('IPHONE_HOME_SCREEN_DIR') or '~/iphone-home-screen')


def layouts_dir():
    d = os.path.join(home_dir(), 'layouts')
    os.makedirs(d, exist_ok=True)
    return d


def stamp():
    return datetime.datetime.now().strftime('%Y-%m-%d-%H%M%S')


def resolve(name, suffix='.plist'):
    """A file in the layouts folder, by bare name. Paths, '..' and links out of the folder are refused."""
    if (not isinstance(name, str) or not name.endswith(suffix) or os.path.basename(name) != name
            or name.startswith('.') or '\0' in name):
        raise Refused(f'{name!r}: give a file name from the layouts folder ending in {suffix} '
                      '(as list_snapshots or an earlier tool printed it), not a path')
    d = os.path.realpath(layouts_dir())
    path = os.path.realpath(os.path.join(d, name))
    if os.path.dirname(path) != d:
        raise Refused(f'{name}: not in the layouts folder {d}')
    if not os.path.isfile(path):
        raise Refused(f'no file named {name} in {d}: see list_snapshots')
    return path


def new_path(label, suffix='.plist'):
    """A new dated file name in the layouts folder that doesn't exist yet."""
    base = os.path.join(layouts_dir(), f'{stamp()}-{label}')
    path, n = base + suffix, 2
    while os.path.exists(path):
        path, n = f'{base}-{n}{suffix}', n + 1
    return path


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_script(script, *args, timeout=120):
    """Run one of the skill's scripts; returns (exit code, its output). stdin is closed, because the
    server's own stdin and stdout carry the MCP protocol."""
    env = dict(os.environ, IPHONE_HOME_SCREEN_DIR=home_dir())
    try:
        r = subprocess.run([sys.executable, '-I', '-B', os.path.join(SCRIPTS, script), *args],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise Refused(f'{script} took longer than {timeout} s and was stopped. Is the iPhone connected, '
                      'unlocked and trusted?')
    return r.returncode, (r.stdout + ('\n' + r.stderr if r.stderr.strip() else '')).strip()


@contextlib.contextmanager
def phone():
    if not PHONE.acquire(timeout=1):
        raise Refused('another phone operation is still running: wait for it to finish, then try again')
    try:
        yield
    finally:
        PHONE.release()


def quiet(fn, *args):
    """Call a script function that prints or sys.exit()s; returns (result, what it printed)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            return fn(*args), out.getvalue()
        except SystemExit as e:
            raise Refused(e.code if isinstance(e.code, str) else out.getvalue().strip() or 'refused')


def load(path):
    with open(path, 'rb') as f:
        return plistlib.load(f)


def grid_arg(grid):
    g = grid or SESSION.get('grid') or '4x6'
    if not re.fullmatch(r'\d+x\d+', g):
        raise Refused(f'grid {g!r}: expected COLUMNSxROWS, e.g. 4x6 (show_layout prints the phone\'s)')
    return g


# --- Showing layouts ---------------------------------------------------------------------------

def is_folder(it):
    return it.get('iconLists') is not None and 'bundleIdentifier' not in it


def item_text(it):
    if it.get('elementType') == 'widget':
        return f"widget {it.get('bundleIdentifier') or it.get('displayIdentifier')} ({it.get('gridSize', '?')})"
    if is_folder(it):
        apps = [push.name(a) for page in it['iconLists'] for a in page]
        return f"[{it.get('displayName')}] folder of {len(apps)}: " + ', '.join(apps)
    label = it.get('displayName')
    b = it.get('bundleIdentifier')
    return f'{b} ({label})' if b and label and label != b else push.name(it)


def layout_text(state, pages=None):
    lines = ['dock: ' + ', '.join(item_text(i) for i in state[0])]
    for p, page in enumerate(state[1:], 1):
        if pages is None or p in pages:
            lines.append(f'page {p} ({len(page)} items, in list order):')
            lines += [f'  {n}. {item_text(i)}' for n, i in enumerate(page, 1)]
    return '\n'.join(lines)


def pins_in_effect():
    """The pins of the last successful write (push.py keeps them), else the user's pins.txt."""
    for path in (os.path.join(layouts_dir(), 'last-write.pins.txt'), os.path.join(home_dir(), 'pins.txt')):
        if os.path.exists(path):
            with open(path) as f:
                specs = [l.split('#')[0].strip() for l in f if l.split('#')[0].strip()]
            return specs, path
    return [], None


def show_layout():
    """Read the phone's layout, save it as a new snapshot, and describe it."""
    with phone():
        code, info = run_script('homescreen.py', 'show')
        if code != 0:
            raise Refused(info + '\n\nCould not read the phone. It must be connected by USB, unlocked and '
                          'trusted ("Trust This Computer"); only one iPhone at a time.')
        snap = new_path('before')
        code, out = run_script('homescreen.py', 'dump', snap)
        if code != 0:
            raise Refused(out)
    m = re.search(r'grid (\d+) columns x (\d+) rows', info)
    if m:
        SESSION['grid'] = f'{m[1]}x{m[2]}'
    SESSION['phone'] = info.splitlines()[0] if info else ''
    specs, src = pins_in_effect()
    pins = ('\n'.join(specs) + f'\n(from {src})') if specs else 'none recorded'
    return (f"{SESSION['phone']}\n\nSaved this layout as {os.path.basename(snap)} (use it as the base for "
            f"build_page and check_layout).\n\n{layout_text(load(snap))}\n\nPins in effect (PAGE:ITEM:SLOT):\n{pins}\n\n"
            'Pages list items in slot order; blank spaces are not listed, so use the pins to see where gaps are. '
            'Pass the pins you want to keep on every write, or those gaps close.')


def list_snapshots(limit=30):
    d = layouts_dir()
    files = sorted((f for f in os.listdir(d) if f.endswith('.plist') and not f.startswith('.')),
                   key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
    if not files:
        return f'no layouts saved yet in {d}: run show_layout'
    lines = [f'Layouts in {d}, newest first:']
    for f in files[:limit]:
        pins = f[:-len('.plist')] + '.pins.txt'
        when = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(d, f))).strftime('%Y-%m-%d %H:%M')
        lines.append(f'  {when}  {f}' + (f'   (pins: {pins})' if os.path.exists(os.path.join(d, pins)) else ''))
    if len(files) > limit:
        lines.append(f'  ... and {len(files) - limit} older')
    lines.append('"*-after.plist" = read back after a write; "*.autosave-before-*" = the layout just before '
                 'that write (restore_snapshot undoes a write with it); "*-before.plist" = from show_layout.')
    return '\n'.join(lines)


def show_snapshot(name, pages=None):
    """Describe a saved layout (pages: list of page numbers, default all)."""
    return f'{name}:\n' + layout_text(load(resolve(name)), set(pages) if pages else None)


# --- Building layouts (offline) ----------------------------------------------------------------

def build_page(base, page, items, grid=None):
    """arrange.py: set PAGE of BASE to exactly ITEMS (bundle IDs or folder names), into a new file."""
    src = resolve(base)
    if not items:
        raise Refused('items is empty: list the page\'s apps and folders in screen order')
    out = new_path(f'page{int(page)}')
    code, text = run_script('arrange.py', src, out, str(int(page)), *items, '--grid', grid_arg(grid))
    if code != 0:
        raise Refused(text)
    return f'{text}\n\nSaved as {os.path.basename(out)}. Next: more build_page calls on it, or check_layout.'


def make_folder(base, name, apps, page):
    """Create a folder NAME holding APPS (taken from wherever they are, including other folders) at
    the end of PAGE, into a new file. See "Creating folders" in references/commands.md."""
    src = resolve(base)
    st = load(src)
    page = int(page)
    if not 1 <= page < len(st):
        raise Refused(f'page {page}: use 1-{len(st) - 1} (0 is the dock, which is never edited)')
    if not name or not apps:
        raise Refused('give the folder a name and at least one app')
    if any(is_folder(it) and it.get('displayName') == name for p in st[1:] for it in p):
        raise Refused(f'a folder named {name} already exists: use build_page to move it, or pick another name')
    want, found = set(apps), {}

    def take(lst):
        out = []
        for it in lst:
            if is_folder(it):
                it['iconLists'] = [l for l in (take(l) for l in it['iconLists']) if l]
                if not it['iconLists']:
                    continue
            elif it.get('bundleIdentifier') in want and it['bundleIdentifier'] not in found:
                found[it['bundleIdentifier']] = it
                continue
            out.append(it)
        return out

    st[1:] = [take(p) for p in st[1:]]
    missing = [a for a in apps if a not in found]
    if missing:
        raise Refused(f'not on the home screen (only in the App Library, or not installed?): {missing}')
    ordered = [found[a] for a in apps]
    st[page].append({'displayName': name, 'listType': 'folder',
                     'iconLists': [ordered[i:i + 9] for i in range(0, len(ordered), 9)]})
    st[1:] = [p for p in st[1:] if p]
    page = next(p for p in range(1, len(st)) if any(it.get('displayName') == name and is_folder(it) for it in st[p]))
    out = new_path('folder')
    with open(out, 'wb') as f:
        plistlib.dump(st, f)
    return (f'Folder [{name}] with {len(apps)} apps added at the end of page {page}. '
            f'Saved as {os.path.basename(out)}. Next: build_page to place it, or check_layout.')


# --- Checking and writing ----------------------------------------------------------------------

def pin_specs(pins, no_pins):
    specs = [p.strip() for p in (pins or []) if p and p.strip()]
    if any('\n' in p for p in specs):
        raise Refused('one pin per list entry, as PAGE:ITEM:SLOT')
    if specs and no_pins:
        raise Refused('give pins or no_pins=true, not both')
    if not specs and not no_pins:
        raise Refused('no pins given. Writing without pins closes every gap on every page. Pass the pins to keep '
                      '(show_layout lists the ones in effect), or no_pins=true if packing is really wanted.')
    quiet(push.parse_pins, specs)  # refuses malformed pins with push.py's own message
    return specs


def check_layout(base, new, pins=None, no_pins=False, untested_ios_ok=False, grid=None):
    """push.py --check BASE NEW: on success, return a preview and a one-time confirmation token."""
    b, n = resolve(base), resolve(new)
    specs = pin_specs(pins, no_pins)
    g = grid_arg(grid)
    pins_file = new_path('check', '.pins.txt') if specs else None
    try:
        if pins_file:
            with open(pins_file, 'w') as f:
                f.write('\n'.join(specs) + '\n')
        code, out = run_script('push.py', '--check', b, n, '--grid', g, *(['--pins', pins_file] if specs else []))
    finally:
        if pins_file and os.path.exists(pins_file):
            os.remove(pins_file)
    if code != 0:
        raise Refused(out + '\n\nNot safe to write: fix the layout (or pins) and check again. No token issued.')
    before, after = load(b), load(n)
    changed = [p for p in range(1, len(after)) if p >= len(before) or push.names([after[p]]) != push.names([before[p]])]
    token = secrets.token_hex(4)
    for t in [t for t, v in PENDING.items() if v['expires'] < time.time()]:
        del PENDING[t]
    PENDING[token] = {'base': b, 'new': n, 'base_sha': sha(b), 'new_sha': sha(n), 'pins': specs,
                      'untested_ios_ok': bool(untested_ios_ok), 'expires': time.time() + TOKEN_TTL}
    pages_after = len(after) - 1
    preview = layout_text(after, set(changed)) if changed else '(no page changes; pins only)'
    return (f'{out}\n\nPages that change ({pages_after} pages in all):\n{preview}\n\n'
            f"Pins: {', '.join(specs) if specs else 'none (every page packs to the left)'}"
            + ('\nUntested iOS allowed for this write (pin test).' if untested_ios_ok else '') +
            f'\n\nConfirmation token: {token} (valid {TOKEN_TTL // 60} minutes, for this exact layout and these pins).\n'
            'Show the user these pages and pins and ask for a clear yes. Only then call write_layout with this token.')


def write_layout(confirm_token):
    """push.py NEW AFTER with the pins check_layout approved; it reads back and verifies."""
    p = PENDING.pop((confirm_token or '').strip(), None)
    if not p:
        raise Refused('unknown or already used confirmation token: run check_layout first')
    if time.time() > p['expires']:
        raise Refused('the confirmation token expired: run check_layout again (and confirm with the user)')
    for k in ('base', 'new'):
        if not os.path.exists(p[k]) or sha(p[k]) != p[k + '_sha']:
            raise Refused(f'{os.path.basename(p[k])} changed since check_layout: run check_layout again')
    after = new_path('after')
    args = [p['new'], after] + ([a for s in p['pins'] for a in ('--pin', s)] if p['pins'] else ['--no-pins'])
    if p['untested_ios_ok']:
        args.append('--untested-ios-ok')
    with phone():
        code, out = run_script('push.py', *args, timeout=180)
    m = re.search(r'saved the layout from before this write: (\S+\.plist)', out)
    undo = (f'\n\nTo undo this write: restore_snapshot with {os.path.basename(m[1])}.' if m else '')
    if code != 0:
        raise Refused(out + undo + '\n\nThe write was refused or did not come back as sent. Read the lines above; '
                      'read_guide("troubleshooting") explains each message.')
    return out + f'\n\nRead back and saved as {os.path.basename(after)}.' + undo


def restore_snapshot(snapshot, pins_file=None, untested_ios_ok=False):
    """Prepare putting SNAPSHOT back on the phone, with its pins: a check_layout that returns a token."""
    s = resolve(snapshot)
    if pins_file:
        pf = resolve(pins_file, '.txt')
    else:
        pf = s[:-len('.plist')] + '.pins.txt'
    specs = quiet(push.read_pins_file, pf)[0] if os.path.exists(pf) else []
    note = (f'Restoring with the pins in {os.path.basename(pf)}.' if specs else
            f'No pins file for {snapshot}, so this restore has no pins: pages pack to the left and any gaps close. '
            'If the user had gaps, pass the matching pins_file (see list_snapshots).')
    return note + '\n\n' + check_layout(snapshot, snapshot, specs, not specs, untested_ios_ok)


# --- Usage ranking -----------------------------------------------------------------------------

def list_usage_devices():
    code, out = run_script('rank.py', '--devices', timeout=300)
    return out or ('no synced usage data found: needs Screen Time "Share Across Devices" on the iPhone and '
                   'Full Disk Access for the Claude app')


def archive_usage():
    code, out = run_script('rank.py', '--archive', timeout=300)
    if code != 0:
        raise Refused(out)
    return out


def rank_apps(since=None, until=None, device=None, skip=None, lookup=False, top=20):
    args = []
    for flag, d in (('--since', since), ('--until', until)):
        if d:
            try:
                datetime.date.fromisoformat(d)
            except ValueError:
                raise Refused(f'{flag} {d!r}: expected YYYY-MM-DD')
            args += [flag, d]
    if device:
        args += ['--device', device]
    if skip:
        args += ['--skip', *skip]
    if lookup:
        args.append('--lookup')
    data = os.path.join(home_dir(), 'data')
    os.makedirs(data, exist_ok=True)
    out = os.path.join(data, f'ranking-{datetime.date.today()}.csv')
    if os.path.exists(out):
        out = os.path.join(data, f'ranking-{stamp()}.csv')
    code, text = run_script('rank.py', out, '--top', str(int(top)), *args, timeout=300)
    if code != 0:
        raise Refused(text)
    return text


# --- Settings and guides -----------------------------------------------------------------------

CONFIG_KEYS = {'devices': dict, 'dock': list, 'exclude': list, 'exclude_genres': list, 'store_country': str}


def read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def get_settings():
    d = home_dir()
    specs, src = pins_in_effect()
    parts = [f'Data folder: {d}']
    for label, path in (('config.json (usage ranking settings)', 'config.json'),
                        ("layout.md (the user's chosen layout and rules)", 'layout.md'),
                        ('tested-ios.txt (iOS versions that passed the pin tests here)', 'tested-ios.txt')):
        text = read_text(os.path.join(d, path))
        parts.append(f'--- {label}:\n' + (text.strip() if text and text.strip() else '(none yet)'))
    parts.append('--- pins in effect:\n' + ('\n'.join(specs) + f'\n(from {src})' if specs else '(none recorded)'))
    return '\n\n'.join(parts)


def save_settings(config=None, layout_notes=None):
    """Write config.json and/or layout.md in the data folder; the previous version is kept as *.previous."""
    if config is None and layout_notes is None:
        raise Refused('nothing to save: pass config and/or layout_notes')
    d = home_dir()
    os.makedirs(d, exist_ok=True)
    saved = []
    if config is not None:
        if not isinstance(config, dict):
            raise Refused('config must be an object')
        bad = [k for k in config if k not in CONFIG_KEYS or not isinstance(config[k], CONFIG_KEYS[k])]
        if bad:
            raise Refused(f'unknown or wrongly typed config keys {bad}: allowed '
                          + ', '.join(f'{k} ({t.__name__})' for k, t in CONFIG_KEYS.items()))
        saved.append(_replace(os.path.join(d, 'config.json'), json.dumps(config, indent=2) + '\n'))
    if layout_notes is not None:
        saved.append(_replace(os.path.join(d, 'layout.md'), layout_notes.rstrip() + '\n'))
    return 'Saved ' + ', '.join(saved) + ' (the previous version, if any, is kept as *.previous).'


def _replace(path, text):
    if os.path.exists(path):
        os.replace(path, path + '.previous')
    with open(path, 'w') as f:
        f.write(text)
    return path


GUIDES = {'how-it-works': 'how-it-works.md', 'troubleshooting': 'troubleshooting.md', 'commands': 'commands.md'}
COMMAND_MAP = ('These references were written for the skill\'s command-line scripts. Here each command is a tool: '
               'homescreen.py show/dump = show_layout; arrange.py = build_page; push.py --check = check_layout; '
               'push.py = write_layout (after check_layout); restoring a dump = restore_snapshot; rank.py = rank_apps, '
               'list_usage_devices, archive_usage; "Creating folders" = make_folder; config.json and layout.md = '
               'get_settings / save_settings. Steps that need a shell (the layout-file backup, the syslog) are '
               'for Claude Code; tell the user.\n\n')


def read_guide(topic):
    if topic not in GUIDES:
        raise Refused(f'topic must be one of {sorted(GUIDES)}')
    return COMMAND_MAP + read_text(os.path.join(SKILL, 'references', GUIDES[topic]))
