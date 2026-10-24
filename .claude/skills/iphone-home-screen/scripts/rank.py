"""Rank iPhone apps by a combined score of days used, opens and time.

  python3 -I -B scripts/rank.py OUT.csv [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--top N]
                                         [--device LABEL] [--skip BUNDLE_ID ...] [--lookup]
  python3 -I -B scripts/rank.py --devices      list synced devices, to find a phone's ID
  python3 -I -B scripts/rank.py --archive      copy the live usage files into <data folder>/data/raw/

Settings come from config.json in your data folder (template: assets/config.example.json):
which devices to read, dock apps, other apps to leave out, and excluded App Store genres.

Reads each device's App.InFocus events from the Mac's synced Biome store (needs Full Disk
Access) and from data/raw/<device-id>/, merging and de-duplicating them. Sessions are built
per device, so one phone never closes another's session; a session is capped at 4 hours.

Score = geometric mean of the app's rank by days used, by opens and by hours (lower is
better). Excluded apps are still written to OUT with an `excluded` reason, but get no rank.
Genres are cached in data/app-genres.json; --lookup fetches missing ones from the App Store
(it sends bundle IDs to Apple).
"""
import argparse, csv, datetime, glob, json, os, shutil, statistics, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import infocus as ic

# Each person's settings, usage archive and layouts live outside the skill, in one folder:
# $IPHONE_HOME_SCREEN_DIR if set, else ~/iphone-home-screen.
HOME_DIR = os.path.expanduser(os.environ.get('IPHONE_HOME_SCREEN_DIR') or '~/iphone-home-screen')
BIOME = os.path.expanduser('~/Library/Biome/streams/restricted/App.InFocus/remote')
RAW = os.path.join(HOME_DIR, 'data', 'raw')
GENRES = os.path.join(HOME_DIR, 'data', 'app-genres.json')
CONFIG = os.path.join(HOME_DIR, 'config.json')


def load_config():
    try:
        c = json.load(open(CONFIG))
    except OSError:
        c = {}
    return c


_cfg = load_config()
DEVICES = _cfg.get('devices', {})  # {device ID: label}; empty until set up (see --devices)
SESSION_CAP = 4 * 3600

# Not real apps: iOS screens and system UI that show up as "in focus".
SYSTEM = {
    'com.apple.InCallService', 'com.apple.SleepLockScreen', 'com.apple.purplebuddy', 'com.apple.webapp',
    'com.apple.springboard', 'com.apple.TCC', 'com.apple.CarPlaySplashScreen',
}
SYSTEM_SUFFIXES = ('control-center', 'today-view', 'CarPlaySplashScreen', 'TCC', 'Service')
DOCK = set(_cfg.get('dock', []))           # dock apps: they stay in the dock, so never ranked
OTHER = set(_cfg.get('exclude', []))       # anything else the user keeps out (Settings, a widget's app)
EXCLUDED_GENRES = set(_cfg.get('exclude_genres', ['Games']))
STORE_COUNTRY = _cfg.get('store_country', 'us')  # App Store region for genre lookups


def is_system(b):
    return (b in SYSTEM or b.startswith('com.apple.springboard')
            or (b.startswith('com.apple.') and b.endswith(SYSTEM_SUFFIXES)))


def load_genres():
    try:
        return json.load(open(GENRES))
    except OSError:
        return {}


def lookup_genres(ids, genres):
    """Fill in App Store genres for ids missing from the cache; Apple apps not in the store get 'Apple'."""
    todo = sorted(b for b in ids if b not in genres)
    for i in range(0, len(todo), 50):
        q = urllib.parse.urlencode({'bundleId': ','.join(todo[i:i + 50]), 'country': STORE_COUNTRY, 'entity': 'software'})
        for r in json.load(urllib.request.urlopen('https://itunes.apple.com/lookup?' + q, timeout=30))['results']:
            genres[r['bundleId']] = r.get('primaryGenreName')
        time.sleep(1)
    for b in todo:
        genres.setdefault(b, 'Apple' if b.startswith('com.apple.') else None)
    os.makedirs(os.path.dirname(GENRES), exist_ok=True)
    json.dump(genres, open(GENRES, 'w'), indent=1, sort_keys=True)
    return len(todo)


def device_dirs(dev):
    return [os.path.join(BIOME, dev), os.path.join(RAW, dev)]


def load_events(dirs):
    seen = set()
    for d in dirs:
        for p in glob.glob(os.path.join(d, '[0-9]*')):
            for r in ic.records(p):
                m = ic.parse_msg(r)
                if m and 4 in m and 6 in m:
                    seen.add((m[4], m[6].decode('utf-8', 'replace'), m.get(3, 0)))
    return sorted(seen)


def day(ts):
    return datetime.datetime.fromtimestamp(ts + ic.MAC_EPOCH).date()


def list_devices():
    """Every synced device with usage data, newest first, so a new phone is easy to spot."""
    rows = []
    for d in glob.glob(os.path.join(BIOME, '*')) + glob.glob(os.path.join(RAW, '*')):
        dev = os.path.basename(d)
        if any(r[0] == dev for r in rows):
            continue
        ev = load_events(device_dirs(dev))
        if ev:
            top = Counter(b for _, b, s in ev if s and not is_system(b)).most_common(3)
            rows.append((dev, day(ev[0][0]), day(ev[-1][0]), len(ev), ', '.join(b for b, _ in top)))
    for dev, first, last, n, top in sorted(rows, key=lambda r: r[2], reverse=True):
        print(f"{dev}  {DEVICES.get(dev, '(not in config)'):16}  {first} .. {last}  {n:6} events  top: {top}")


def archive():
    """Copy the live usage files for DEVICES into data/raw (run every few weeks; the Mac keeps ~4).

    Never overwrites: the Mac prunes old events from inside the same files it keeps appending to, so
    copying over an archived file would lose the days it no longer has. A changed file is saved
    beside the old copy instead; ranking merges and de-duplicates events from every copy."""
    import filecmp, time
    for dev, label in DEVICES.items():
        src, dst = os.path.join(BIOME, dev), os.path.join(RAW, dev)
        os.makedirs(dst, exist_ok=True)
        new = kept = same = 0
        for f in glob.glob(os.path.join(src, '[0-9]*')):
            target = os.path.join(dst, os.path.basename(f))
            if not os.path.exists(target):
                shutil.copy2(f, target)
                new += 1
            elif filecmp.cmp(f, target, shallow=False):
                same += 1
            else:
                stamp = time.strftime('%Y%m%dT%H%M%S', time.localtime(os.path.getmtime(f)))
                versioned = f'{target}.{stamp}'
                if not os.path.exists(versioned):
                    shutil.copy2(f, versioned)
                kept += 1
        print(f'{label}: {new} new, {kept} changed (saved alongside the old copies), {same} unchanged -> {dst}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?')
    ap.add_argument('--since', type=datetime.date.fromisoformat)
    ap.add_argument('--until', type=datetime.date.fromisoformat)
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--lookup', action='store_true', help='fetch missing App Store genres')
    ap.add_argument('--devices', action='store_true')
    ap.add_argument('--archive', action='store_true')
    ap.add_argument('--device', help="only this device: a label from config.json (e.g. 'My iPhone') or a device ID")
    ap.add_argument('--skip', nargs='+', default=[], metavar='BUNDLE_ID',
                    help='leave these out of the ranking (one-off spikes the user ruled out)')
    a = ap.parse_args()
    if a.devices:
        return list_devices()
    if not DEVICES:
        sys.exit(f'no devices configured: run --devices, then add your phone to "devices" in {CONFIG}')
    if a.archive:
        return archive()
    if not a.out:
        ap.error('OUT.csv is required')
    if not os.access(BIOME, os.R_OK):
        print(f'note: cannot read {BIOME} (Full Disk Access?); using data/raw only', file=sys.stderr)

    sessions = defaultdict(list)          # bundle -> [seconds]
    days = defaultdict(set)               # bundle -> {date}
    per_dev = defaultdict(lambda: defaultdict(int))  # bundle -> device -> opens
    all_days, available = set(), set()
    devices = {d: l for d, l in DEVICES.items() if not a.device or a.device in (d, l)}
    if not devices:
        sys.exit(f'--device {a.device}: not in DEVICES {list(DEVICES.values())}')
    for dev, label in devices.items():
        cur = None
        for ts, b, start in load_events(device_dirs(dev)):
            d = day(ts)
            available.add(d)
            if (a.since and d < a.since) or (a.until and d > a.until):
                continue
            all_days.add(d)
            if start:
                if cur:
                    sessions[cur[0]].append(min(ts - cur[1], SESSION_CAP))
                cur = (b, ts)
                days[b].add(d)
                per_dev[b][label] += 1
            elif cur and cur[0] == b:
                sessions[b].append(min(ts - cur[1], SESSION_CAP))
                cur = None
    if not available:
        sys.exit('no usage events found at all: check Full Disk Access and DEVICES (see --devices)')
    if not sessions:
        sys.exit(f'no usage in the requested window ({a.since or "start"} to {a.until or "end"}); '
                 f'data available {min(available)} to {max(available)}')
    if a.since and min(all_days) > a.since:
        print(f'warning: data starts {min(all_days)}, after --since {a.since}; '
              f'run --archive every few weeks so older days are kept', file=sys.stderr)

    genres = load_genres()
    if a.lookup:
        print(f'looked up {lookup_genres(sessions, genres)} new apps', file=sys.stderr)
    # No genre = never looked up, or the App Store had no entry (a lookup stores None). Either way a
    # game could hide here, so flag it rather than letting it rank.
    unknown = [b for b in sessions if not genres.get(b) and not is_system(b)]

    def why_excluded(b):
        if is_system(b):
            return 'system'
        if b in DOCK:
            return 'dock'
        if b in OTHER:
            return 'chosen'
        if b in a.skip:
            return 'skipped'
        if genres.get(b) in EXCLUDED_GENRES:
            return 'game'
        return ''
    ranked = [b for b in sessions if not why_excluded(b)]

    def ranks(metric):
        return {b: i + 1 for i, b in enumerate(sorted(ranked, key=metric, reverse=True))}
    rd = ranks(lambda b: len(days[b]))
    ro = ranks(lambda b: len(sessions[b]))
    rt = ranks(lambda b: sum(sessions[b]))
    score = {b: (rd[b] * ro[b] * rt[b]) ** (1 / 3) for b in ranked}
    order = sorted(ranked, key=lambda b: score[b])
    position = {b: i + 1 for i, b in enumerate(order)}

    span = len(all_days)
    with open(a.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rank', 'score', 'bundle_id', 'excluded', 'genre', 'days_used', 'days_in_period', 'opens',
                    'hours', 'median_session_s', 'p90_session_min'] + [f'opens_{l}' for l in DEVICES.values()])
        for b in order + sorted((b for b in sessions if b not in score), key=lambda b: -sum(sessions[b])):
            s = sessions[b]
            p90 = statistics.quantiles(s, n=10)[-1] if len(s) > 1 else s[0]
            w.writerow([position.get(b, ''), round(score[b], 1) if b in score else '', b, why_excluded(b),
                        genres.get(b) or '', len(days[b]), span, len(s), round(sum(s) / 3600, 2),
                        round(statistics.median(s)), round(p90 / 60, 1)] + [per_dev[b][l] for l in DEVICES.values()])

    print(f'{min(all_days)} to {max(all_days)} ({span} days) -> {a.out}')
    print(' #  score  days  opens   hours  bundle')
    for b in order[:a.top]:
        flag = '  (genre unknown: game?)' if b in unknown else ''
        print(f'{position[b]:2}  {score[b]:5.1f}  {len(days[b]):4}  {len(sessions[b]):5}  '
              f'{sum(sessions[b]) / 3600:6.1f}  {b}{flag}')
    if unknown:
        print(f'note: {len(unknown)} apps have no saved genre, so games among them are not excluded; '
              f're-run with --lookup', file=sys.stderr)


if __name__ == '__main__':
    main()
