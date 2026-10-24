"""Offline tests for the skill's scripts: no phone, no network, no pymobiledevice3.

  python3 -m unittest discover -s tests -v
"""
import os, plistlib, struct, subprocess, sys, tempfile, unittest

SKILL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.claude', 'skills', 'iphone-home-screen')
SCRIPTS = os.path.join(SKILL, 'scripts')
sys.path.insert(0, SCRIPTS)
sys.dont_write_bytecode = True
import push, infocus  # noqa: E402  (neither imports pymobiledevice3)


def app(b):
    return {'bundleIdentifier': b, 'displayIdentifier': b, 'displayName': b.split('.')[-1]}


def widget(uid, size='medium', bundle='com.example.weather.widget'):
    return {'elementType': 'widget', 'gridSize': size, 'bundleIdentifier': bundle, 'displayIdentifier': uid}


def folder(n, apps):
    return {'displayName': n, 'listType': 'folder', 'iconLists': [apps]}


def layout():
    """Dock + page 1 (widget, 4 apps, a folder) + page 2 (3 apps)."""
    return [
        [app('com.apple.mobilephone'), app('com.apple.mobilesafari')],
        [widget('W1')] + [app(f'com.example.a{i}') for i in range(1, 5)]
        + [folder('Tools', [app('com.example.t1'), app('com.example.t2')])],
        [app(f'com.example.b{i}') for i in range(1, 4)],
    ]


def run(script, *args):
    return subprocess.run([sys.executable, '-I', '-B', os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True)


class Compare(unittest.TestCase):
    def test_identical_layout_passes(self):
        self.assertTrue(push.compare(layout(), layout(), quiet=True))

    def test_lost_app_fails(self):
        new = layout(); new[2].pop()
        self.assertFalse(push.compare(layout(), new, quiet=True))

    def test_changed_dock_fails(self):
        new = layout(); new[0], new[2][0] = [new[2][0]] + new[0][1:], new[0][0]
        self.assertFalse(push.compare(layout(), new, quiet=True))

    def test_new_folder_is_not_an_added_item(self):
        new = layout(); moved = new[2].pop()
        new[2].append(folder('New', [moved]))
        self.assertTrue(push.compare(layout(), new, quiet=True))

    def test_two_widgets_from_one_app_are_not_duplicates(self):
        st = layout(); st[2].append(widget('W2', 'small'))
        self.assertTrue(push.compare(st, st, quiet=True))

    def test_overflowing_page_fails(self):
        new = layout(); new[2] += [app(f'com.example.c{i}') for i in range(30)]
        before = layout(); before.append(new[2][3:])
        self.assertFalse(push.compare(before, new, quiet=True))


class Pins(unittest.TestCase):
    def test_valid_pins(self):
        self.assertEqual(push.validate_pins(layout(), [(1, 'com.example.a1', 23), (1, 'Tools', 20)]), [])

    def test_bad_page_slot_and_duplicates(self):
        errors = push.validate_pins(layout(), [
            (0, 'com.apple.mobilephone', 3),      # the dock
            (9, 'com.example.a1', 3),             # no such page
            (1, 'com.example.a1', 24),            # outside 4x6
            (1, 'com.example.a2', 20), (1, 'com.example.a3', 20),   # one slot twice
            (2, 'com.example.zz', 1),             # not on that page
        ])
        self.assertEqual(len(errors), 5, errors)

    def test_pin_under_widget_is_refused(self):
        errors = push.validate_pins(layout(), [(1, 'com.example.a1', 0)])
        self.assertTrue(any("widget" in e for e in errors), errors)

    def test_folder_pin_key_and_grid(self):
        d = push.with_pins(layout(), [(1, 'Tools', 23)], (4, 6))
        (meta,) = d['listMetadata'].values()
        (k, slot), = meta['fixedLocations'].items()
        self.assertTrue(k.startswith('folder:'))
        self.assertEqual((slot, meta['fixedLocationsGridColumns'], meta['fixedLocationsGridRows']), (23, 4, 6))

    def test_verify_tells_honored_from_ignored(self):
        pins = [(1, 'com.example.a1', 23), (1, 'Tools', 20)]
        sent = push.pinned_first(layout(), pins)
        order = push.expected_order(sent[1], {'com.example.a1': 23, 'Tools': 20})
        honored = [sent[0], sorted(sent[1], key=lambda i: order.index(push.name(i))), sent[2]]
        self.assertTrue(push.verify(sent, honored, pins))
        self.assertFalse(push.verify(sent, sent, pins))

    def test_reordered_for_verification_is_not_a_widget_move(self):
        # Regression: push.py sends pinned items first; that reordering must not look like a moved widget.
        pins = [(1, 'com.example.a3', 20), (1, 'com.example.a4', 23)]
        self.assertEqual(push.validate_pins(layout(), pins), [])
        push.with_pins(push.pinned_first(layout(), pins), pins)   # must not exit

    def test_display_zoom_grid(self):
        self.assertTrue(push.validate_pins(layout(), [(1, 'com.example.a1', 23)], (4, 5)))


class Commands(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.before = os.path.join(self.d, 'before.plist')
        plistlib.dump(layout(), open(self.before, 'wb'))

    def test_push_requires_a_pins_choice(self):
        r = run('push.py', self.before, os.path.join(self.d, 'after.plist'))
        self.assertEqual(r.returncode, 2)
        self.assertIn('--no-pins', r.stderr)

    def test_push_rejects_mistyped_flags(self):
        # With a valid choice present, the unknown flag alone must still be refused.
        r = run('push.py', self.before, os.path.join(self.d, 'after.plist'), '--no-pins', '--Pins', 'x')
        self.assertEqual(r.returncode, 2)
        self.assertIn('unrecognized', r.stderr)

    def test_push_refuses_an_empty_pins_file(self):
        empty = os.path.join(self.d, 'pins.txt')
        open(empty, 'w').write('# only comments\n\n')
        r = run('push.py', self.before, os.path.join(self.d, 'after.plist'), '--pins', empty)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no pins found', r.stderr)

    def test_bad_pin_and_grid_give_messages_not_tracebacks(self):
        r = run('push.py', '--check', self.before, self.before, '--grid', 'four')
        self.assertIn('--grid needs', r.stderr)
        bad = os.path.join(self.d, 'bad.txt')
        open(bad, 'w').write('1-com.example.a1-23\n')
        r = run('push.py', '--check', self.before, self.before, '--pins', bad)
        self.assertIn('bad pin', r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_check_command(self):
        self.assertEqual(run('push.py', '--check', self.before, self.before).returncode, 0)

    def test_arrange_refuses_the_dock_and_overwrites(self):
        out = os.path.join(self.d, 'new.plist')
        r = run('arrange.py', self.before, out, '0', 'com.example.a1')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('dock', r.stderr)
        self.assertEqual(run('arrange.py', self.before, out, '1', 'W1-missing').returncode, 1)
        r = run('arrange.py', self.before, out, '2', 'com.example.b3', 'com.example.b1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(run('arrange.py', self.before, out, '2', 'com.example.b1').returncode, 0)

    def test_arrange_takes_app_out_of_folder(self):
        out = os.path.join(self.d, 'new2.plist')
        r = run('arrange.py', self.before, out, '2', 'com.example.t1', 'com.example.b1', 'com.example.b2',
                'com.example.b3')
        self.assertEqual(r.returncode, 0, r.stderr)
        st = plistlib.load(open(out, 'rb'))
        tools = next(i for i in st[1] if i.get('displayName') == 'Tools')
        self.assertEqual([a['bundleIdentifier'] for a in tools['iconLists'][0]], ['com.example.t2'])


class IosGate(unittest.TestCase):
    def test_a_version_needs_both_app_and_folder_passes(self):
        import importlib
        d = tempfile.mkdtemp()
        os.environ['IPHONE_HOME_SCREEN_DIR'] = d
        try:
            sys.modules.pop('homescreen', None)
            stub = type(sys)('pymobiledevice3')     # homescreen imports pymobiledevice3 at the top
            for m in ('pymobiledevice3', 'pymobiledevice3.lockdown', 'pymobiledevice3.services',
                      'pymobiledevice3.services.springboard'):
                sys.modules.setdefault(m, stub)
            stub.create_using_usbmux = stub.SpringBoardServicesService = None
            hs = importlib.import_module('homescreen')
            self.assertFalse(hs.ios_tested('28.0'))
            hs.record_ios_pass('28.0', {'app'})
            self.assertFalse(hs.ios_tested('28.0'))
            hs.record_ios_pass('28.0', {'folder'})
            self.assertTrue(hs.ios_tested('28.0'))
            self.assertTrue(hs.ios_tested('27.0.1'))
        finally:
            del os.environ['IPHONE_HOME_SCREEN_DIR']
            for m in ('homescreen', 'pymobiledevice3', 'pymobiledevice3.lockdown', 'pymobiledevice3.services',
                      'pymobiledevice3.services.springboard'):
                sys.modules.pop(m, None)

    def test_not_provable_proves_nothing(self):
        pins = [(1, 'com.example.a1', 5)]   # a1 already sits in slot 5: order can't prove the pin
        st = layout()
        proven = set()
        push.verify(st, st, pins, proven=proven)
        self.assertEqual(proven, set())


class UsageDecoder(unittest.TestCase):
    def segb(self, events):
        """Build a minimal SEGB v2 file: header, entries, and the end-of-file index read backwards."""
        def varint(n):
            out = b''
            while True:
                b, n = n & 0x7F, n >> 7
                out += bytes([b | (0x80 if n else 0)])
                if not n:
                    return out
        body, ends = b'', []
        for ts, bundle, starting in events:
            bb = bundle.encode()
            payload = (varint(3 << 3) + varint(starting) + varint((4 << 3) | 1) + struct.pack('<d', ts)
                       + varint((6 << 3) | 2) + varint(len(bb)) + bb)
            body += b'\0' * (-len(body) % 4) + struct.pack('<II', 0, 10) + payload
            ends.append(len(body))
        table = b''.join(struct.pack('<IId', e, 1, 0.0) for e in reversed(ends))
        return b'SEGB' + b'\0' * 28 + body + b'\0' * 64 + table

    def test_records_round_trip(self):
        events = [(800000000.0, 'com.example.a1', 1), (800000060.0, 'com.example.a1', 0)]
        path = os.path.join(tempfile.mkdtemp(), '1')
        open(path, 'wb').write(self.segb(events))
        got = [infocus.parse_msg(r) for r in infocus.records(path)]
        self.assertEqual([(m[4], m[6].decode(), m.get(3, 0)) for m in got], events)


if __name__ == '__main__':
    unittest.main()
