"""iPhone home screen MCP server (stdio): the skill's scripts as tools, for Claude Desktop and Claude Code.

  uv run --directory <repo> server/server.py

The tools themselves are in tools.py; this file only describes them to MCP clients.
"""
import functools, os, sys
from typing import Annotated, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools  # noqa: E402

INSTRUCTIONS = """\
Arranges the user's iPhone home screen from their Mac over USB (one iPhone, connected, unlocked and
trusted): pages, order, folders, and apps or folders pinned to exact grid slots with blank spaces.
It uses undocumented Apple interfaces, so treat every write with care.

Before anything else, call get_settings. If layout.md exists, it is the layout the user chose:
follow it unless they ask for a change. If there's no layout.md, set things up: show_layout,
ask how they want it organized (their own arrangement, or one suggested by usage ranking), and
save their choices with save_settings (layout_notes = what goes where by page and row, the
widgets kept, the rules; plus the pins).

To change the layout, every time:
1. show_layout: reads the phone and saves a fresh snapshot. Always build from that snapshot,
   never an older file. It also prints the pins in effect: keep passing them, or the gaps close.
   If it says the iOS version is NOT tested, pins are refused until both pin tests pass (an app
   pin, then a folder pin, each with untested_ios_ok=true and restored afterwards; see
   read_guide("troubleshooting"), "After an iOS update"). Tell the user.
2. build_page (and make_folder) to build the new layout from that snapshot, one page at a time;
   each call writes a new file and the next call builds on it.
3. check_layout(base=the snapshot, new=the built file, pins=[...]). It must pass. Slots count
   from 0, left to right, top to bottom (0-23 on a 4x6 grid); a medium widget fills rows 1-2.
   "nowhere left for <widget>" on a page you didn't change means the phone lists that widget
   after pinned items: rebuild the page with build_page, widget first, in the user's order.
4. Show the user the pages and pins check_layout printed, and get a clear yes.
5. write_layout(confirm_token). Report what it printed: lost and added must be [], every pinned
   page must say CONFIRMED. FAILED: stop and read_guide("troubleshooting"). "not provable": ask
   the user to look at that page. Tell the user the snapshot it saved, so they can undo with
   restore_snapshot.
Apps that come back from the App Library onto pages after a write: the user removes them by hand.

Usage ranking (optional) reads Screen Time data synced to the Mac: it needs Screen Time "Share
Across Devices" on the iPhone and Full Disk Access for the Claude app (restart Claude after
granting it). list_usage_devices finds the phone's ID for config.json (save_settings). Before
rank_apps with lookup=true, ask: it sends app bundle IDs to Apple's App Store lookup. Vet the top
ranks with the user (games, one-off spikes) and re-rank with skip. Archive usage every few weeks.
If anything behaves unexpectedly, read_guide("troubleshooting") before trying fixes.
"""

mcp = MCPServer('iphone-home-screen', instructions=INSTRUCTIONS, version='2.0.0')

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def tool(annotations, title):
    """Register FN as a tool whose refusals come back as tool errors, with the message."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except tools.Refused as e:
                raise ToolError(str(e))
        return mcp.tool(title=title, annotations=annotations)(run)
    return wrap


Pins = Annotated[Optional[list[str]], Field(description='Pins as "PAGE:ITEM:SLOT", e.g. "1:com.apple.Maps:23" or "3:Travel:4" (folders by name). Pass every pin to keep, not just new ones.')]


@tool(READ, 'Show the iPhone layout')
def show_layout() -> str:
    """Read the connected iPhone's home screen (model, iOS version, grid, dock and every page) and save
    it as a new snapshot file to build from. Also lists the pins in effect. Read-only on the phone."""
    return tools.show_layout()


@tool(READ, 'List saved layouts')
def list_snapshots() -> str:
    """List saved layouts (snapshots, built layouts, readbacks and automatic pre-write backups), newest first."""
    return tools.list_snapshots()


@tool(READ, 'Show a saved layout')
def show_snapshot(name: Annotated[str, Field(description='A layout file name from list_snapshots')],
                  pages: Annotated[Optional[list[int]], Field(description='Page numbers to show (default all)')] = None) -> str:
    """Describe a saved layout file without touching the phone."""
    return tools.show_snapshot(name, pages)


@tool(LOCAL, 'Build a page')
def build_page(base: Annotated[str, Field(description='Layout to start from: the show_layout snapshot, or the result of an earlier build_page/make_folder')],
               page: Annotated[int, Field(description='1 = first home screen page; one past the last adds a page. The dock is never edited.')],
               items: Annotated[list[str], Field(description='Exactly what goes on the page, in screen order: bundle IDs, folder names, widget bundle IDs')],
               grid: Annotated[Optional[str], Field(description='COLUMNSxROWS; default the grid show_layout read')] = None) -> str:
    """Set one page to an exact list of items, pulling each from wherever it is now (apps leave folders
    when listed). Displaced items go to the front of the next page. Saves a new file; the phone is untouched."""
    return tools.build_page(base, page, items, grid)


@tool(LOCAL, 'Make a folder')
def make_folder(base: Annotated[str, Field(description='Layout to start from')],
                name: Annotated[str, Field(description='Folder name')],
                apps: Annotated[list[str], Field(description='Bundle IDs of the apps to put in it, in order')],
                page: Annotated[int, Field(description='Page to add the folder to (at the end; place it with build_page)')]) -> str:
    """Create a new folder from apps on the home screen. Saves a new file; the phone is untouched."""
    return tools.make_folder(base, name, apps, page)


@tool(READ, 'Check a layout before writing')
def check_layout(base: Annotated[str, Field(description='The show_layout snapshot the new layout was built from')],
                 new: Annotated[str, Field(description='The layout to write')],
                 pins: Pins = None,
                 no_pins: Annotated[bool, Field(description='Write with no pins: every gap on every page closes. Only if the user wants that.')] = False,
                 untested_ios_ok: Annotated[bool, Field(description='Only for the two pin tests on an iOS version not yet tested')] = False,
                 grid: Annotated[Optional[str], Field(description='COLUMNSxROWS; default the grid show_layout read')] = None) -> str:
    """Check offline that the new layout keeps every app and widget, keeps the dock, fits the grid, and
    that the pins are valid. If it passes, returns the pages that change and a one-time confirmation
    token for write_layout. Show the user the preview and get their yes before writing."""
    return tools.check_layout(base, new, pins, no_pins, untested_ios_ok, grid)


@tool(ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
      'Write the layout to the iPhone')
def write_layout(confirm_token: Annotated[str, Field(description='The token check_layout returned, after the user said yes')]) -> str:
    """Write the layout and pins that check_layout approved to the iPhone, then read it back and verify.
    Refuses if the phone changed since the snapshot (apps installed or removed, dock changed), if it isn't
    an iPhone, or if pins are used on an untested iOS version. Saves the phone's previous layout first,
    so the write can be undone with restore_snapshot."""
    return tools.write_layout(confirm_token)


@tool(READ, 'Prepare a restore')
def restore_snapshot(snapshot: Annotated[str, Field(description='Layout file to put back, e.g. an *.autosave-before-* file from list_snapshots')],
                     pins_file: Annotated[Optional[str], Field(description="Pins file to restore with; default the snapshot's own *.pins.txt")] = None,
                     untested_ios_ok: bool = False) -> str:
    """Prepare putting a saved layout back on the phone, with its pins: checks it like check_layout and
    returns a confirmation token. After the user's yes, write it with write_layout."""
    return tools.restore_snapshot(snapshot, pins_file, untested_ios_ok)


@tool(READ, 'Find synced devices')
def list_usage_devices() -> str:
    """List devices whose Screen Time usage has synced to this Mac, newest first, with date range and top
    apps, to find the iPhone's ID for config.json. Needs Full Disk Access for the Claude app."""
    return tools.list_usage_devices()


@tool(LOCAL, 'Archive usage data')
def archive_usage() -> str:
    """Copy the configured devices' synced usage files into the data folder, since the Mac keeps only
    about 4 weeks. Run every few weeks."""
    return tools.archive_usage()


@tool(ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
      'Rank apps by use')
def rank_apps(since: Annotated[Optional[str], Field(description='YYYY-MM-DD')] = None,
              until: Annotated[Optional[str], Field(description='YYYY-MM-DD')] = None,
              device: Annotated[Optional[str], Field(description='One device: its label in config.json, or its ID')] = None,
              skip: Annotated[Optional[list[str]], Field(description='Bundle IDs the user ruled out')] = None,
              lookup: Annotated[bool, Field(description="Fetch missing App Store genres, to recognise games. Sends bundle IDs to Apple: ask the user first.")] = False,
              top: int = 20) -> str:
    """Rank apps by days used, opens and time, from Screen Time data synced to the Mac. Dock apps, the
    user's exclusions and excluded genres (games) get no rank. Writes a CSV in the data folder."""
    return tools.rank_apps(since, until, device, skip, lookup, top)


@tool(READ, 'Read settings')
def get_settings() -> str:
    """Show the data folder, config.json, the user's saved layout plan (layout.md), the pins in effect and
    the iOS versions that passed the pin tests on this Mac."""
    return tools.get_settings()


@tool(LOCAL, 'Save settings')
def save_settings(config: Annotated[Optional[dict], Field(description='Whole config.json: devices {id: label}, dock [bundle IDs], exclude [bundle IDs], exclude_genres [names], store_country ("us")')] = None,
                  layout_notes: Annotated[Optional[str], Field(description="Whole layout.md: the user's layout by page and row, widgets kept, rules, and their pins")] = None) -> str:
    """Save config.json and/or layout.md in the data folder (replacing them; the previous version is kept)."""
    return tools.save_settings(config, layout_notes)


@tool(READ, 'Read a guide')
def read_guide(topic: Annotated[str, Field(description='"troubleshooting", "how-it-works" or "commands"')]) -> str:
    """Read the kit's reference guides: troubleshooting (read before trying fixes), how it works, commands."""
    return tools.read_guide(topic)


if __name__ == '__main__':
    mcp.run()
