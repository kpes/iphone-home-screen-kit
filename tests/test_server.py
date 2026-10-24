"""Offline tests for the MCP server's tools: no phone, no network. The tool logic (server/tools.py)
needs only the standard library; the MCP layer (server/server.py) is tested when `mcp` is installed.

  python3 -m unittest discover -s tests -v
"""
import asyncio, os, plistlib, sys, tempfile, time, unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
import tools  # noqa: E402
from test_scripts import app, folder, layout  # noqa: E402

PINS = ['1:com.example.a4:23', '1:Tools:20']


class ToolsTest(unittest.TestCase):
    """Each test gets its own data folder, with layout() saved as base.plist."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ['IPHONE_HOME_SCREEN_DIR'] = self.home
        self.layouts = tools.layouts_dir()
        self.save('base.plist', layout())
        tools.PENDING.clear()
        tools.SESSION.clear()
        self.calls = []
        self.real_run = tools.run_script

    def tearDown(self):
        tools.run_script = self.real_run
        del os.environ['IPHONE_HOME_SCREEN_DIR']

    def save(self, name, state):
        with open(os.path.join(self.layouts, name), 'wb') as f:
            plistlib.dump(state, f)

    def load(self, name):
        with open(os.path.join(self.layouts, name), 'rb') as f:
            return plistlib.load(f)

    def fake_phone(self, code=0, snapshot='y-after.autosave-before-1.plist', out='pins page 1: CONFIRMED'):
        """Replace the phone scripts (homescreen.py, push.py writes); offline scripts still run for real.
        A write "saves" SNAPSHOT (layout() unless the test saved one) like push.py does."""
        path = os.path.join(self.layouts, snapshot)
        if not os.path.exists(path):
            self.save(snapshot, layout())
        out = f'saved the layout from before this write: {path}\n{out}'

        def run(script, *args, timeout=120):
            if script == 'arrange.py' or args[:1] == ('--check',):
                return self.real_run(script, *args, timeout=timeout)
            self.calls.append((script,) + args)
            return code, out
        tools.run_script = run

    def created(self, text):
        """The file name a tool said it saved."""
        return text.split('Saved as ')[1].split('.plist')[0] + '.plist'

    def token(self, text):
        return text.split('Confirmation token: ')[1].split()[0]


class Files(ToolsTest):
    def test_names_must_be_bare_files_in_the_layouts_folder(self):
        outside = os.path.join(self.home, 'outside.plist')
        open(outside, 'wb').write(b'')
        os.symlink(outside, os.path.join(self.layouts, 'link.plist'))
        for bad in ('../outside.plist', outside, 'sub/base.plist', '.base.plist', 'base.txt', 'missing.plist',
                    'link.plist', None):
            with self.assertRaises(tools.Refused, msg=bad):
                tools.resolve(bad)
        self.assertEqual(tools.resolve('base.plist'), os.path.realpath(os.path.join(self.layouts, 'base.plist')))

    def test_data_folder_setting_is_expanded(self):
        # Claude Desktop passes the manifest default unexpanded; anything relative falls back to ~.
        default = os.path.expanduser('~/iphone-home-screen')
        for value, want in (('${HOME}/iphone-home-screen', default), ('~/iphone-home-screen', default),
                            ('relative/dir', default), ('', default), (self.home, self.home)):
            os.environ['IPHONE_HOME_SCREEN_DIR'] = value
            self.assertEqual(tools.home_dir(), want, value)
        os.environ['IPHONE_HOME_SCREEN_DIR'] = self.home

    def test_new_files_never_overwrite(self):
        a, b = tools.new_path('x'), None
        open(a, 'w').close()
        b = tools.new_path('x')
        self.assertNotEqual(a, b)
        self.assertFalse(os.path.exists(b))


class Building(ToolsTest):
    def test_build_page_writes_a_new_file(self):
        out = tools.build_page('base.plist', 2, ['com.example.b3', 'com.example.b1', 'com.example.b2'])
        new = self.load(self.created(out))
        self.assertEqual([i['bundleIdentifier'] for i in new[2]], ['com.example.b3', 'com.example.b1', 'com.example.b2'])
        self.assertEqual(self.load('base.plist'), layout())

    def test_build_page_reports_arrange_refusals(self):
        with self.assertRaises(tools.Refused) as e:
            tools.build_page('base.plist', 0, ['com.example.a1'])
        self.assertIn('dock', str(e.exception))

    def test_make_folder_pulls_apps_from_anywhere(self):
        out = tools.make_folder('base.plist', 'Mix', ['com.example.b1', 'com.example.t1'], 2)
        new = self.load(self.created(out))
        mix = next(i for i in new[2] if i.get('displayName') == 'Mix')
        self.assertEqual([a['bundleIdentifier'] for a in mix['iconLists'][0]], ['com.example.b1', 'com.example.t1'])
        tools_folder = next(i for i in new[1] if i.get('displayName') == 'Tools')
        self.assertEqual([a['bundleIdentifier'] for a in tools_folder['iconLists'][0]], ['com.example.t2'])
        self.assertIn('OK: safe to push', tools.check_layout('base.plist', self.created(out), no_pins=True))

    def test_make_folder_refusals(self):
        for args in (('Tools', ['com.example.b1'], 2), ('New', ['com.example.zz'], 2), ('New', ['com.example.b1'], 0)):
            with self.assertRaises(tools.Refused, msg=args):
                tools.make_folder('base.plist', *args)


class Checking(ToolsTest):
    def test_pins_choice_is_required(self):
        for kw in ({}, {'pins': []}, {'pins': PINS, 'no_pins': True}, {'pins': ['1-com.example.a1-3']}):
            with self.assertRaises(tools.Refused, msg=kw):
                tools.check_layout('base.plist', 'base.plist', **kw)
        self.assertEqual(tools.PENDING, {})

    def test_failed_check_issues_no_token(self):
        bad = layout(); bad[2].pop()
        self.save('bad.plist', bad)
        with self.assertRaises(tools.Refused) as e:
            tools.check_layout('base.plist', 'bad.plist', PINS)
        self.assertIn('lost', str(e.exception))
        self.assertEqual(tools.PENDING, {})

    def test_invalid_pins_issue_no_token(self):
        with self.assertRaises(tools.Refused) as e:
            tools.check_layout('base.plist', 'base.plist', ['1:com.example.a1:0'])   # under the widget
        self.assertIn('widget', str(e.exception))
        self.assertEqual(tools.PENDING, {})

    def test_passing_check_previews_and_issues_a_token(self):
        out = tools.check_layout('base.plist', 'base.plist', PINS)
        self.assertIn('OK: safe to push', out)
        self.assertIn(self.token(out), tools.PENDING)
        self.assertEqual([f for f in os.listdir(self.layouts) if f.endswith('.txt')], [])  # temp pins removed


class Writing(ToolsTest):
    def checked(self, **kw):
        self.fake_phone()
        return self.token(tools.check_layout('base.plist', 'base.plist', **kw))

    def test_write_runs_push_with_the_checked_pins(self):
        out = tools.write_layout(self.checked(pins=PINS))
        (call,) = self.calls
        self.assertEqual(call[0], 'push.py')
        self.assertTrue(call[1].endswith('base.plist') and call[2].endswith('-after.plist'))
        self.assertEqual(call[3:], ('--pin', PINS[0], '--pin', PINS[1]))
        self.assertIn('restore_snapshot with y-after.autosave-before-1.plist', out)

    def test_no_pins_and_untested_ios_are_passed_on(self):
        tools.write_layout(self.checked(no_pins=True, untested_ios_ok=True))
        self.assertEqual(self.calls[0][3:], ('--no-pins', '--untested-ios-ok'))

    def test_a_token_works_once(self):
        t = self.checked(pins=PINS)
        tools.write_layout(t)
        with self.assertRaises(tools.Refused):
            tools.write_layout(t)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_and_expired_tokens_are_refused(self):
        t = self.checked(pins=PINS)
        for bad in ('', 'nope', None):
            with self.assertRaises(tools.Refused):
                tools.write_layout(bad)
        tools.PENDING[t]['expires'] = time.time() - 1
        with self.assertRaises(tools.Refused) as e:
            tools.write_layout(t)
        self.assertIn('expired', str(e.exception))
        self.assertEqual(self.calls, [])

    def test_a_layout_changed_after_the_check_is_refused(self):
        t = self.checked(pins=PINS)
        st = layout(); st[2].reverse()
        self.save('base.plist', st)
        with self.assertRaises(tools.Refused) as e:
            tools.write_layout(t)
        self.assertIn('changed since check_layout', str(e.exception))
        self.assertEqual(self.calls, [])

    def test_a_failed_write_is_an_error_with_the_undo(self):
        t = self.checked(pins=PINS)
        self.fake_phone(code=1, snapshot='z.autosave-before-2.plist',
                        out='pins page 1: FAILED, read back as sent (pins ignored)')
        with self.assertRaises(tools.Refused) as e:
            tools.write_layout(t)
        self.assertIn('FAILED', str(e.exception))
        self.assertIn('restore_snapshot with z.autosave-before-2.plist', str(e.exception))


    def test_no_undo_promise_when_the_snapshot_would_not_pass(self):
        # A live read can list a widget after pinned items; with its pins it then fails the check.
        st = layout()
        st[1] = st[1][1:] + st[1][:1]
        self.save('w.autosave-before-3.plist', st)
        open(os.path.join(self.layouts, 'w.autosave-before-3.pins.txt'), 'w').write('1:com.example.a1:11\n1:com.example.a2:19\n')
        t = self.checked(pins=PINS)
        self.fake_phone(snapshot='w.autosave-before-3.plist')
        out = tools.write_layout(t)
        self.assertNotIn('restore_snapshot with', out)
        self.assertIn('rebuild the changed pages', out)


class Restoring(ToolsTest):
    def test_restore_uses_the_snapshots_own_pins(self):
        self.save('s.autosave-before-1.plist', layout())
        open(os.path.join(self.layouts, 's.autosave-before-1.pins.txt'), 'w').write('# kept\n' + '\n'.join(PINS) + '\n')
        self.fake_phone()
        out = tools.restore_snapshot('s.autosave-before-1.plist')
        tools.write_layout(self.token(out))
        self.assertEqual(self.calls[0][3:], ('--pin', PINS[0], '--pin', PINS[1]))

    def test_restore_without_pins_says_gaps_close(self):
        self.fake_phone()
        out = tools.restore_snapshot('base.plist')
        self.assertIn('no pins', out)
        tools.write_layout(self.token(out))
        self.assertEqual(self.calls[0][3:], ('--no-pins',))


class Showing(ToolsTest):
    def test_show_layout_saves_a_snapshot_and_reads_the_grid(self):
        def run(script, *args, timeout=120):
            if args == ('show',):
                return 0, 'phone : iPhone iPhone19,2, iOS 27.0.1 (tested), grid 4 columns x 5 rows\ndock  : []'
            with open(args[1], 'wb') as f:
                plistlib.dump(layout(), f)
            return 0, 'saved'
        tools.run_script = run
        open(os.path.join(self.layouts, 'last-write.pins.txt'), 'w').write('\n'.join(PINS) + '\n')
        out = tools.show_layout()
        self.assertEqual(tools.SESSION['grid'], '4x5')
        self.assertIn('[Tools] folder of 2', out)
        self.assertIn(PINS[0], out)
        self.assertTrue(tools.resolve(out.split('Saved this layout as ')[1].split()[0]))

    def test_widgets_are_named_as_arrange_takes_them(self):
        out = tools.show_snapshot('base.plist', [1])
        self.assertIn('widget com.example.weather.widget#W1 (medium)', out)
        built = tools.build_page('base.plist', 1, ['com.example.weather.widget#W1', 'com.example.a1'])
        self.assertIn('Saved as', built)

    def test_unreadable_phone_is_explained(self):
        tools.run_script = lambda *a, **k: (1, 'No device connected')
        with self.assertRaises(tools.Refused) as e:
            tools.show_layout()
        self.assertIn('unlocked', str(e.exception))


class Settings(ToolsTest):
    def test_save_settings_validates_and_keeps_the_previous_version(self):
        with self.assertRaises(tools.Refused):
            tools.save_settings({'dock': 'com.apple.mobilephone'})
        with self.assertRaises(tools.Refused):
            tools.save_settings({'devises': {}})
        tools.save_settings({'dock': ['a']}, 'page 1: a')
        tools.save_settings({'dock': ['b']})
        self.assertIn('"a"', open(os.path.join(self.home, 'config.json.previous')).read())
        out = tools.get_settings()
        self.assertIn('"b"', out)
        self.assertIn('page 1: a', out)

    def test_settings_explain_both_tested_ios_lists(self):
        open(os.path.join(self.home, 'tested-ios.txt'), 'w').write('28.0 app\n28.0 folder\n29.0 app\n')
        out = tools.get_settings()
        self.assertIn("tested by the kit's author: 27.0.1", out)
        self.assertIn('passed both pin tests on this Mac (tested-ios.txt): 28.0', out)

    def test_guides(self):
        self.assertIn('Symptom', tools.read_guide('troubleshooting'))
        with self.assertRaises(tools.Refused):
            tools.read_guide('../SKILL')


try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


@unittest.skipUnless(HAVE_MCP, 'the mcp package is not installed (CI installs it in the server job)')
class Server(ToolsTest):
    def test_tools_and_safety_annotations(self):
        import server
        listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(set(listed), {
            'show_layout', 'list_snapshots', 'show_snapshot', 'build_page', 'make_folder', 'check_layout',
            'write_layout', 'restore_snapshot', 'list_usage_devices', 'archive_usage', 'rank_apps',
            'get_settings', 'save_settings', 'read_guide'})
        writes = {n for n, t in listed.items() if t.annotations.destructive_hint}
        self.assertEqual(writes, {'write_layout'})
        self.assertEqual(list(listed['write_layout'].input_schema['properties']), ['confirm_token'])

    def test_refusals_are_tool_errors(self):
        import server
        from mcp.server.mcpserver.exceptions import ToolError
        with self.assertRaises(ToolError) as e:   # the protocol layer sends it as a result with isError
            asyncio.run(server.mcp.call_tool('write_layout', {'confirm_token': 'nope'}))
        self.assertIn('check_layout first', str(e.exception))

    def test_manifest_lists_the_servers_tools(self):
        import json, server
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        manifest = json.load(open(os.path.join(root, 'manifest.json')))
        listed = {t.name for t in asyncio.run(server.mcp.list_tools())}
        self.assertEqual({t['name'] for t in manifest['tools']}, listed)


if __name__ == '__main__':
    unittest.main()
