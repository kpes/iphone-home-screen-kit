# Developing the iPhone home screen kit

## What's in the kit
- **The skill**, in `.claude/skills/iphone-home-screen/`:

  | Path | What it is |
  |---|---|
  | `SKILL.md` | Setup, the refresh procedure and restore points |
  | `scripts/` | `rank.py` (usage ranking), `homescreen.py` (read the layout), `arrange.py` (build a page), `push.py` (check, write with pins, verify), `infocus.py` (usage decoder) |
  | `references/` | `commands.md`, `how-it-works.md`, `troubleshooting.md` |
  | `assets/` | Example `config.json`, an example pin file, and an excerpt of iOS's pin format |

- **The desktop extension** is the repo root: `manifest.json` (the extension), `pyproject.toml`
  and `uv.lock` (its dependencies), `icon.png`, and `server/`. `tools.py` runs the skill's scripts
  for each tool, and `server.py` describes the tools over MCP. The tools are `show_layout`,
  `list_snapshots`, `show_snapshot`, `build_page`, `make_folder`, `check_layout`, `write_layout`,
  `restore_snapshot`, `list_usage_devices`, `archive_usage`, `rank_apps`, `get_settings`,
  `save_settings` and `read_guide`. Every write goes through `push.py`, with the same checks as the
  skill, after `check_layout` has passed on that exact layout and pins. `.mcpbignore` keeps
  everything else out of the `.mcpb`.
- **`.claude-plugin/`** makes the repo a Claude Code plugin and marketplace whose one plugin is the
  skill. The plugin doesn't register the MCP server.

Each user's settings, usage archive and layout snapshots live in `~/iphone-home-screen/` (or
`$IPHONE_HOME_SCREEN_DIR`), outside the kit.

## Tests
Offline tests, no phone needed:
```bash
python3 -B -m unittest discover -s tests
```
This runs everything except the MCP-layer tests, which are skipped without the `mcp` package. To
run those too, in the server's own environment:
```bash
uv run python -B -m unittest discover -s tests
```
CI runs the offline tests on Python 3.9 and 3.13, `skills-ref validate` on the skill, and, on macOS,
`uv sync --locked`, all the tests, and the extension's manifest check and pack. It uploads the
`.mcpb` as an artifact.

## The MCP server in Claude Code (optional)
The plugin is skill-only. To use the extension's tools in Claude Code as well (they appear as
`mcp__iphone-home-screen__*`), clone the repo and add the server yourself. It needs
[uv](https://docs.astral.sh/uv/) on your `PATH`.
```bash
git clone https://github.com/kpes/iphone-home-screen-kit ~/iphone-home-screen-kit
claude mcp add --scope user iphone-home-screen -- uv run --quiet --directory ~/iphone-home-screen-kit server/server.py
```
Remove it with `claude mcp remove --scope user iphone-home-screen`, and update it with
`git -C ~/iphone-home-screen-kit pull`.

## Building the extension
```bash
npx @anthropic-ai/mcpb pack . dist/iphone-home-screen.mcpb
```
Double-click the result to install it in the Claude desktop app.

## Releasing (maintainers)
1. Bump the version in `.claude-plugin/plugin.json`, `SKILL.md`, `manifest.json`, `pyproject.toml`
   and `server/server.py`, and add a CHANGELOG entry.
2. After merging, download the `iphone-home-screen.mcpb` that CI built from the merge commit (the
   `mcp-server` job's artifact), and check that it installs.
3. Attach it to the release:
   ```bash
   gh release create vX.Y.Z --title vX.Y.Z --notes-file <notes> iphone-home-screen.mcpb
   ```
   The README's download link points at the latest release, so every release needs the `.mcpb`.
