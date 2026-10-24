"""Sum foreground time per app from a Biome App.InFocus remote stream directory."""
import datetime, glob, os, struct, sys
from collections import defaultdict

MAC_EPOCH = 978307200


def varint(b, i):
    n = s = 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return n, i


def parse_msg(b):
    """Return dict of top-level protobuf fields, or None if it doesn't parse."""
    f, i = {}, 0
    try:
        while i < len(b):
            key, i = varint(b, i)
            num, wt = key >> 3, key & 7
            if wt == 0:
                v, i = varint(b, i)
            elif wt == 1:
                v = struct.unpack('<d', b[i:i + 8])[0]; i += 8
            elif wt == 2:
                ln, i = varint(b, i); v = b[i:i + ln]; i += ln
            elif wt == 5:
                i += 4; continue
            else:
                return None
            f[num] = v
    except (IndexError, struct.error):
        return None
    return f


def records(path):
    """SEGB v2: 32-byte header, entries of [crc:u32][?:u32][payload] 4-byte aligned,
    and a table at file end (read backwards) of 16-byte rows: [end:u32][state:u32][ts:f64]."""
    with open(path, 'rb') as f:
        b = f.read()
    if b[:4] != b'SEGB':
        return
    start, pos = 0, len(b) - 16
    while pos > 32:
        end, state = struct.unpack('<II', b[pos:pos + 8])
        if end == 0 or 32 + end > pos:
            break
        if state == 1:
            yield b[32 + start + 8:32 + end]
        start = (end + 3) & ~3
        pos -= 16


def main(d):
    events = []
    for p in glob.glob(os.path.join(d, '[0-9]*')):
        for r in records(p):
            m = parse_msg(r)
            if not m or 4 not in m or 6 not in m:
                continue
            events.append((m[4], m[6].decode('utf-8', 'replace'), m.get(3, 0)))
    if not events:
        sys.exit(f'no events read from {d} (missing folder, or no Full Disk Access?)')
    events.sort()
    totals, launches = defaultdict(float), defaultdict(int)
    open_app = None  # (bundle, start_ts)
    for ts, bid, starting in events:
        if starting:
            if open_app:  # previous app implicitly left foreground
                totals[open_app[0]] += min(ts - open_app[1], 4 * 3600)
            open_app = (bid, ts); launches[bid] += 1
        elif open_app and open_app[0] == bid:
            totals[bid] += min(ts - open_app[1], 4 * 3600)
            open_app = None
    if events:
        fmt = lambda t: datetime.datetime.fromtimestamp(t + MAC_EPOCH).strftime('%Y-%m-%d %H:%M')
        print(f'# {len(events)} events, {fmt(events[0][0])} .. {fmt(events[-1][0])}')
    for bid, secs in sorted(totals.items(), key=lambda x: -x[1]):
        print(f'{secs / 3600:8.1f}h  {launches[bid]:5d}x  {bid}')


if __name__ == '__main__':
    main(sys.argv[1])
