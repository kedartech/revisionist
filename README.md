# Revisionist

Revisionist is a turn-based alternate-history strategy game. Players pick a moment in history, take on a real person from it, and pursue a secret goal. A game master built from a model runs the parts nobody is playing, and a deterministic referee decides what succeeds.

The engine is Python. It ships a Typer CLI (`revisionist`), a Discord bot and a web room served by `revisionist web serve`.

## TL;DR

```sh
uv sync --frozen
uv run revisionist new salt-strait
uv run revisionist tick --offline
uv run revisionist leaks
```

The first campaign is a local SQLite file. `--offline` makes no model calls. See [Quickstart](#quickstart).

## Requirements

- **Python 3.12.** `requires-python` in `pyproject.toml` is `>=3.12`, and `.python-version` pins 3.12.
- **[uv](https://docs.astral.sh/uv/)** to install dependencies and run the tools.
- **The `claude` CLI, logged in on the host.** Every model call runs `claude -p` through `ClaudeCli` in `src/revisionist/engine/llm.py`. There is no API key path. Commands without `--offline` need it on your `PATH`.
- **Postgres** for the web room, Discord and the scheduler. A solo CLI game does not need it.
- **Node 20 or later**, only to run the web client tests.

## Quickstart

Install the dependencies:

```sh
uv sync --frozen
```

Start a solo campaign on SQLite. Use `--offline` for any command that would otherwise call a model:

```sh
uv run revisionist new salt-strait      # start a campaign in a world
uv run revisionist status               # where it stands, as your seat sees it
uv run revisionist tick --offline       # resolve one tick with fixtures
uv run revisionist leaks                # confirm no secret reached a reader
```

`salt-strait` is a solo world. You play Varda, the hinge state, and three AI factions run the rest. The campaign is a file named by `REVISIONIST_DB` (default `./revisionist.db`), so you can delete it and start over.

The bundled worlds are the files in `worlds/`:

| World | What it is |
|---|---|
| `salt-strait` | The solo world. Four polities share a strait. |
| `salt-strait-duo` | `salt-strait` with a second human seat. |
| `autumn-1941` | A realism world, 1 September to 7 December 1941. |
| `realism-slice-1941` | Five people from `autumn-1941`, for schema testing. |
| `engine-v2-slice-1941` | A contract-proof slice of `autumn-1941`. |
| `realism-toy` | A three-person test world. |

Realism worlds need `--seat`, the person you play. `revisionist world check <file>` validates a world file before you play it.

A realism campaign uses levers, steps and counsel:

```sh
uv run revisionist new realism-toy --seat "Ada Mor"
uv run revisionist aide --offline                             # your aide's brief: papers, decisions, draft orders
uv run revisionist lever propose_levy rate=5 purpose=harbour  # file an order by pulling a lever
uv run revisionist consult Tull "What would you do?"          # ask someone on your card; changes nothing
uv run revisionist step --help                                # act at a step of an order that waits on you
```

`aide` lists draft orders without filing them. Run `uv run revisionist why` on a tick to trace an order through the roll, the deltas and the narration.

Commands that call a model, such as `order`, `briefing`, `consult` and `tick` without `--offline`, use the `claude` CLI. Run `uv run revisionist --help` for the full list.

## Web room

The web room is a browser client for a campaign on Postgres. Each player sees their own seat, with:

- **Character select.** The cast as cards. Each person has a dossier with a bio, an arena, a history, a quote, a fact and a portrait. A searchable table lists everyone else who held power. The dossier text is in `worlds/dossiers/<world>.yaml`, and the portraits are in `web/assets/portraits/`, with their sources in `SOURCES.md`.
- **The opening.** Begin plays an opening crawl, then a one-time splash. Each browser sees it once per game.
- **The desk.** The in-tray, the desk where you write orders, your orders, and the messenger for your aide and contacts.
- **The day run.** The day runs when everyone is done. An overlay shows while it runs, and a What happened sheet opens with the next wake.

Start it with a Postgres database. `REVISIONIST_DB` must be a `postgresql://` URL. Set `REVISIONIST_ADMIN_DSN` to the admin connection `db migrate` uses, then apply the migrations:

```sh
export REVISIONIST_DB='postgresql://<user>:<password>@<host>/<database>'
uv run revisionist db migrate
uv run revisionist web serve
```

`web serve` takes three flags: `--host` (default `127.0.0.1`), `--port` (default `8740`) and `--static` (the client folder, default `web/`). It also takes `--offline-prose`, which writes realism pages from templates instead of a model. The server is plain HTTP. Bind it to a private address such as a tailnet address, never a public one.

The header has a theme setting. **Terminal** (green on black) is the default. **Paper** is a typed-paper look. An **Effects** toggle turns the screen effects on or off, and it is off by default. The choice is kept in the browser under `rv.theme` and `rv.effects`. The client is plain ES modules in `web/js/`, with views in `web/js/views/` and styles in `web/css/`. It has no build step.

## Discord

Discord play runs on Postgres. A campaign's humans link to Discord users, then each human redeems a single-use invite with `/join`. `revisionist discord run` starts the gateway bot in the foreground. It reads the bot token and the guild ID from environment variables named in the command's help.

```sh
uv run revisionist discord --help
```

The commands in the group are `link`, `unlink`, `invite`, `invites`, `channel`, `seats` and `run`.

## Documentation

| File | What it holds |
|---|---|
| [`docs/entry-points.md`](docs/entry-points.md) | A map of the entry points: the CLI, the services and the files they touch. |
| [`docs/deploy.md`](docs/deploy.md) | The runbook for the home server: Postgres roles, systemd units, Discord, backups. |
| [`docs/design.md`](docs/design.md) | The event log, state, visibility and pipeline, and the rules the code must keep. |
| [`docs/game-spec.md`](docs/game-spec.md) | The game rules, parameters and decisions. |
| [`docs/build-plan.md`](docs/build-plan.md) | The layer-by-layer build plan and what is built. |

[`CONTRIBUTING.md`](CONTRIBUTING.md) holds the rules and gates for contributors.

## Layout

```
src/revisionist/core/      pure game rules: events, state, visibility, referee, goals
src/revisionist/engine/    ticks, model adapters, Session Zero, scheduler, Discord, web server
src/revisionist/engine/migrations/   Postgres migrations, applied by `revisionist db migrate`
web/                       the web client: js/, css/, assets/, test/
worlds/                    world files (YAML) and dossiers/ for character select
tests/                     unit, property, leak and recorded-fixture tests; recordings/ replays model calls
docs/                      design, rules, build plan, deploy runbook
deploy/                    systemd units and backup and restore-drill scripts
schema/                    the exported JSON Schema for the event log
scripts/                   helper scripts, such as prose_ab.py, a blind prose comparison
.github/workflows/         CI
```

## Development

Run each gate on its own, so a failing exit code is not hidden by a pipe:

```sh
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest
cd web && node --test test/*.test.js
```

The suite makes no live model calls. It replays the recordings in `tests/recordings/`. Postgres tests skip unless `REVISIONIST_TEST_PG_ADMIN_DSN` names a superuser database URL. The suite creates and drops its own scratch databases.

## License

MIT, as declared in `pyproject.toml`.
