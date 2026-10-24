"""Read the iPhone home screen via SpringBoardServices (read-only; push.py writes).

  homescreen.py show          print the phone, its grid, and the dock and pages 1-2
  homescreen.py dump OUT      save the full live layout to OUT (a plist)

Talks to the first iPhone on USB, so connect only one at a time.
"""
import asyncio, inspect, os, plistlib, sys

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.springboard import SpringBoardServicesService

TESTED_IOS = {'27.0.1'}  # versions the skill's author confirmed the pin format on
# Versions this user's phone has passed the pin tests on (push.py --untested-ios-ok records them).
HOME_DIR = os.path.expanduser(os.environ.get('IPHONE_HOME_SCREEN_DIR') or '~/iphone-home-screen')
TESTED_FILE = os.path.join(HOME_DIR, 'tested-ios.txt')


def _passes():
    """{version: {'app', 'folder'}} from TESTED_FILE (one "VERSION KIND" per line)."""
    out = {}
    try:
        for line in open(TESTED_FILE):
            parts = line.split()
            if len(parts) == 2:
                out.setdefault(parts[0], set()).add(parts[1])
    except OSError:
        pass
    return out


def ios_kinds_passed(version):
    return _passes().get(version, set())


def ios_tested(version):
    """True for versions the author confirmed, or that passed both the app and folder pin tests here."""
    return version in TESTED_IOS or {'app', 'folder'} <= ios_kinds_passed(version)


def record_ios_pass(version, kinds):
    os.makedirs(HOME_DIR, exist_ok=True)
    with open(TESTED_FILE, 'a') as f:
        for k in sorted(set(kinds) - ios_kinds_passed(version)):
            f.write(f'{version} {k}\n')


async def maybe(x):
    return await x if inspect.isawaitable(x) else x


def summary(state):
    name = lambda it: (f"{it.get('bundleIdentifier')}#{it.get('displayIdentifier')}"  # a widget: # then its ID
                       if it.get('elementType') == 'widget' else it.get('bundleIdentifier') or f"[{it.get('displayName')}]")
    print('dock  :', [name(i) for i in state[0]])
    print('page 1:', [name(i) for i in state[1]])
    if len(state) > 2:
        print('page 2:', [name(i) for i in state[2]])
    print('pages :', len(state) - 1)


async def connect():
    ld = await maybe(create_using_usbmux())
    sb = SpringBoardServicesService(ld)
    if hasattr(sb, '__aenter__'):
        await sb.__aenter__()
    return ld, sb


async def service():
    return (await connect())[1]


async def device_info(ld, sb):
    """The phone's model, iOS version and home screen grid, as the phone reports them."""
    m = await maybe(sb.get_homescreen_icon_metrics())
    return {
        'model': ld.all_values.get('ProductType'),
        'class': ld.all_values.get('DeviceClass'),
        'ios': ld.product_version,
        'columns': int(m.get('homeScreenIconColumns', 4)),
        'rows': int(m.get('homeScreenIconRows', 6)),
    }


def describe(info):
    tested = 'tested' if ios_tested(info['ios']) else 'NOT tested yet: run the pin tests before writing pins'
    return (f"{info['class']} {info['model']}, iOS {info['ios']} ({tested}), "
            f"grid {info['columns']} columns x {info['rows']} rows")


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'show'
    ld, sb = await connect()
    state = await maybe(sb.get_icon_state(format_version='2'))
    if cmd == 'dump':
        if os.path.exists(sys.argv[2]):
            sys.exit(f'refusing to overwrite {sys.argv[2]}: choose a new name')
        plistlib.dump(state, open(sys.argv[2], 'wb'))
        print(f'saved {len(state) - 1} pages to {sys.argv[2]}')
    else:
        print('phone :', describe(await device_info(ld, sb)))
        summary(state)


if __name__ == '__main__':
    asyncio.run(main())
