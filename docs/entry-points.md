# Revisionist entry-point inventory

Read-only inventory of `main`. Paths are relative to the repo root. Each entry cites its location as `path:line`, and the line is the one that holds the named symbol.

## Map of the repo
- `src/revisionist/cli.py`: Typer CLI, the only console script (`revisionist`). There is no `__main__.py`.
- `src/revisionist/core/`: pure rules with no I/O: events, fold/state, referee, contest, goals, canary (leak scan), world compile.
- `src/revisionist/engine/`: tick runner, scheduler, SQLite and Postgres stores, Claude transport (`llm.py`), Session Zero, `engine/discord/` bot, `engine/prompts/` model prompts, `engine/web/` web client backend (JSON API).
- `src/revisionist/engine/migrations/` (Postgres SQL), `worlds/` (world YAML and `worlds/dossiers/` sidecar text), `schema/` (committed event JSON Schema), `deploy/` (systemd user units, backup scripts), `docs/`.
- `web/` (static client: `index.html`, `js/`, `css/`, `assets/`, `test/`), `tests/` (pytest; `recordings/` replays model calls), `.github/workflows/ci.yml`.

## 1. Process / service entry points
- `pyproject.toml:20-21`: `[project.scripts]` `revisionist = "revisionist.cli:app"`. Installed with `uv tool install --editable '.[postgres,discord]'` (`docs/deploy.md:68`).
- `src/revisionist/schema_export.py:36-37`: `python -m revisionist.schema_export` regenerates the committed schema.
- `deploy/systemd/revisionist-discord.service:15`: `ExecStart=%h/.local/bin/revisionist discord run`. Type=simple (`deploy/systemd/revisionist-discord.service:10`), `Restart=on-failure` (`deploy/systemd/revisionist-discord.service:16`), env file `%h/.config/revisionist/revisionist.env` (`deploy/systemd/revisionist-discord.service:11`), `WantedBy=default.target` (`deploy/systemd/revisionist-discord.service:27`).
- `deploy/systemd/revisionist-scheduler.service:14`: `ExecStart=... revisionist scheduler run`. Type=oneshot (`deploy/systemd/revisionist-scheduler.service:9`), same env file (`deploy/systemd/revisionist-scheduler.service:10`).
- `deploy/systemd/revisionist-scheduler.timer:5`: `OnCalendar` every 10 minutes. Triggers the scheduler unit (`deploy/systemd/revisionist-scheduler.timer:9`).
- `deploy/systemd/revisionist-scheduler@.service:18`: the templated unit, one instance per name after the `@` (`revisionist-scheduler@share.service`). `ExecStart=... revisionist scheduler run --transport ${REVISIONIST_SCHEDULER_TRANSPORT}`. Type=oneshot (`deploy/systemd/revisionist-scheduler@.service:13`), env file `%h/.config/revisionist/%i.env` (`deploy/systemd/revisionist-scheduler@.service:14`). The instance's env file must set `REVISIONIST_SCHEDULER_TRANSPORT=claude|openrouter`: a file without the line makes the start fail, and nothing falls back to `claude`. Installed and enabled as in `docs/deploy.md` §11.
- `deploy/systemd/revisionist-scheduler@.timer:5`: `OnCalendar` every 10 minutes for the instance; `Unit=revisionist-scheduler@%i.service` (`deploy/systemd/revisionist-scheduler@.timer:9`), `WantedBy=timers.target` (`deploy/systemd/revisionist-scheduler@.timer:12`).
- `deploy/systemd/revisionist-backup.service:10`: `ExecStart=%h/.local/bin/revisionist-backup`. Oneshot, admin env file `deploy/systemd/revisionist-backup.service:9`. Installed from `deploy/backup/revisionist-backup.sh` (`docs/deploy.md:95`).
- `deploy/systemd/revisionist-backup.timer:5`: `OnCalendar=*-*-* 03:30:00`, `RandomizedDelaySec=15min` (`deploy/systemd/revisionist-backup.timer:7`).
- `deploy/backup/revisionist-restore-drill.sh:1-37`: manual drill, not on a timer. Installed as `revisionist-restore-drill` (`docs/deploy.md:96`). Runs `revisionist db verify`, then restores `map-objects/` from the backup into a scratch directory and runs `revisionist db map-objects verify` against it.
- Bot entry: `src/revisionist/cli.py:1369-1401` (`discord run`) → `src/revisionist/engine/discord/bot.py:464` `run()` → `RevisionistBot.run(token)`.
- Scheduler entry: `src/revisionist/engine/scheduler.py:288` `run()`, called from `scheduler run` (`src/revisionist/cli.py:1132`). With `--transport openrouter` the transport is built first by `_openrouter_factory()` (`src/revisionist/cli.py:1069`): one shared, guarded, free-models-only `OpenRouterTransport` (`src/revisionist/engine/openrouter.py:187`), and the `claude` CLI is never started.
- Solo entry: `revisionist tick` (`src/revisionist/cli.py:587`), run by hand on SQLite.
- Web entry: `revisionist web serve` (`src/revisionist/cli.py:1412`) runs in the foreground. Plain HTTP. No systemd unit or deploy file covers it (`deploy/` and `docs/deploy.md` have none). `--transport openrouter` builds the same shared free-models transport as the scheduler and runs the aide from templates.

## 2. CLI commands
Exit codes: 1 error, 2 refused, 3 leak (`src/revisionist/cli.py:60-62`). `--seat` takes an ID or a name (`src/revisionist/cli.py:103-106`). `--offline` is `src/revisionist/cli.py:56-58`.

Top-level:
- `version` (`src/revisionist/cli.py:139`): print engine version.
- `new WORLD [--seat PERSON]` (`src/revisionist/cli.py:156`): compile a world YAML (name in `worlds/` or a path) and start a campaign. A realism world needs `--seat` (a person's key or name), which claims them and closes Session Zero; a legacy world refuses it.
- `dashboard [--seat]` (`src/revisionist/cli.py:341`): standing, means, goal progress.
- `status [--seat]` (`src/revisionist/cli.py:384`): campaign status as your seat sees it.
- `briefing [--seat]` (`src/revisionist/cli.py:395`): agent briefing. Exit 3 if withheld.
- `order TEXT [--seat] [--visibility private|public|covert] [--spin ≤280]` (`src/revisionist/cli.py:418`): file an order.
- `tick [--offline]` (`src/revisionist/cli.py:595`): resolve one tick. `--offline` uses the scripted resolver and narrator. On a realism campaign it runs `run_realism_tick` (`src/revisionist/engine/realism_tick.py:135`) and prints the wake and the new date. Code decides every outcome; the only model call is the PROSE stage, one call per document author per wake through `ClaudeProseWriter` (`src/revisionist/engine/prose.py:146`). The prose writer is picked in `src/revisionist/engine/runner.py:83`: `TemplateProseWriter` (plain period sentences, no model) when offline.
- `lever NAME [key=value ...] [--seat]` (`src/revisionist/cli.py:466`): realism. File an order by pulling a lever on your card; every parameter is checked against its spec. Prints the order id and its first step.
- `step ORDER ACTION [key=value ...] [--seat]` (`src/revisionist/cli.py:484`): realism. Act at the step of your order that waits on you (`pass`, `refuse`, `amend` with edits, ...). A final step that enacts the order runs its resolver in the same batch, so its quantities (vote counts) are set before the next tick.
- `consult PERSON "QUESTION" [--seat]` (`src/revisionist/cli.py:528`): realism. Ask a person on your card (by surname, full name or entity id) over your card's channel to them. The counsel model speaks as that person from their projection only (`core/realism/person.project_person`). Lands a `counsel_held` record private to your seat, plus `cost_logged`; changes nothing in the world and files nothing. Exit 2 for someone not within reach.
- `aide [--seat] [--offline]` (`src/revisionist/cli.py:560`): realism. Your aide's brief from your projected view: a summary of unread pages, the decisions waiting on you, and up to three draft orders from your levers, printed as `revisionist lever ...` commands and never filed. `--offline` uses the template aide (no model).
- `why TARGET [--break-glass] [--reason]` (`src/revisionist/cli.py:638`): trace an intent or event through the log.
- `replay --to TICK` (`src/revisionist/cli.py:666`): rebuild state at a tick and print its hash.
- `cost` (`src/revisionist/cli.py:675`): model spend per tick and in total; on a realism campaign also per in-world day.
- `leaks [--humans]` (`src/revisionist/cli.py:682`): canary scan. `--humans` needs Postgres and Discord links.
- `history [--seat]` (`src/revisionist/cli.py:854`): tick-0 brief from the record.
- `agent --name --role [--voice] [--backstory] [--relationship] [--seat]` (`src/revisionist/cli.py:865`): design your agent's persona.
- `begin` (`src/revisionist/cli.py:885`): close Session Zero and start play.

Groups:
- `world` (`src/revisionist/cli.py:203-204`):
  - `check WORLD [--gaps-only]` (`src/revisionist/cli.py:208`): validate a world file as `new` would, and list what is still unsourced. `--gaps-only` prints only the gap list.
- `establish` (`src/revisionist/cli.py:235`):
  - `pitch TEXT [--effort 1-4]` (`src/revisionist/cli.py:246`): read a pitch into a setting card.
  - `confirm N [--strike] [--end YYYY-MM-DD] [--days 1-365] [--plausibility] [--inertia] [--lethality] [--betrayal] [--tone] [--tick-hours 1-168] [--effort]` (`src/revisionist/cli.py:271`): open the game from start point N.
- `season` (`src/revisionist/cli.py:351`):
  - `end` (`src/revisionist/cli.py:356`): full reveal, winners; ticks stop.
  - `report` (`src/revisionist/cli.py:372`): season report.
- `character` (`src/revisionist/cli.py:714`):
  - `roster` (`src/revisionist/cli.py:746`), `search DESCRIPTION` (`src/revisionist/cli.py:752`), `claim NAME [--new]` (`src/revisionist/cli.py:765`), `pick NAME [--new]` (`src/revisionist/cli.py:778`).
- `goal` (`src/revisionist/cli.py:716`):
  - `suggest {history|could_have} [--seat]` (`src/revisionist/cli.py:792`), `own TEXT [--seat]` (`src/revisionist/cli.py:811`), `confirm LABEL [--seat]` (`src/revisionist/cli.py:824`).
  - `flags` (`src/revisionist/cli.py:835`), `approve SEAT` (`src/revisionist/cli.py:841`): host balance flags.
- `db` (`src/revisionist/cli.py:890`):
  - `migrate [--app-role]` (`src/revisionist/cli.py:899`): apply migrations as `REVISIONIST_ADMIN_DSN`.
  - `copy --from SQLITE --to PG_URL [--campaign]; map-objects copy --to DIR [--campaign] [--all]` (`src/revisionist/cli.py:915`), `verify [--campaign]` (`src/revisionist/cli.py:946`).
  - `map-objects verify [--campaign]` (`src/revisionist/cli.py:985`), `map-objects copy --to DIR [--campaign] [--all]` (`src/revisionist/cli.py:994`): the map objects the stored campaigns name. `verify` prints `ok` or `FAIL` per campaign (the FAIL names the campaign and the missing hash) and exits non-zero on any; only `REVISIONIST_MAP_OBJECTS` counts, never a world-named file. `copy` writes each named object into DIR and reads it back against its hash; `--all` copies every object in the directory without reading a database (the backup uses it, so a sealed database needs no key there). Built by `map_api.verify_objects()` and `map_api.copy_objects()` (`src/revisionist/engine/web/map_api.py`). `docs/deploy.md` section 7.
  - `wake-report [--campaign]` (`src/revisionist/cli.py:960`): read-only report for the operator, never served to a seat. Per campaign: how each wake closed (`all_committed`, `deadline` or `host`, `open`, or `unknown` in a log written before the wake record); per seat, the wakes the aide played and the hours from a wake's opening to the seat's own commit; and for each return after a missed wake, whether the catch-up reply served a page, with at least one paper or the owner's note of what the aide filed, for every wake missed; and in a game with `holders` on, under each wake, the territories that changed holder in it (name, new holder, old holder) and, with `economy` on, every nation's public figure as the wake ended (`Holding`); and in a game with `locks` on, under each wake, per seat, the orders it filed, the orders a lock held, the asks it made and its held orders whose lock opened (`Locked`), counts only; and in a game with `offers` on, under each wake, the offers made to blocs and the promises judged kept and broken (`Offers`), counts only. Built by `wake_report.lines()` (`src/revisionist/engine/wake_report.py:219`) from the event log, through `build()` (`src/revisionist/engine/wake_report.py:92`) and `render()` (`src/revisionist/engine/wake_report.py:182`).
- `admin` (`src/revisionist/cli.py:980`):
  - `show EVENT_ID [--reason]` (`src/revisionist/cli.py:985`): print an event; a sealed private one is logged as an admin read.
  - `erase --seat [--reason] [--campaign]` (`src/revisionist/cli.py:1003`): destroy a seat's key.
  - `new-master-key PATH` (`src/revisionist/cli.py:1043`).
- `reports` (`src/revisionist/cli.py`, `reports_app`): the players' reports, for the operator; Postgres only (migration 0015).
  - `list [--campaign] [--status]`: one line per report, oldest first: number, kind, status, game, wake and the start of its words. `show NUMBER`: one report in full, with its game, the office that filed it, wake, log position, state hash, words and reply. `export [--campaign] [--out]`: every report as one JSON line, words in plain, to stdout or a new file made with mode 600. `mark NUMBER --status [--reply]`: set the status (`new`, `seen`, `acted`) and, if given, the one-line reply (at most 200 characters) its author reads. Sealed words are opened with the seat's key; an erased seat's read as erased. Built by `src/revisionist/engine/web/reports.py` (`listing()`, `get()`, `mark()`, `record()`).
  - `digest [--day]`: one day's digest (default yesterday, UTC) to `REVISIONIST_REPORTS_DIGEST_TO` through the notice sender (`REVISIONIST_NOTICE_SMTP`, else `REVISIONIST_NOTICE_OUTBOX`): a count of that day's reports by kind and game, none of their words (`notice.compose_digest()`, `notice.send_digest()`). Once a day: a day already sent (`player_report_digests`) or with no reports sends nothing, and a send that fails is not marked. Nothing runs it on a timer yet: run it daily from cron or a user timer.
- `scheduler` (`src/revisionist/cli.py:1083`):
  - `run [--campaign] [--offline] [--transport claude|openrouter]` (`src/revisionist/cli.py:1113`), `status [--campaign]` (`src/revisionist/cli.py:1154`), `advance [--campaign]` (`src/revisionist/cli.py:1182`), `pause [--campaign] [--reason]` (`src/revisionist/cli.py:1188`), `resume [--campaign]` (`src/revisionist/cli.py:1197`).
  - `run --transport` falls back to `$REVISIONIST_SCHEDULER_TRANSPORT` (`SCHEDULER_TRANSPORT_ENV`, `src/revisionist/cli.py:1064`), then to `claude`. `openrouter` needs `$REVISIONIST_OPENROUTER_KEY` and ticks on free models only. The templated units (section 1) pass the flag, so an instance cannot start on the wrong transport.
- `discord` (`src/revisionist/cli.py:1204`):
  - `link --user ID [--campaign] [--seat]` (`src/revisionist/cli.py:1248`), `unlink [--campaign] [--seat]` (`src/revisionist/cli.py:1271`), `invite [--campaign] [--seat] [--hours 1-720]` (`src/revisionist/cli.py:1287`), `invites [--campaign]` (`src/revisionist/cli.py:1321`), `channel public CHANNEL_ID [--campaign]` (`src/revisionist/cli.py:1334`), `seats` (`src/revisionist/cli.py:1357`), `run` (`src/revisionist/cli.py:1369`).
- `web` (`src/revisionist/cli.py:1404`):
  - `serve [--host 127.0.0.1] [--port 8740] [--static DIR] [--offline-prose] [--transport claude|openrouter] [--secure-cookie]` (`src/revisionist/cli.py:1412`). `--secure-cookie` says HTTPS sits in front: the cookie gets `Secure` and every reply `Strict-Transport-Security`; without it, a bind other than this machine prints one warning line (`guard.start_warning()`). `--offline-prose` makes the realism `advance` write pages with `TemplateProseWriter` instead of `ClaudeProseWriter`. `--transport openrouter` serves on the free models (key from `$REVISIONIST_OPENROUTER_KEY`) with the aide written from templates. The server is built at `src/revisionist/cli.py:1447`.
  - `check-transport [--transport openrouter]` (`src/revisionist/cli.py:1461`): sends each free model of the routing table one fixed text of places, names, a date and a number, and asks for it back (`transport_check.run()`, `src/revisionist/engine/transport_check.py:92`). Exit 0 every word came back, 1 a word was lost (check the account's guardrails), 2 no verdict. Run it before serving the free instance.

## 3. Discord surface
- Registration: `src/revisionist/engine/discord/bot.py:112` `register()`. Every command is guild-scoped (`guild=guild`). Command names are listed at `src/revisionist/engine/discord/bot.py:37-62`.
- `src/revisionist/engine/discord/bot.py:442-443` `setup_hook`: syncs the guild command tree. `src/revisionist/engine/discord/bot.py:435`: default intents only.
- `src/revisionist/engine/discord/bot.py:73` `answer()`: defers ephemerally and replies by followup. Replies slower than `LONG_REPLY_S` (`src/revisionist/engine/discord/bot.py:34`) are also DMed.
- Seat commands (bot.py handler → `src/revisionist/engine/discord/handlers.py` method):
  - `/order text visibility spin`: `src/revisionist/engine/discord/bot.py:124` → `src/revisionist/engine/discord/handlers.py:211` `order`. File an order.
  - `/briefing`: `src/revisionist/engine/discord/bot.py:134` → `src/revisionist/engine/discord/handlers.py:233` `briefing`. Latest agent briefing.
  - `/dispatch`: `src/revisionist/engine/discord/bot.py:139` → `src/revisionist/engine/discord/handlers.py:282` `dispatch`. Latest tick briefing.
  - `/join code`: `src/revisionist/engine/discord/bot.py:147` → `src/revisionist/engine/discord/handlers.py:297` `join`. Redeem an invite code for a seat.
  - `/status`: `src/revisionist/engine/discord/bot.py:154` → `src/revisionist/engine/discord/handlers.py:242` `status`.
  - `/dossier`: `src/revisionist/engine/discord/bot.py:296` → `src/revisionist/engine/discord/handlers.py:201` `dossier`. What your seat holds, knows and faces.
  - `/dashboard`: `src/revisionist/engine/discord/bot.py:301` → `src/revisionist/engine/discord/handlers.py:494` `dashboard`.
  - `/report`: `src/revisionist/engine/discord/bot.py:422` → `src/revisionist/engine/discord/handlers.py:885` `report`. Season report after it ends.
  - `/bug notes`: `src/revisionist/engine/discord/bot.py:415` → `src/revisionist/engine/discord/handlers.py:264` `bug`. Report a bug pinned to this tick.
  - `/key`: `src/revisionist/engine/discord/bot.py:427` → `NOT_YET` stub (`src/revisionist/engine/discord/bot.py:429`, `src/revisionist/engine/discord/handlers.py:101`).
  - `/character action [text]`: `src/revisionist/engine/discord/bot.py:237` → `src/revisionist/engine/discord/handlers.py:616` `character`. Actions: roster, search, claim, pick.
  - `/goal action [text]`: `src/revisionist/engine/discord/bot.py:250` → `src/revisionist/engine/discord/handlers.py:648` `goal`. Actions: history, could_have, own, confirm.
  - `/history`: `src/revisionist/engine/discord/bot.py:261` → `src/revisionist/engine/discord/handlers.py:666` `history`.
  - `/agent name role voice backstory relationship`: `src/revisionist/engine/discord/bot.py:266` → `src/revisionist/engine/discord/handlers.py:676` `agent`.
- Host commands:
  - `/establish pitch text`: `src/revisionist/engine/discord/bot.py:162` → `src/revisionist/engine/discord/handlers.py:375` `establish_pitch`.
  - `/establish confirm choice strike end days`: `src/revisionist/engine/discord/bot.py:175` → `src/revisionist/engine/discord/handlers.py:393` `establish_check` (refuses early), then `src/revisionist/engine/discord/handlers.py:430` `establish_confirm`. Result is DMed (`src/revisionist/engine/discord/bot.py:195-200`).
  - `/retire [campaign]`: `src/revisionist/engine/discord/bot.py:206` → `src/revisionist/engine/discord/handlers.py:516` `retire`.
  - `/invite [seat]`: `src/revisionist/engine/discord/bot.py:216` → `src/revisionist/engine/discord/handlers.py:552` `invite`. One-time `/join` code.
  - `/channel`: `src/revisionist/engine/discord/bot.py:223` → `src/revisionist/engine/discord/handlers.py:596` `channel`. Make this channel the public channel.
  - `/begin`: `src/revisionist/engine/discord/bot.py:285` → `src/revisionist/engine/discord/handlers.py:682` `begin`. Then DMs each opening dossier (`src/revisionist/engine/discord/bot.py:288-293`, `src/revisionist/engine/discord/handlers.py:696` `opening_dossiers`).
  - `/season-end`: `src/revisionist/engine/discord/bot.py:306` → `src/revisionist/engine/discord/handlers.py:503` `season_end`.
  - `/advance`: `src/revisionist/engine/discord/bot.py:311` → `src/revisionist/engine/discord/handlers.py:720` `advance`. Run the next tick now.
  - `/pause`: `src/revisionist/engine/discord/bot.py:316` → `src/revisionist/engine/discord/handlers.py:759` `pause`. `/resume`: `src/revisionist/engine/discord/bot.py:321` → `src/revisionist/engine/discord/handlers.py:767` `resume`.
  - `/host` group (`src/revisionist/engine/discord/bot.py:325`, added at `src/revisionist/engine/discord/bot.py:411`):
    - `seats` → `src/revisionist/engine/discord/handlers.py:776` `host_seats`, `invites` → `src/revisionist/engine/discord/handlers.py:781` `host_invites`.
    - `link user seat` → `src/revisionist/engine/discord/handlers.py:788` `host_link`, `unlink seat` → `src/revisionist/engine/discord/handlers.py:805` `host_unlink`.
    - `flags` → `src/revisionist/engine/discord/handlers.py:812` `host_flags`, `approve seat` → `src/revisionist/engine/discord/handlers.py:817` `host_approve`.
    - `schedule` → `src/revisionist/engine/discord/handlers.py:826` `host_schedule`, `cost` → `src/revisionist/engine/discord/handlers.py:835` `host_cost`.
    - `leaks` → `src/revisionist/engine/discord/handlers.py:843` `host_leaks`, `why target reason` → `src/revisionist/engine/discord/handlers.py:853` `host_why`.
    - `replay tick` → `src/revisionist/engine/discord/handlers.py:873` `host_replay`, `verify` → `src/revisionist/engine/discord/handlers.py:878` `host_verify`.
- Listeners:
  - `src/revisionist/engine/discord/bot.py:445-461` `on_message`: a DM starting `order:` → `handlers.order`. Any other DM → `handlers.advise` (`src/revisionist/engine/discord/handlers.py:182`). Guild messages and bots are ignored.
- Components: none. Nothing in `src/` uses `discord.ui` views, modals or selects.
- Scheduled tasks in process: none. Ticks come from the systemd timer and `scheduler run` (see section 1).

## 4. Engine entry points
Ticks and orders:
- `src/revisionist/engine/runner.py:62` `play_tick()`: run or resume one tick. Calls `faction_turns` (`src/revisionist/engine/runner.py:117`) for AI factions, then `run_tick`, then the leak report.
- `src/revisionist/engine/tick.py:165` `run_tick()`: close one tick (resolve, narrate, deliver). Safe to re-run after a crash. Raises `NotInPlayError` (`src/revisionist/engine/tick.py:119`).
- `src/revisionist/engine/tick.py:137` `file_intent()`: validate an intent with the referee. Appends `IntentFiled` or `IntentRejected`.
- `src/revisionist/engine/play.py:77` `give_order()`: player order → `receive_order` (called at `src/revisionist/engine/play.py:100`) → `file_intent` (`src/revisionist/engine/agent.py:494`).
- `src/revisionist/engine/agent.py:452` `receive_order()`. `src/revisionist/engine/agent.py:213` `class Agent`; `src/revisionist/engine/agent.py:286` `deputy_turn()` files faction deputies' intents. `src/revisionist/engine/agent.py:516` `counterfactual_diff()`.
- `src/revisionist/engine/runner.py:141`: deputy intents are filed with `KeywordSafety`.
- `src/revisionist/engine/scheduler.py:288` `run()`: tick every due campaign once. `src/revisionist/engine/scheduler.py:135` `ScheduleTable` with `advance` (`src/revisionist/engine/scheduler.py:198`), `pause` (`src/revisionist/engine/scheduler.py:203`), `resume` (`src/revisionist/engine/scheduler.py:209`), `retire` (`src/revisionist/engine/scheduler.py:216`). `src/revisionist/engine/scheduler.py:234` `register()`, `src/revisionist/engine/scheduler.py:245` `live_campaigns()`, `src/revisionist/engine/scheduler.py:78` `due()`.

The asynchronous wake (one wake for the whole table; a leader changes hands only at a close):
- `src/revisionist/engine/wake.py`: `open_wake()` (`src/revisionist/engine/wake.py:57`), `commit()` (`src/revisionist/engine/wake.py:98`), `hand_over()` (`src/revisionist/engine/wake.py:156`, a new player takes up a leader nobody plays; refused for a leader someone plays or will play and while the players after the close would fill every human seat), `joining()` (`src/revisionist/engine/wake.py:176`), `leave()` (`src/revisionist/engine/wake.py:187`), `close_wake()` (`src/revisionist/engine/wake.py:217`).
- `src/revisionist/engine/wake_open.py`: the two hooks of a wake opening. `before_offers()` (`src/revisionist/engine/wake_open.py:19`) files the seats' held orders, in the order given and before the wake's offers; `after_open()` (`src/revisionist/engine/wake_open.py:29`) sends each human seat its notice and never stops the tick. Both are called from `src/revisionist/engine/runner.py`.
- `src/revisionist/engine/notice.py`: one notice per human seat per wake opening (`WebNotifier`, `src/revisionist/engine/notice.py:297`; `for_store()`, `src/revisionist/engine/notice.py:328`; `address_action()`, `src/revisionist/engine/notice.py:358`). Goes by SMTP when `REVISIONIST_NOTICE_SMTP` is set, else to the file `REVISIONIST_NOTICE_OUTBOX` as one JSON line per message (a dry run), else nowhere (section 8). Also the operator's report digest: `compose_digest()` and `send_digest()`, one message a day to `REVISIONIST_REPORTS_DIGEST_TO` with a count per kind and game, never a report's words.
- `src/revisionist/engine/web/reports.py`: player reports (RPS). `file()` stores one (`player_reports`, migration 0015) pinned to the log position and the state's hash, words sealed to the seat, and, when `REVISIONIST_REPORTS_DIR` is set, writes `report-<n>.md` there (folder 700, file 600, the words in plain: kind, game, office, wake, log position, state hash, words); `action()` is the realism `report`, `reports` and `report-mark`; `from_question()` files a prefixed aide question by code; `seat_bug()` is the seat action `bug`; `listing()`, `get()`, `mark()`, `record()`, `day_counts()` and `send_digest()` serve `revisionist reports`. A report is read by its author, the host of its game and the operator; no model reads one.
- `src/revisionist/engine/maps.py`: map objects. `map_object(sha256, file)` finds the map a stored game names by its hash (`REVISIONIST_MAP_OBJECTS`, below). A world's board is compiled into one `map_declared` event (`src/revisionist/core/realism/territory.py`, `WorldMap`); `load_world()` reads the map file the world names from `maps/` beside it, or beside it.
- `src/revisionist/core/realism/kinds.py`: the world's own piece kinds and resources (`piece_kinds`, `resources` in the world file), compiled into one `kinds_declared` event and held in `state.kinds`. Rules ask what a piece is only through `kinds.domain()` and `kinds.is_force()`, and which resources play a role through `kinds.with_role()`; a world with no `piece_kinds` keeps the five feature kinds.
- `src/revisionist/core/realism/locks.py`: deciders and locks (DCD, LCK, ASK), read only with the `locks` rule on. `lock_for()` (`src/revisionist/core/realism/locks.py:229`) is the pure function from state, a seat and an order (form or written) to the row that holds it and its decider; `seen_lock()` (`src/revisionist/core/realism/locks.py:359`) is the same read from what the seat can see, and `reason()` words it for the seat. `HeldOrder` is the stored held order; `ask()` (`src/revisionist/core/realism/locks.py:517`) and `open_now()` (`src/revisionist/core/realism/locks.py:550`) are the ask and the lock's condition read from state. `route.held()` (`src/revisionist/core/realism/route.py:103`) is the hook each filing path calls after today's refusals; `realism_tick._unlocked()` (`src/revisionist/engine/realism_tick.py:667`) lands or fails the held orders each world day and `realism_tick.ask_order()` (`src/revisionist/engine/realism_tick.py:728`) files an ask. With `deciders` on, `rows_on()` gives the rows that put a kind of question to a nation's decider, and a row naming a question or a council is decided as a matter (`matters_due()`, `matter_granted()`), each member's choice filed by `realism_tick.choose_matter()`.
- `src/revisionist/core/realism/offers.py`: the priced move (PRC), read only with the `offers` rule on (and `groups` and `laws`). A chamber's bloc carries `prices`; `offer()` (`src/revisionist/core/realism/offers.py:241`) checks a seat's offer of one price to one bloc of its own nation for a law whose bill is on its way, and `realism_tick.make_offer()` (`src/revisionist/engine/realism_tick.py:787`) logs it sealed to that nation's seats. `batch()` (`src/revisionist/core/realism/offers.py:304`) settles a day's filings by content, `points()` (`src/revisionist/core/realism/offers.py:212`) is what the votes rule adds to the bloc's part of the count, and `walk()` (`src/revisionist/core/realism/offers.py:379`) lapses an offer whose measure failed, sets the due day of one that passed and judges the promise on that day.
- `src/revisionist/core/realism/pipelines.py`: with the `command` rule on (CMD), `under_issuer()` (`src/revisionist/core/realism/pipelines.py:94`) and `step_allowed()` (`src/revisionist/core/realism/pipelines.py:103`) limit a commander's step on his superior's order to pass or stall, and `held_due()` passes it unanswered on its due day; `_superior_order()` (`src/revisionist/core/realism/pipelines.py:503`) finds the superior's order on a shared force, and the lower one is settled as replaced. A card's `path` is in `src/revisionist/core/realism/card.py`.
- `src/revisionist/engine/catchup.py`: the catch-up seam. `seat_events()` (`src/revisionist/engine/catchup.py:259`) is the one fog path every feed reads; every event kind is listed in `FEED_KINDS` (`src/revisionist/engine/catchup.py:42`) or `NEVER` (`src/revisionist/engine/catchup.py:84`). `news_reported`, `request_answered` and `step_chosen` are never fed; a routed order is fed as its issuer's view, without the engine's `ask`, estimate or held answer.
- `src/revisionist/engine/estimate.py`: the estimator (`CALL_CLASS = "estimator"`, `src/revisionist/engine/estimate.py:43`). `aide_orders()` (`src/revisionist/engine/estimate.py:164`) names the orders an aide filed for an absent seat; a `Deal` the estimator rules on one of them is dropped.
- `src/revisionist/engine/wake_report.py`: the read-only report behind `db wake-report` (section 2). `build()` (`src/revisionist/engine/wake_report.py:92`), `render()` (`src/revisionist/engine/wake_report.py:182`), `lines()` (`src/revisionist/engine/wake_report.py:219`). Nothing a seat reaches imports it.
- `src/revisionist/engine/odds.py`: the odds spread (the `odds` action, spec section 10). `picture()` reads the seat's own pieces exactly and the enemy only from `View.reports` for the area; `spread()` runs `battle.simulate` `ODDS_RUNS` times over `ODDS_DAYS` days from a seed of the campaign, the wake, the seat and the request's inputs, and returns the shares of win, stalemate and loss, the loss ranges, the chance and median days of taking the territory, the chance of being forced back and where, the win share at each reported strength, and the report keys used; with no report there, the terrain only. `Service` bounds odds work for the whole server: a fixed worker pool, a bounded queue that answers busy, a cache for the wake, one computation for identical requests in flight, and 30 requests a minute a seat. `ended()` gives each battle the seat's nation fought that has ended its closing odds: as they truly stood on its first day beside what the seat's own picture said, computed from the log's `battle_opened` and listed in the `battles` block after the open ones.
- `src/revisionist/engine/withdraw.py`: taking back a seat's own order (the `withdraw` action, section 5). `refusal()` (`src/revisionist/engine/withdraw.py:69`) says why an order cannot be withdrawn now, `withdrawable()` (`src/revisionist/engine/withdraw.py:77`) lists the ones that can, and `withdraw_order()` (`src/revisionist/engine/withdraw.py:89`) lands `order_settled` as withdrawn. An order qualifies while the wake it was filed in is open, its seat has not committed and it is still at its first step; after the commit or the close it stands and a recall is a new order.
- `src/revisionist/engine/openrouter.py`: `OpenRouterTransport` (`src/revisionist/engine/openrouter.py:187`), the free-models-only transport for `--transport openrouter`: model ids `:free` only, usage guarded, the key from `REVISIONIST_OPENROUTER_KEY` (`KEY_ENV`, `src/revisionist/engine/openrouter.py:42`), per-kind models from `REVISIONIST_OPENROUTER_MODELS` (`MODELS_ENV`, `src/revisionist/engine/openrouter.py:43`). `src/revisionist/engine/transport_check.py`: the check behind `web check-transport` (`openrouter()` `src/revisionist/engine/transport_check.py:119`, `run()` `src/revisionist/engine/transport_check.py:92`, `exit_code()` `src/revisionist/engine/transport_check.py:97`).

Realism:
- `src/revisionist/engine/realism_tick.py:135` `run_realism_tick(..., prose=writer)` (the web `advance` passes one too; see section 5): stages ADVANCE, PIPELINES, RESOLVE, FEEDS, then PROSE when a writer is passed (`play_tick` always passes one). PROSE gathers pages issued since the last `tick_closed` without prose, groups them by author, makes one writer call per author, drops prose that states a figure the page lacks (`core/realism/prose.invented_numbers`), and lands `document_written` events with their own `tick_stage_completed`. A `TransportError` leaves the pages bare and the tick still closes; call costs go on `tick_closed.costs`.
- `src/revisionist/engine/prose.py:53` `ProseWriter` protocol (takes `DocumentView`s and an `Author`, never `State`), `src/revisionist/engine/prose.py:146` `ClaudeProseWriter`, `src/revisionist/engine/prose.py:223` `TemplateProseWriter`. Prompt `src/revisionist/engine/prompts/document_prose.md`.
- `src/revisionist/engine/counsel.py:130` `consult()`: counsel; prompt `src/revisionist/engine/prompts/counsel.md`.
- `src/revisionist/engine/aide.py:319` `aide_for()`, `src/revisionist/engine/aide.py:222` `brief()`: the aide; prompt `src/revisionist/engine/prompts/aide.md`.
- `src/revisionist/engine/emit.py`: the envelope builder and log tail both tick orchestrators share (`Emitter` mints dense sequence numbers and folds each batch before it lands; `tail` reads the tick in progress, which is how a tick resumes after a crash). `src/revisionist/engine/ids.py`: mints IDs (outside the core because a ULID reads the clock).
- `src/revisionist/engine/prose_context.py`: why a page is written, read from state and handed to the prose writer as plain data on the `Author` block. `src/revisionist/engine/expects.py`: screens the `expects` and `risks` a model option may carry against the targets the seat's view holds.
- `scripts/prose_ab.py --live`: the P0 prose A/B (two models, five pages, blind sheet and separate key). Refuses without `--live`.

Briefings and reads:
- `src/revisionist/engine/play.py:116` `get_briefing()`: agent briefing for a seat (model call through the transport).
- `src/revisionist/engine/advise.py:21` `advise()`: DM question to the agent (`AGENT_MODEL` from `src/revisionist/engine/agent.py`).
- `src/revisionist/engine/play.py:136` `dashboard_lines()`, `src/revisionist/engine/play.py:186` `status_lines()`. `src/revisionist/core/dashboard.py:38` `dashboard()`.
- `src/revisionist/core/dossier.py:52` `dossier()`. `src/revisionist/core/orders.py:57` `order_results()`.
- `src/revisionist/engine/campaign.py:226` `briefings_dir()`. `src/revisionist/engine/campaign.py:208` `FileDeliverer`.

Contests and the referee:
- `src/revisionist/core/referee.py:224` `validate()`, `src/revisionist/core/referee.py:306` `rate()` (feasibility band), `src/revisionist/core/referee.py:481` `roll()`, `src/revisionist/core/referee.py:788` `admissible()`, `src/revisionist/core/referee.py:864` `reveal()`.
- `src/revisionist/core/contest.py:42` `momentum_moves()`, `src/revisionist/core/contest.py:63` `decisions()`. A contest is decided when its countdown runs out.
- `src/revisionist/core/history.py:35` `settle()`: scheduled history events.
- `src/revisionist/core/fold.py:107` `apply()`, `src/revisionist/core/fold.py:119` `replay()`, `src/revisionist/core/fold.py:130` `replay_to()`, `src/revisionist/core/fold.py:99` `state_hash()`. The reducer everything agrees on.

Establish, start, retire:
- `src/revisionist/engine/campaign.py:85` `world_path()`, `src/revisionist/engine/campaign.py:96` `load_world()`, `src/revisionist/engine/campaign.py:100` `new_campaign()`. Events come from `src/revisionist/core/world_compile.py:127` `compile_world()`. `src/revisionist/core/world_compile.py:268` `check_history()`.
- `src/revisionist/engine/pitch.py:183` `read_pitch()`: pitch → 2–3 start points (model; `PITCH_MODEL` at `src/revisionist/engine/pitch.py:19`).
- `src/revisionist/engine/session_zero.py:140` `draft_world()` (model via `src/revisionist/engine/draft.py:208` `draft()`), `src/revisionist/engine/session_zero.py:161` `establish()`, `src/revisionist/engine/session_zero.py:187` `propose()`, `src/revisionist/engine/session_zero.py:196` `confirm()`.
- `src/revisionist/engine/session_zero.py:1081` `begin()`: closes Session Zero and starts play.
- `src/revisionist/engine/session_zero.py:1056` `flagged()`, `src/revisionist/engine/session_zero.py:1070` `approve()`: balance flags.
- `src/revisionist/engine/season.py:46` `end_season()` (full reveal, ticks stop; winners from `goals.season_winners`), `src/revisionist/engine/season.py:75` `report()`; `src/revisionist/engine/season.py:30` `last_deciding_day()` and `src/revisionist/engine/season.py:39` `due()`: with `aims` on the season ends on the last deciding day.
- Retire: `src/revisionist/engine/scheduler.py:216` `ScheduleTable.retire()`; Discord handler `src/revisionist/engine/discord/handlers.py:516`.

Seats:
- `src/revisionist/engine/campaign.py:117` `human_seats()`, `src/revisionist/engine/campaign.py:122` `human_seat()`, `src/revisionist/engine/campaign.py:135` `resolve_seat()` (ID or name), `src/revisionist/engine/campaign.py:145` `faction_seats()`.
- `src/revisionist/engine/session_zero.py:405` `claim()`, `src/revisionist/engine/session_zero.py:445` `search()`, `src/revisionist/engine/session_zero.py:650` `pick()` (a real person from the record).
- `src/revisionist/engine/host_ops.py:182` `link_seat()`, `src/revisionist/engine/host_ops.py:207` `unlink_seat()`.
- `src/revisionist/engine/discord/tables.py:43` `SeatLinks` (`link` `src/revisionist/engine/discord/tables.py:47`, `unlink` `src/revisionist/engine/discord/tables.py:67`, `users` `src/revisionist/engine/discord/tables.py:96`). `src/revisionist/engine/discord/tables.py:129` `Invites` (`issue` `src/revisionist/engine/discord/tables.py:135`, `redeem` `src/revisionist/engine/discord/tables.py:146`).

Goals and mandates:
- `src/revisionist/engine/session_zero.py:800` `propose_goals()` (routes: history, could_have, own), `src/revisionist/engine/session_zero.py:908` `confirm_goal()`, `src/revisionist/engine/session_zero.py:987` `history_brief()`, `src/revisionist/engine/session_zero.py:1024` `design_agent()`.
- `src/revisionist/core/goals.py:585` `check()` (progress, met, undone), `src/revisionist/core/goals.py:776` `season_winners()` (with `aims` on, the seats whose person has two aims holding; `aim_goals()` `src/revisionist/core/goals.py:731` makes a person's aims into goals once, `aim_status()` `src/revisionist/core/goals.py:676` reads met, at risk or failed from state), `src/revisionist/core/goals.py:938` `balance()` (flags goals too strong for a seat's power).
- The player's own aim (`own_aim`): `src/revisionist/core/aim_patterns.py:550` `fill()` checks a pattern filled from the seat's view, `src/revisionist/core/aim_patterns.py:601` `ladder()` lists the patterns a seat's post may use, easiest first, `src/revisionist/core/aim_patterns.py:579` `own_aim_set()` makes the event, and `src/revisionist/engine/realism_tick.py:743` `set_own_aim()` logs it.
- Mandates: `MandateKind` and the mandate triggers are in `src/revisionist/core/realism/agenda.py` (imported by `src/revisionist/core/world.py`). The seat's own mandates are projected in `src/revisionist/core/project.py`. The web agenda shows them (section 5). Goals are the separate secret-goal system above.

Leak scan:
- `src/revisionist/core/canary.py:83` `scan()`, `src/revisionist/core/canary.py:48` `scan_text()`, `src/revisionist/core/canary.py:107` `scan_deliveries()`, `src/revisionist/core/canary.py:196` `scan_humans()` (per person across seats).
- `src/revisionist/core/report.py:141` `leak_report()`. `src/revisionist/engine/host_ops.py:112` `leak_lines()`. `src/revisionist/cli.py:674` `leaks`.

Model (LLM) calls:
- `src/revisionist/engine/llm.py:97` `ClaudeCli`, `call()` at `src/revisionist/engine/llm.py:113`: the only live transport. Runs `claude -p` with no settings sources and no tools (`src/revisionist/engine/llm.py:113-135`). Strips `REVISIONIST_*` from the child env (`src/revisionist/engine/llm.py:138`).
- `src/revisionist/engine/llm.py:93` `Transport` protocol, `src/revisionist/engine/llm.py:55` `Request`, `src/revisionist/engine/llm.py:73` `Reply`.
- `src/revisionist/engine/llm.py:235` `RecordedTransport`: replays `tests/recordings/`.
- `src/revisionist/engine/llm.py:394` `ClaudeResolver` (call class `resolver`, `RESOLVER_MODEL` `claude-sonnet-5-5` at `src/revisionist/engine/llm.py:35`).
- `src/revisionist/engine/llm.py:501` `ClaudeNarrator` (call class `narrator`, `NARRATOR_MODEL` `claude-haiku-5-5` at `src/revisionist/engine/llm.py:36`).
- Other call classes: `session_zero` (`src/revisionist/engine/session_zero.py:112`), `character_search` (`src/revisionist/engine/session_zero.py:470`), `character_record` (`src/revisionist/engine/session_zero.py:539`), `draft_{stage}` (`src/revisionist/engine/draft.py:146`), `pitch` (`src/revisionist/engine/pitch.py:193`), `counsel` (`src/revisionist/engine/counsel.py:106`), `prose` (`src/revisionist/engine/prose.py:156`), `aide` (`src/revisionist/engine/aide.py:238`, `src/revisionist/engine/aide_help.py:117`, `src/revisionist/engine/directive.py:143`), `cast` (`src/revisionist/engine/cast.py:71`), `build` (`src/revisionist/engine/build.py:127`), `held_power` (`src/revisionist/engine/timeline.py:98`), `aide` for the order reader (`src/revisionist/engine/orders_reader.py:34`), `options` (`src/revisionist/engine/options.py:51`), `estimator` (`src/revisionist/engine/estimate.py:41`).
- Offline providers: `src/revisionist/engine/providers.py:28` `ScriptedResolver`, `src/revisionist/engine/providers.py:66` `TemplateNarrator`, `src/revisionist/engine/providers.py:90` `KeywordSafety`. Used when `offline` is set (`src/revisionist/engine/runner.py:101`).
- Cost: `src/revisionist/engine/campaign.py:154` `log_cost()`. `src/revisionist/core/report.py:47` `cost_report()`.

Store and event log:
- `src/revisionist/engine/store.py:33` `EventStore` protocol, `src/revisionist/engine/store.py:103` `load_state()`, `src/revisionist/engine/store.py:123` `MemoryStore`, `src/revisionist/engine/store.py:196` `SqliteStore`.
- `src/revisionist/engine/pg_store.py:29` `PostgresEventStore`. `src/revisionist/engine/campaign.py:56` `open_store()` chooses between them.
- `src/revisionist/engine/maintenance.py:32` `verify_campaign()`, `src/revisionist/engine/maintenance.py:72` `copy_campaign()`. `src/revisionist/engine/host_ops.py:225` `replay_line()`, `src/revisionist/engine/host_ops.py:238` `verify_lines()`.

Sealing:
- `src/revisionist/engine/seal.py:84` `KeyringSealer`, `src/revisionist/engine/seal.py:255` `PgKeyring`, `src/revisionist/engine/seal.py:248` `new_master_key()`, `src/revisionist/engine/seal.py:232` `load_master_key()`, `src/revisionist/engine/seal.py:330` `destroy_key()`.

### Rule modules

`src/revisionist/core/realism/` holds the rules of the realism game: pure functions of state, no I/O. Each file below, with its first docstring line.

- `actors.py`: Seats for the people nobody plays, so their acts go through the same routing as a player's.
- `advance.py`: The event-driven advance (plan, Phase 2 unit B1).
- `agenda.py`: The agenda, play styles and the options a seat is offered (engine v2; spec §8.5-8.6).
- `agreement.py`: Agreements with clauses the rules can check (AGR).
- `answer.py`: What a person nobody plays does back (strategy step 2).
- `answering.py`: People nobody plays answer what is done to them (strategy step 2).
- `apply.py`: Applying a part's effects to the world (engine v2, spec §8.2-8.3).
- `arrivals.py`: What a force's arrival sets going: the commanding seat's report of it (spec §8.3).
- `bases.py`: Reach: how far a side can hold a force from its bases (reach, R2).
- `battle.py`: Battles that last several days, one round a day (BTL).
- `card.py`: Seat cards: one record per person, for every office (pillar 2).
- `check.py`: Gaps in a world file: what is still unsourced, before anyone plays it.
- `conference.py`: The conference: seats vote on a text, votes sealed ahead (CNF).
- `contests.py`: Contests that move and decide (CON).
- `detachments.py`: Detachments (reach R4): part of a force sent off as a force of its own, and its return.
- `detect.py`: Detection: every known enemy piece is a report (DET).
- `document.py`: Documents: every metric reaches a person as a report (pillar 3).
- `economy.py`: What a territory yields, and one war-economy figure per nation (YLD).
- `effect.py`: The effect vocabulary, routes and fidelity (engine v2; spec §8.2-8.3).
- `feeds.py`: Feeds: documents that report the truth through an author's bias (pillar 3).
- `geography.py`: Geography: forces, fronts and routes on the map (realism, Batch 6).
- `groups.py`: Groups at home, defined by the world (GRP).
- `holders.py`: Who holds each territory, and capture that takes time (THL).
- `kinds.py`: What a piece is and what a resource is for: the world names them, the engine reads roles.
- `land/allocate.py`: Landing an Allocate effect in the world: a quantity moves between polities, and the recipient's receipt is always recorded as a private fact.
- `land/appointment.py`: Landing an Appointment effect in the world: a public office fact and public news.
- `land/deal.py`: Landing a Deal effect in the world: an offer is recorded to its issuer; an accepted deal records its terms and moves the relationship between the two parties.
- `land/investigate.py`: Landing an Investigate effect: a private report of what the issuing seat already sees, or, for an intelligence order, a reconnaissance flight or an agent placed (IOR).
- `land/statement.py`: Landing a MakeStatement effect in the world.
- `laws.py`: Laws as world data (LWC).
- `locks.py`: Deciders and what locks an order (DCD).
- `mandates.py`: The agenda (engine v2, spec §8.5).
- `opponents.py`: Who stands where toward each seat, and who is actively opposing it.
- `pass_world.py`: The world as it stands mid-pass, shared by `apply` and the `land` modules.
- `person.py`: `project_person(state, person, asker) -> PersonView`: what one person on a card knows when a seat consults them.
- `pipeline.py`: Orders as pipelines (pillar 4).
- `pipelines.py`: Running orders through their pipelines (plan, Phase 2 unit B2).
- `press.py`: Each seat's press: public news worded in its own outlet's voice (engine v2, consequences).
- `process.py`: Process and influence parts (engine v2, spec §8.2).
- `prose.py`: The prose post-check: a written page may state no figure its page does not.
- `quantity.py`: Quantities: the numbers outcomes are computed from (pillar 6).
- `reach.py`: Reach: who a person can get word to, by which channel, and how fast (spec §8.1, §8.4).
- `resolvers/evacuation.py`: The evacuation order (EVC), under the rule name `economy`.
- `resolvers/intel.py`: The intelligence orders from a form (INT): a lever whose rule name is `intel`.
- `resolvers/movement.py`: The movement resolver (realism, Batch 6; the fifth, by Josh's word).
- `resolvers/opinion.py`: The opinion resolver (plan, Phase 2 unit B3).
- `resolvers/production.py`: The production resolver (plan, Phase 2 unit B3; PRD).
- `resolvers/production_stored.py`: The Autumn 1941 names the production rules keep for a stored game (PRL).
- `resolvers/shipping.py`: The shipping resolver (plan, Phase 2 unit B3).
- `resolvers/trade.py`: Embargo and trade orders (EMB), under the rule name `trade`.
- `resolvers/votes.py`: The votes resolver (plan, Phase 2 unit B3).
- `resolvers/war.py`: The war resolver: what a declaration of war sets going.
- `route.py`: The router and the command path (engine v2; spec §8.1-8.2).
- `routing.py`: Sea routing: how far a fleet sails between two places (reach, R3).
- `sealift.py`: Sealift (reach, R6): an army crosses the sea only on its side's shipping.
- `stance.py`: Where a person nobody plays stands toward a seat: five stances, from a score.
- `supply.py`: Supply: pieces operate only within reach of the rail and ports their side holds (SUP).
- `territory.py`: The board a world file defines: regions, territories, sea zones and who borders whom.
- `trade.py`: Fuel and trade: oil is spent to move, and a trade line can be cut (FUL).
- `war.py`: Wars, public news and the papers that print it (engine v2, consequences).
- `war_rules.py`: What a state of war allows and forbids, and what it sets in motion.
- `war_rules_stored.py`: The Autumn 1941 names the war rules keep for a stored game (WRL).

### Rules a world switches on

`rules:` in a world file names the rules the world plays by (`Rule` in `src/revisionist/core/state.py`). A rule that is not named does not act, so a stored game and a world that names none behave as before. Each rule checks its name before it acts.

- `territories`: the board; areas, adjacency and pieces that stand in one area (`territory.py`). The others below need it.
- `holders`: who holds each territory, and capture that takes time (`holders.py`). Needs `territories`.
- `economy`: yields, pools and one public figure per nation (`economy.py`). Needs `holders`.
- `supply`: a piece operates only within reach of the rail and ports its side holds (`supply.py`).
- `fuel`: oil spent to move, trade lines that can be cut (`trade.py`). Needs `economy`.
- `battles`: fights that last several days, one round a day (`battle.py`).
- `reports`: an enemy piece is known only as a report (`detect.py`).
- `groups`: groups at home, whose support moves by happenings, writing and the weekly cap (`groups.py`).
- `agreements`: offers with clauses the rules can check (`agreement.py`).
- `conference`: a vote on a text with votes sealed ahead (`conference.py`).
- `contests`: contests that move and decide (`contests.py`).
- `aims`: the seat's aims are its win, scored in degrees (`agenda.py`, `core/goals.py`).
- `aid`: aid drawn from a nation's production that arrives after a lead time (`resolvers/production.py`, `land/allocate.py`). Named in the world file; the aid code reads `economy`.
- `writing`: free writing moves groups; leans on a live model's reading, off in every shipped world.
- `clause_reader`: treaty and bill wording read into clauses by a live model; off in every shipped world.
- `written_orders`: written orders checked against their form by a live model; off in every shipped world.
- `command`: the commander's seat, a card's path, the superior prevailing, and the step that may only pass or stall (`card.py`, `pipelines.py`, `resolvers/movement.py`).
- `locks`: orders held until the person or body that can allow them does (`locks.py`, `engine/web/locks_api.py`).

The third run declares sixteen more names, each read by a later item; until its reader is built a name does nothing, and no shipped world names one:

- `laws`: laws declared by the world (`laws.py`, `laws.in_force()`), read by locks; votes and shipping read them once the rules lane's half is built.
- `ask_answers`: an ask to a decider nobody plays is answered by its card on a due day (`answering.answer_ask()`), and a grant files the decider's own order.
- `deciders`: locks decided by the kind of question, and by a council (`locks.rows_on()`, `locks.matters_due()`, `locks.matter_granted()`; a seat chooses on a matter by `realism_tick.choose_matter()`).
- `own_aim`: the player's own aim, filled from the world's patterns and scored (`aim_patterns.py`, `aim_patterns.fill()`, `aim_patterns.ladder()`).
- `offers`: a priced offer to a bloc, with a promise that comes due (`offers.py`, `offers.points()`; a seat offers by `realism_tick.make_offer()`).
- `classes`: every happening has a class: felt, reported or secret.
- `losses`: the size of losses moves the mood at home.
- `places`: places with political weight: lost, abandoned or retaken.
- `posts`: player, person and post kept apart, and the ladder of posts.
- `office`: the office question as a formal sitting, and blocs turning on the leader.
- `elections`: elections redraw a chamber.
- `defiance`: acting without permission, and refusing an order from above.
- `aide_note`: the aide's note of what waits for the seat.
- `peace`: an armistice and its terms end a war.
- `post_view`: a commander's view limited to his post.
- `playable_rule`: who can be played comes from a rule over the cards.

### Event kinds

`src/revisionist/core/events.py` holds 117 event kinds. Every one is in exactly one of `FEED_KINDS` or `NEVER` in `src/revisionist/engine/catchup.py`, and `tests/test_catchup.py` checks that split and the fog on the fed ones. The lists below are copied from those two sets.

- Fed to a seat through `seat_events()`, after its own view cuts them (51): `agreement_made`, `agreement_offered`, `agreement_published`, `area_held`, `ask_answered`, `asset_created`, `briefing_delivered`, `clause_judged`, `clock_created`, `commitment_created`, `conference_called`, `conference_tallied`, `contest_created`, `contest_decided`, `contest_moved`, `date_advanced`, `divergence_changed`, `document_issued`, `document_written`, `effects_applied`, `entity_created`, `fact_asserted`, `goal_met`, `goal_progressed`, `goal_set`, `goal_undone`, `held_order_ended`, `influence_decided`, `kinds_declared`, `locks_declared`, `mandate_issued`, `mandate_settled`, `map_declared`, `meter_created`, `narration_written`, `order_asked`, `order_drafted`, `order_executed`, `order_held`, `order_routed`, `order_settled`, `order_step_taken`, `piece_stepped`, `quantity_set`, `relationship_set`, `scheduled_event_fired`, `season_ended`, `statement_issued`, `step_refused`, `wake_opened`, `war_declared`.
- Never fed (68): `admin_read`, `agent_assigned`, `agent_set`, `answer_made`, `answer_planned`, `battle_decided`, `battle_ended`, `battle_opened`, `battle_round`, `campaign_created`, `capture_counted`, `card_amended`, `cards_declared`, `character_claimed`, `character_listed`, `character_released`, `clarification_asked`, `codebreaking_set`, `cost_logged`, `counsel_held`, `delta_applied`, `delta_proposed`, `delta_rejected`, `directive_given`, `document_flagged`, `document_read`, `economy_set`, `effects_estimated`, `feasibility_rated`, `feature_set`, `goal_approved`, `goal_proposed`, `group_moved`, `group_proposed`, `groups_declared`, `intelligence_declared`, `intent_filed`, `intent_rejected`, `matter_chosen`, `news_reported`, `operation_opened`, `operation_resolved`, `opponents_ranked`, `options_offered`, `order_received`, `play_style_set`, `report_made`, `request_answered`, `rolled`, `scheduled_event_created`, `scheduled_event_skipped`, `sealed`, `seat_created`, `seat_handover`, `seat_status_set`, `session_zero_closed`, `session_zero_opened`, `settings_set`, `stance_changed`, `step_chosen`, `tick_closed`, `tick_opened`, `tick_stage_completed`, `trade_set`, `vote_sealed`, `wake_closed`, `wake_committed`, `yield_changed`.

### Scripts

Build-time tools; the game never imports them.

- `scripts/map_build.py` (`python scripts/map_build.py build worlds/maps/src/<slug>`, run with `uv run --group map`): builds a map file, its world fragment and its map object from a recipe and the cached Natural Earth files in `REVISIONIST_MAP_DATA`, each checked against the SHA-256 in `worlds/maps/SOURCES.md`.
- `scripts/map_check.py` (`check MAP.json`, `check --world WORLD.yaml`, `check --region STAGING.yaml`, `adjacency MAP.json`, `render MAP.json`): the map file checker, the one adjacency predicate the build also uses, and the proof sheet.
- `scripts/world_check.py` (`uv run python scripts/world_check.py WORLD [WORLD ...]`, `--keys`): reads `worlds/TEMPLATE.md` and a world, and prints for each of the template's questions whether the world answers it, marks it a gap, leaves it absent, or leaves it absent while a rule it switches on needs it (exit status 1); `--keys` lists the keys the world loader accepts that no row of the template names.
- `scripts/ci_changes.py`: reads changed paths and says whether CI needs the Python tests and the browser test. `scripts/ci_shard.py` (with `scripts/ci_timings.json`): prints the test files of one CI shard. `scripts/ci_pg_client.sh`: the Postgres client tools for CI.
- `scripts/make_web_icons.py` (`python scripts/make_web_icons.py <logo image>`, from the repo root; needs Pillow, which the project does not install): cuts the web client's install icons in `web/icons/` from the square logo file and keeps the source as `web/icons/logo-1024.png`. Run by hand when the logo changes; the game never runs it.
- `scripts/prose_ab.py`: the same five pages written by two models for a blind read; makes live model calls and refuses to run without `--live`.

### Designed and not built

Deception (feints and false radio traffic) is designed and not built. The design note is `kedartech/revisionist/plans/2026-11-17-revisionist-second-run-interface-design.md`, section "Deception (designed, not built)", in the cherith-labs vault. No code, event kind, rule name or action here belongs to it.

## 5. Web/JSON API and client
Backend package: `src/revisionist/engine/web/`. Stdlib `ThreadingHTTPServer` (`src/revisionist/engine/web/server.py:1386` `serve()`), plain HTTP. Bind to a private address.

Modules:
- `src/revisionist/engine/web/server.py`: the HTTP server. `App` (`src/revisionist/engine/web/server.py:138`) holds the DSN, static dir, transport, clock and `offline_prose`; `make_handler()` (`src/revisionist/engine/web/server.py:1139`) builds the request handler. Serves `web/` and the JSON routes below.
- `src/revisionist/engine/web/handlers.py`: `WebHandlers(Handlers)` (`src/revisionist/engine/web/handlers.py:30`). Reuses the Discord command code; the seat is looked up in `web_seats`, not `discord_seats`.
- `src/revisionist/engine/web/guard.py`: the request guard, the one place the server's headers and write checks live: `headers()`, `json_headers()`, `static_headers()` (with `static_cache()`), `map_headers()`, `compress()` (a JSON or static reply over `GZIP_MIN` = 1,024 bytes is gzipped when the request accepts gzip, with `Content-Encoding` and `Vary`), `assetlinks()`, `cookie()`, `served()` (called first in `do_GET` and by `same_origin()`: with `REVISIONIST_PUBLIC_NAMES` set, a Host not on it is a 421), `same_origin()` and `body()` (with `json_body()`); a turned-away request raises `RefusedError`, which `do_GET` and `do_POST` answer as they answer `ApiError`. `src/revisionist/engine/web/limits.py`: what costs money, counted in `web_limit_hits` (migration 0014) so a restart forgets nothing: `check()` counts each player action that calls a model against its hourly line per account (`LINES`, `COUNTED`) and, past the game's dollar ceiling for the wake on player-triggered calls (`CEILING_USD`, `spent()`), returns `TemplateMode` for the aide's brief and help desk (honoured in `App.realism`) or refuses written orders and counsel; `address()` limits sign-up, sign-in and recovery per address (`ADDRESS_LINES`; the forwarded address only with `REVISIONIST_TRUST_PROXY=1`); `SigninThrottle` (the per-handle sign-in and recovery throttle, held as `App.signin`, stored). A refusal is sent as a reply with `refused: true` (status 200), never as an error. `App.limited()` calls `check(store, account_id, None, "<family>/<action>", clock())` at the top of `App.realism`, `App.game` and `App.new_game` and in the `/api/seat/` dispatch before the action runs; the handler calls `address(handler, what)` first in sign-up, sign-in and recovery (`what` is `signup`, `signin` or `recover`). `server.py` names no header and no limit (`tests/test_web_seams.py`).
- `src/revisionist/engine/web/accounts.py`: accounts, sessions, recovery codes and web-held seats. Scrypt password hashes (`hash_password()`, `src/revisionist/engine/web/accounts.py:44`); `Accounts` (`src/revisionist/engine/web/accounts.py:92`), `WebSeats` (`src/revisionist/engine/web/accounts.py:217`).
- `src/revisionist/engine/web/snapshot.py`: the seat's JSON, built from its own view and log. `seat_snapshot()` (`src/revisionist/engine/web/snapshot.py:169`), `checked()` (`src/revisionist/engine/web/snapshot.py:299`, leak scan before sending; raises `WithheldError`, `src/revisionist/engine/web/snapshot.py:42`), `campaign_info()` (`src/revisionist/engine/web/snapshot.py:74`), `schedule_info()` (`src/revisionist/engine/web/snapshot.py:95`), `roster()` (`src/revisionist/engine/web/snapshot.py:103`).
- `src/revisionist/engine/web/held.py`: orders a seat gives after it has committed, or while its wake is closing, kept in `web_held_orders` until the next wake opens (`hold()` `src/revisionist/engine/web/held.py:135`, `listing()` `src/revisionist/engine/web/held.py:163`, `drop()` `src/revisionist/engine/web/held.py:189`, `clear()` `src/revisionist/engine/web/held.py:214`, `file_one()` `src/revisionist/engine/web/held.py:235`, `file_held()` `src/revisionist/engine/web/held.py:269`; `closing()` `src/revisionist/engine/web/held.py:98` is true only while a close of the campaign's wake is running; a leave, a join or a scheduler pass that closes nothing does not count). `src/revisionist/engine/web/catchup_api.py`: the `catchup` action's pages, `reply()` (`src/revisionist/engine/web/catchup_api.py:100`). `src/revisionist/engine/web/playback.py`: the playback feed, each page's `steps`, `steps()` (`src/revisionist/engine/web/playback.py:191`), built from the catch-up seam's events alone; only the kinds in `STEP_KINDS` make a step.
- `src/revisionist/engine/web/court.py`, `people.py`, `stakes.py`, `threats.py`, `destinations.py`: the court, People roster, stakes and opponents lists of `view.realism`, and where a movement form can send a force; each reads one seat's own `View`.
- `src/revisionist/engine/web/realism_api.py`: TypedDict shapes for the realism JSON: documents, desk, situation, orders, map, wake, agenda, reach, reveal and record. Types only.
- `src/revisionist/engine/web/realism_snapshot.py`: builds the realism shapes from one seat's `View`: `seat_realism()` (`src/revisionist/engine/web/realism_snapshot.py:559`), `documents()` (`src/revisionist/engine/web/realism_snapshot.py:126`), `situation()` (`src/revisionist/engine/web/realism_snapshot.py:185`), `desk()` (`src/revisionist/engine/web/realism_snapshot.py:415`), `orders()` (`src/revisionist/engine/web/realism_snapshot.py:389`), `clock()` (`src/revisionist/engine/web/realism_snapshot.py:396`), `seat_map()` (`src/revisionist/engine/web/realism_snapshot.py:289`).
- `src/revisionist/engine/web/economy_api.py`: holders and the war economy as the seat sees them. `Holdings` gives a land area its holder keys for one seat (`MapNation`: key, name, and `own`, `ally`, `enemy` or `neutral`); `block()` builds the seat's `economy` block with `economy` on: every nation's public figure (`economy.figure`), and for the seat's own nation only its income by resource with the world's names and units, its pools (with `fuel` on, the fuel stock too, read from its own view), `fuel_months` (the stock over a month's fuel income, trade lines included; null with `fuel` off or no income) and each held territory's yields and factors by role. Read from the seat's `View`, which holds no other nation's pools or moved yields.
- `src/revisionist/engine/web/battles_api.py`: battles as the seat sees them. `block()` builds the seat's `battles` block with `battles` on: each battle its nation is on, with the rounds from the seat's own round reports, its side's strength, the enemy range from its own sighting papers, the side's decision in force, the decisions it may give now and its own pieces there; never the enemy's true strength, a round's draws or the enemy's decision. `due()` lists the battles waiting on the seat's decision in the open wake, registered as the `battle` kind in `agenda_api.DUE_KINDS`. `battle_asks()` and `contingency_asks()` build the asks the `battle` and `contingency` actions file.
- `src/revisionist/engine/web/home_api.py`: groups at home and the floor as the seat sees them. `block()` builds the seat's `home` block with `groups` on: its own nation's groups (support, what last moved each and when, what each feeds), each chamber its blocs sit in with their seats and, for each measure the seat has on its way, the count by bloc from `votes.floor_counts` (the votes rule's own tally), the nation's themes, its standing at home as a figure, and every nation's standing as one of five public bands (`standing_band`). Read from the seat's `View`, which holds no other nation's groups.
- `src/revisionist/engine/web/agreements_api.py`: offering, answering, publishing and reading agreements (AGA). `offer_reading()` is the `agreement-offer` action: wording, clauses, the other parties and an optional envoy, each clause checked as the treaty reader checks one, held as a reading the seat signs with `file`. `publish_asks()` is the `agreement-publish` action's order. `offer_terms()` gives an offer's terms as signing and its agenda item show them (each clause in `agreement.render_clause`'s words, checked or not, the aide's interpretation or not, and the unchecked wording). `block()` builds the seat's `agreements` block with `agreements` on: every agreement its nation is party to and every public one, each clause's state and day, and its open offers, the seat's own showing each answer only once the due day decides it. Read from the seat's `View`.
- `src/revisionist/engine/web/locks_api.py`: the seat's locks and the check before sending (LKD). `block()` builds the seat's `locks` block with `locks` on (absent with it off): each of its own held orders with the order in plain words, who can allow it, the reason it was told, the day it was held and whether it has asked, and each ask put before it with the asker, the order's words, the day and the seat's own form that would allow it where the lock's row names one. `agenda_api.DUE_KINDS` lists each ask for the decider's wake notice. `check_form()` and `check_asks()` are the `check` action: the filing's own steps (`realism_tick.form_filing`, `realism_tick.written_filing`) run on the game as it stands, with nothing logged, so a lock on a fact the seat cannot see holds nothing and checks as allowed. Read from the seat's `View`.
- `src/revisionist/engine/web/conferences_api.py`: calling a conference and voting in it (CNA). `call_args()` and `call()` are the `conference-call` action (`{text, invited, voting_day, public?, key?, clauses?, unanimous?}`: the caller's own nation is always invited; `key` is a name the caller may vote by, and the conference is stored and shown under a key derived from it; the clauses are checked against the caller's view again when a held call lands; landed at once through `wake.call_conference`), `vote_args()` and `vote()` the `conference-vote` action (`{conference, vote}`, `conference` the stored key or the name the seat gave its own call: for, against or abstain, sealed to the seat through `wake.seal_vote`; a later vote in the same wake replaces the earlier). `items()` puts each conference the seat's nation votes in on its agenda as a `Vote` item due on the voting day, which `agenda_api.DUE_KINDS` lists for the wake notice without the vote. `block()` builds the seat's `conferences` block with `conference` on: the text, the invited, the voting day, the seat's own vote and, after the tally, the result and each nation's counted vote. Read from the seat's `View`.
- `src/revisionist/engine/web/map_api.py`: the map as the seat sees it in a territory game: `add_board()` (`src/revisionist/engine/web/map_api.py:86`) gives the `map` block its areas with their neighbours (each land area with its printed `yields` and, with `holders` on, its `holder`, `held_since`, `taken_from` and, for the holding nation's seats only, `falling`; a sea zone none), regions, coordinates, box and map file; `seat_board()` (`src/revisionist/engine/web/map_api.py:99`) cuts the truth down to what the seat knows (its own side's pieces, the quantities its view admits and its own nation's shipping), and `lit()` (`src/revisionist/engine/web/map_api.py:128`) gives each own piece's `moves` from `territory.plans` on that board, so an enemy the seat has no report of changes nothing; `map_reply()` (`src/revisionist/engine/web/map_api.py:150`) answers the `map` action.
- `src/revisionist/engine/web/wake_api.py`: the shared wake: `commit()` (`src/revisionist/engine/web/wake_api.py:129`), `close()` (`src/revisionist/engine/web/wake_api.py:153`), `advance()` (`src/revisionist/engine/web/wake_api.py:176`), `wake_header()` (`src/revisionist/engine/web/wake_api.py:66`), `set_wake_hours()` (`src/revisionist/engine/web/wake_api.py:168`).
- `src/revisionist/engine/web/agenda_api.py`: the agenda: live mandates, the options offered at wake open, and the play style. `agenda()` (`src/revisionist/engine/web/agenda_api.py:99`), `set_style()` (`src/revisionist/engine/web/agenda_api.py:138`), `pick_option()` (`src/revisionist/engine/web/agenda_api.py:156`), `answer()` (`src/revisionist/engine/web/agenda_api.py:318`: a holder's answer to another seat's request, stored sealed to the holder; see `answer` below). `requests()` (`src/revisionist/engine/web/agenda_api.py:265`) lists the requests put to the seat and `held_steps()` (`src/revisionist/engine/web/agenda_api.py:299`) a held decision waiting on the seat as its holder, each with an item id the seat's `answer` or `step` action accepts and never the issuer's order id. A picked option is filed through the ordinary order path.
- `src/revisionist/engine/web/forecast.py`: the forecast checked (`agenda.forecast` of `view.realism`): each of the seat's own orders that came from a suggested action, its expected moves judged held or missed once settled, 7 world days after the order is enacted, from the seat's own view, and whether its aide chose it; `judge()` and `tally()` also give `db wake-report` its forecasts line.
- `src/revisionist/engine/web/record_api.py`: the seat's record block, its orders and the latest wake: `record_block()` (`src/revisionist/engine/web/record_api.py:61`). Ledger keys become opaque tokens.
- `src/revisionist/engine/web/results.py`: how each routed order landed, spoken from the seat's own view: `results()` (`src/revisionist/engine/web/results.py:117`).
- `src/revisionist/engine/web/reach_groups.py`: who the seat can reach and how, in four groups: `reach()` (`src/revisionist/engine/web/reach_groups.py:30`).
- `src/revisionist/engine/web/reveal.py`: the end-of-game reveal: `build()` (`src/revisionist/engine/web/reveal.py:54`). The one read that does not pass `snapshot.checked`.
- `src/revisionist/engine/web/new_game_api.py`: a new realism game: `timeline()` (`src/revisionist/engine/web/new_game_api.py:19`), `figures()` (`src/revisionist/engine/web/new_game_api.py:27`), `start()` (`src/revisionist/engine/web/new_game_api.py:48`), `opening()` (the game's people by nation, path and person, from `roster.claimable` alone) and `ready_made()` (a game whose world was not drafted from a pitch: it refuses the who-held-power list and a name off its roster, so opening and claiming make no model call).
- `src/revisionist/engine/web/dossiers.py`: dossier and setting text from `worlds/dossiers/<world>.yaml`: `load()` (`src/revisionist/engine/web/dossiers.py:179`), `for_people()` (`src/revisionist/engine/web/dossiers.py:220`), `setting()` (`src/revisionist/engine/web/dossiers.py:242`).
- `src/revisionist/engine/web/tray.py`: in-tray rules the client cannot work out alone: `acknowledgement()` (`src/revisionist/engine/web/tray.py:14`) says which papers only acknowledge an order; `feed_group()` (`src/revisionist/engine/web/tray.py:32`) says which belong to a feed.
- `src/revisionist/engine/web/__init__.py`: the package docstring: accounts, web-held seats and the JSON API.

Routes (`src/revisionist/engine/web/server.py`):
- `do_GET` (`src/revisionist/engine/web/server.py:1003`):
  - `GET /api/me` (`src/revisionist/engine/web/server.py:1217`): `{"account": null}` if signed out, else `App.state_for()` (`src/revisionist/engine/web/server.py:203`).
  - `GET /maps/<sha256>.json`: the map object (`maps.map_object`) whose hash the signed-in account's game names, with `Cache-Control: private, max-age=31536000, immutable`; 401 signed out, 404 for any other hash. `GET /.well-known/assetlinks.json`: the file `REVISIONIST_ASSETLINKS_FILE` names, 404 when unset or unreadable. `.webmanifest` is served as `application/manifest+json`; `/sw.js` carries `Service-Worker-Allowed: /` and `no-cache`.
  - Other `GET /api/*` → 404 (`src/revisionist/engine/web/server.py:1013`). Any other `GET` → static file, or `index.html` for client routes (`src/revisionist/engine/web/server.py:1015`, `_static` at `src/revisionist/engine/web/server.py:1152`).
- `do_POST` (`src/revisionist/engine/web/server.py:1025`). Every write first runs `guard.same_origin()` and reads its body through `guard.body()`.
  - `POST /api/signup` (`src/revisionist/engine/web/server.py:1030` → `_signup` `src/revisionist/engine/web/server.py:1073`): 201 with session cookie and recovery codes.
  - `POST /api/signin` (`src/revisionist/engine/web/server.py:1032` → `_signin` `src/revisionist/engine/web/server.py:1092`).
  - `POST /api/recover` (`src/revisionist/engine/web/server.py:1034` → `_recover` `src/revisionist/engine/web/server.py:1115`).
  - `POST /api/signout` (`src/revisionist/engine/web/server.py:1036` → `_signout` `src/revisionist/engine/web/server.py:1140`).
  - `POST /api/signout-all` (`_signout_all`): needs a session; ends every session of the account (`Accounts.close_all()`).
  - `POST /api/seat/<action>` (`src/revisionist/engine/web/server.py:1038-1045`): needs a session, dispatches via `SEAT_ACTIONS` (`src/revisionist/engine/web/server.py:831`). Replies whose text is in `REFUSALS` (`src/revisionist/engine/web/server.py:912`) return `refused: true`.
  - `POST /api/new/<action>` (`src/revisionist/engine/web/server.py:1257` → `App.new_game()` `src/revisionist/engine/web/server.py:677`). Actions: `worlds` (`src/revisionist/engine/web/server.py:682`), `timeline` (`src/revisionist/engine/web/server.py:685`), `figures` (`src/revisionist/engine/web/server.py:687`; refused for a seat in a ready-made game), and the start of a game: `ready`, `pitch`, `cast`, `start` (`src/revisionist/engine/web/server.py:698`, refused for a seat already in a game), then `opening` (no lock, and only while the game chooses its people: the nations, paths and persons with taken marked, and the human seats left; in play it is refused as `pick` is), then, with the game's lock held, `pick`, `unpick`, `style` (`src/revisionist/engine/web/server.py:744-749`), and for the host `invite` and `begin` (`src/revisionist/engine/web/server.py:751-755`; `App._session_zero()` `src/revisionist/engine/web/server.py:731`).
  - `POST /api/game/<action>` (`src/revisionist/engine/web/server.py:1261` → `App.game()` `src/revisionist/engine/web/server.py:588`). Actions: `reveal` (`src/revisionist/engine/web/server.py:600`), `notice-address` (`{address?, zone?}`: read or set where the account's wake notices go; `src/revisionist/engine/web/server.py:602`, `src/revisionist/engine/notice.py` `address_action`), `leave` (a realism game in play: the leader is run by the code from the next wake; `src/revisionist/engine/web/server.py:612`, `src/revisionist/engine/wake.py` `leave`), `wake-hours` (`src/revisionist/engine/web/server.py:633`), `pause` (`src/revisionist/engine/web/server.py:639`), `resume` (`src/revisionist/engine/web/server.py:645`), and for the host `handover-list` (`src/revisionist/engine/web/server.py:629`; `{}` → `{reply, refused, leaders: [{key, name, office}]}`) and `handover` (`src/revisionist/engine/web/server.py:631`; `{leader: key}` → `{reply, refused, code, from_wake}`; the code is redeemed with `join`, and the new player counts from the next wake; `src/revisionist/engine/web/wake_api.py`; refused at the human-seat cap).
  - `POST /api/realism/<action>` (`src/revisionist/engine/web/server.py:1265` → `App.realism()` `src/revisionist/engine/web/server.py:285`). Actions: `catchup` (`src/revisionist/engine/web/server.py:313`; `{first?, last?}`: one page per wake the seat missed, by default every wake since it last committed by itself; `src/revisionist/engine/web/catchup_api.py`. A page the aide played for the seat carries `aide_filed`, and a page whose opening dropped one of the seat's held orders carries `held_dropped`, each in that seat's payload only. Every page carries `steps`, the wake's playback in the order it happened (`src/revisionist/engine/web/playback.py`): the seat's own order steps, its own nation's pieces stepping, its papers on arrival, holder changes and its stakes; no commit, close or cause of a move. Its events come from the catch-up seam `src/revisionist/engine/catchup.py` `seat_events`, where every event kind is listed in `FEED_KINDS` or `NEVER`), `map` (`src/revisionist/engine/web/server.py:333`; `{shapes?}`: in a territory game, the map object the game's stored hash names (`shapes: false` leaves `map` null, for a client that holds the object fetched from `/maps/<sha256>.json`), whatever map the world file names now, the same for every seat; refused in one line when no object has that hash, `This game's map is missing on the server.`, or when the game has no territory map; `src/revisionist/engine/web/map_api.py`), `read` (`src/revisionist/engine/web/server.py:322`, logs `document_read`), `flag` (`src/revisionist/engine/web/server.py:332`, logs `document_flagged`; 404 for a document outside the seat's view), `lever` (`src/revisionist/engine/web/server.py:341`), `directive` and `sign` (`src/revisionist/engine/web/server.py:348`), `aide` (`src/revisionist/engine/web/server.py:389`), `consult` (`src/revisionist/engine/web/server.py:408`), `help` (`src/revisionist/engine/web/server.py:422`), `step` (`src/revisionist/engine/web/server.py:427`; `{order_id, action, params?}`: only the seat that holds the person at the step may act on it, and any other seat is refused with the one text `That decision is not yours to take.`, an unknown id included. A held decision waiting on its holder is listed on the holder's agenda as a Decision item, whose id goes in `order_id`. On the seat's own order the step is taken at once; on another seat's order the choice is stored as `step_chosen`, sealed to the holder and never fed, shown in the item's `cause`, may be given again, and is kept until the step's held due day, when it is taken in the card's place with the card's date), `advance` (`src/revisionist/engine/web/server.py:440`), `commit` and `close` (`src/revisionist/engine/web/server.py:449`), `style` (`src/revisionist/engine/web/server.py:466`), `option` (`src/revisionist/engine/web/server.py:469`), `answer` (`src/revisionist/engine/web/server.py:472`; `{item, accept: bool}`: the holder of the person another seat asked something of answers that request (or an offer of agreement, an `Offer` item on its agenda) through `agenda_api.answer()`. The answer is stored as `request_answered`, sealed to the holder and never fed to the seat that asked; the holder may give it again until the request's due day, and on that day the answer decides the request in the card's place, with the card's date and wording), `order` (`src/revisionist/engine/web/server.py:478`; when the aide reads a treaty the reply also carries `terms`), `agreement-offer` (`{parties, wording?, clauses?, envoy?}`: an offer of agreement from a form, each clause checked as the treaty reader checks one and the whole refused when one fails; the reply carries the proposal and its `terms`, and `file` signs it; `src/revisionist/engine/web/agreements_api.py`), `agreement-publish` (`{agreement}`: a party files the order that publishes an agreement not yet public), `conference-call` and `conference-vote` (calling a conference, and sealing the seat's vote in one; `src/revisionist/engine/web/conferences_api.py`), `file` (`src/revisionist/engine/web/server.py:498`), `battle` and `contingency` (`{area, decision, to?}`: press, hold or withdraw for a battle the seat's nation is on, filed as a posture or move of one of its pieces there; `{force, kind, to?, below?}`: a force's standing order for a battle, filed as an engagement that keeps its rule; both through `realism_tick.commit_order`, `src/revisionist/engine/web/battles_api.py`), `odds` (`{force, to}` for sending one of the seat's own forces into an area, or `{force, battle, decision}` for a battle its nation is on: the spread from the seat's own picture, `src/revisionist/engine/odds.py`; files nothing, is never held after a commit, and answers `busy` with a refusal when the server's odds queue is full or the seat has asked 30 times in a minute), `check` (`{lever, params}` for a form, `{bloc, measure, price}` for a draft offer to a bloc, or `{}` for the seat's latest reading of a written order: what filing it now would do, `allowed`, `locked` with who can allow it and the words the seat would be told, or `beyond` with today's refusal; run on the game as it stands through the filing's own steps and logged nowhere, files nothing, is never held after a commit; `src/revisionist/engine/web/locks_api.py`), `ask` (`{order_id}`: the seat asks, once, for one of its own held orders, through `realism_tick.ask_order`; the reply names who was asked), `aim-check` and `aim-set` (`{key, values}`: a pattern of the world's own aims filled with a value for each blank. `aim-check` answers `{reply, refused, aim}` with `aim` `{stands, text, reasons}`: whether it stands from the seat's own view, with the sentence as it will read, or every reason it cannot, and files nothing; `aim-set` stores it as the seat's own aim in place of its card's replaceable aim through `realism_tick.set_own_aim`, the same answer with the aim as stored, and after the window or a second time is refused with `Your own aim was not set.` and the reason. Neither is held after a commit, and neither calls a model; `src/revisionist/engine/web/stakes.py`. While the seat may still set one, `/api/me` carries its ladder under `view.realism.own_aim`), `offer` (`{bloc, measure, price}`: with `offers` on, the seat offers one price from a bloc of its own nation's list for a law whose bill is on its way, through `realism_tick.make_offer`, sealed to that nation's seats; a refusal is the filing's own words, the same `check` gives. With `offers` on, `view.realism.home` carries `offers`, each law of the seat's nation on its way with each bloc that votes on it, its prices and the offer that holds it, and `promises`, the seat's own offers with their due days; a promise come due is a line in the wake notice and in what waits on the seat, `agenda_api.due_matters`; `src/revisionist/engine/web/home_api.py`), `withdraw` (`src/revisionist/engine/web/server.py:520`; `{order_id}` for an order the seat filed in the open wake that is still at its first step, before the seat commits, or `{held_id}` for an order held for the next wake, which is dropped from the queue; one or the other, and a refusal is a reply; `/api/me` lists the orders it can withdraw under `game.withdrawable`). Reports (`src/revisionist/engine/web/reports.py`, `reports.action()`): `report` (`{kind, text}`: `kind` is `bug`, `idea` or `confusing`, `text` up to 4,000 characters; answers `{reply, refused, report}` with the report's number; pinned to the log position and the state's hash, the words sealed to the seat, at most 20 an hour per account), `reports` (`{}`: the caller's own reports in this game, each `{id, kind, status, reply, words, wake, filed}`; `{inbox: true}`: for the host, every report in his game with the `office` that filed it, and for anyone else the same shape with no reports), `report-mark` (`{id, status, reply?}`: the host sets a report's status, `new`, `seen` or `acted`, and a reply of at most 200 characters; anyone else is told `Only the host can do that.`, and a report in another game reads as `No such report.`). A `help` question that opens with `report:`, `idea:` or `bug:` (a plain `report:` is a bug) is filed as a report by `reports.from_question()`, and the aide's line says so; it never reaches `aide_help` or a model. None of these is held after a commit, and none is an event: reports sit outside the game's log. After the seat has committed, or while a close of the wake is running, `lever`, `sign`, `option`, `file`, `step`, `answer`, `battle`, `contingency`, `agreement-publish`, `conference-call`, `conference-vote`, `ask` and `offer` are checked and held for the next wake (`Held for the next wake.`, with the `held` id; `src/revisionist/engine/web/held.py`), filed by `wake_open.before_offers` when that wake opens, in the order given and before its offers; `/api/me` lists the seat's own held orders under `game.held`. `advance` passes a prose writer to `run_realism_tick`: `ClaudeProseWriter(transport_factory())`, or `TemplateProseWriter()` when the `App` was built with `offline_prose=True`. Pages the writer drops are logged at warning level and stay bare. Replies are in words; the CLI keeps `wake_line`.
- Seat actions (`SEAT_ACTIONS` keys, `src/revisionist/engine/web/server.py:1022`, mapped to `WebHandlers`): `join`, `roster`, `search`, `claim`, `pick`, `goal`, `confirm`, `history`, `agent`, `order`, `ask`, `dossier`, `dispatch`, `status`, `report`, `bug`. `bug` (`{notes}`) files a player report of the kind bug through `reports.seat_bug()`, as the realism `report` does; `report` is the season report, unchanged.
- Realism seat block, `view.realism` in `GET /api/me`: `documents`, `desk`, `situation`, `orders`, `clock`, `record`, `reach`, `map`, `agenda`. `situation()` is the Situation tab: each body line with a unit and a number-or-silent value, from arrived pages only, grouped by line and by author, never averaged; a silent latest report is a gap dated by `last_given`.
- Errors: `ApiError` (`src/revisionist/engine/web/server.py:113`). `WithheldError` returns `{"error": WITHHELD}` (`except snapshot.WithheldError` in `do_GET` and `do_POST`).
- Auth and hardening (`src/revisionist/engine/web/server.py`):
  - Session cookie `rv_session` (`guard.COOKIE`), HttpOnly, SameSite=Strict (`guard.cookie()`). Token hashed at rest (`src/revisionist/engine/web/accounts.py:69`).
  - Writes need a JSON content type and an `Origin` matching `Host`, or with no `Origin` a `Referer` on `Host`; a write naming neither is refused (`guard.same_origin()`).
  - Body cap 64 KiB (`guard.BODY_MAX`, `guard.body()`); a `Content-Length` that is not a number is a 400; a body that stalls is a 408; each of these closes the connection (`guard.closing()`). A connection that sends nothing for `guard.IDLE_S` (30) seconds is closed (the handler's `timeout`).
  - Expired sessions are deleted at start and once a day (`accounts.sweep_daily()`, `Accounts.sweep()`, started by `serve()`).
  - Sign-in and recovery throttle: 10 failures per handle per 15 min (`limits.SIGNIN_TRIES`, `limits.SigninThrottle`, held as `App.signin`).
  - CSP header on every response (`guard.CSP`, `guard.headers()`), with `Cross-Origin-Resource-Policy: same-origin` and a `Permissions-Policy` that grants no listed feature (`guard.PERMISSIONS`).
  - `secure_cookie` defaults to `False`; `web serve --secure-cookie` sets it, which adds `Secure` to the cookie and `Strict-Transport-Security` (`guard.HSTS`) to every reply.

Frontend (static, no build):
- `web/index.html:38`: loads `/js/app.js` as a module. Mounts `#app`. Stylesheets are linked at `web/index.html:9-17` (`web/css/`).
- `web/js/app.js:18`: route from `location.hash`, default `signin`. `go()` at `web/js/app.js:21`. The view is picked in `render()` (`web/js/app.js:60`). A re-render runs every 60 s (`web/js/app.js:116-122`) unless typing or a dialog is open.
- `web/js/api.js:10` `call()`. `web/js/api.js:32` `api` object: `me` (GET `/api/me`), `signup`, `signin`, `recover`, `signout`, and `seat(action)` (`web/js/api.js:39`) → `/api/seat/<action>`.
- Views, one file each in `web/js/views/`:
  - `auth.js`: sign up, sign in, recovery codes and recovery.
  - `frame.js`: the black frame header shared by every signed-in screen.
  - `new-game.js`: a new realism game, from a ready-made world or a pitch read into start points and a generated cast. Whoever starts it is its host.
  - `realism.js`: realism views: the in-tray, a document page, the directive form, the situation board, the aide's brief, conversation bubbles, the pace header and the standard forms. Each takes the realism JSON and returns a node.
  - `realism-room.js`: the realism room, one surface for a seat: the in-tray on the left, what needs an answer, ideas, the order being written or signed, the standard forms and the commit in the middle, the seat's orders on the right, and the messenger over it.
  - `realism-tray.js`: the in-tray as a message list with a reading pane.
  - `realism-acks.js`: acknowledgements in the conversation with their author.
  - `realism-answer.js`: "Needs your answer": what is waiting on the seat, leader requests first, then the desk's own matters, each with its choices.
  - `realism-requests.js`: requests from named leaders and their choices, as pure helpers that `realism-answer.js` draws.
  - `realism-ideas.js`: "Ideas": orders the seat could file now, the initiative offer and the aide's suggested drafts in one list.
  - `realism-forms.js`: "Standard forms": the seat's levers, folded by default.
  - `realism-wake.js`: the wake on the desk: header, how you play, the agenda, initiative, commit, the order the aide read and how each order landed. Counts only.
  - `realism-overlay.js`: the overlay while a wake runs: a full-screen layer that holds the room and gives the player something to read.
  - `realism-happened.js`: "What happened": the sheet that opens once when a new wake opens.
  - `realism-news.js`: the "What changed" block on the desk: the newest unread press pages.
  - `realism-orders.js`: the orders log: one row per order, made, landed and finished.
  - `realism-chat.js`: the messenger: a fixed "Messages" button with the unread count, and a panel with Chats and Contacts.
  - `realism-contacts.js`: the Contacts tab of the messenger: everyone the seat can reach, and a contact's detail.
  - `realism-reach.js`: who the seat can reach and how, in four groups, as pure helpers.
  - `realism-dossier.js`: the two dossiers behind the header: the character the seat plays, and the setting.
  - `realism-map.js`: the realism map: forces, fronts and routes drawn over Natural Earth coastlines, with the same marks as a list.
  - `realism-cast.js`: choosing the people: the cast as cards that open a dossier, everyone else who held power as a searchable table, and the host's invite and Begin.
  - `realism-castcard.js`: a cast member's card on character select: portrait or monogram, name, side and pitch.
  - `realism-castdossier.js`: the dossier behind a cast card or a listed figure on character select.
  - `realism-castlist.js`: everyone else who held power on the start date: side chips, one table, and the Find someone search.
  - `realism-intro.js`: the opening of a game: the crawl, then the player's own splash. Once per game per browser.
  - `realism-reveal.js`: the end-of-game reveal, at the route `#reveal/<id>`.
  - `session-zero.js`: Session Zero, the player's steps: character, goal, brief, agent, then waiting for the host. The host's steps stay on Discord and the CLI.
  - `war-room.js`: the war room: position on the left, briefing and dossier in the centre with the order box, the agent and the Chronicle on the right.
- Pure rules, unit-tested: `web/js/rules.js` (`band` `web/js/rules.js:14`, `visibility` `web/js/rules.js:28`, `disposition` `web/js/rules.js:39`, `parseReply` `web/js/rules.js:54`, `untilText` `web/js/rules.js:80`, `worldDate` `web/js/rules.js:91`). Realism rules in `web/js/realism-rules.js` (`sortInTray` `web/js/realism-rules.js:47`, `stepLine` `web/js/realism-rules.js:110`, `mapBox` `web/js/realism-rules.js:262`).
- DOM helpers in `web/js/dom.js` (`h` `web/js/dom.js:9`, `reply` `web/js/dom.js:105`, `prose` `web/js/dom.js:117`).
- Theme: `web/js/theme.js:6-7` (`THEME_KEY`, `EFFECTS_KEY`). The default theme is Terminal (`web/js/theme.js:13`); Paper is the other choice. `web/js/theme-setting.js:10` `themeStore()` reads and writes both keys.
- `web/package.json:8` `npm test` (`node --test test/*.test.js`). `web/package.json:9` `npm run lint` (`eslint js test`).

## 6. Data
- SQLite (default):
  - `src/revisionist/engine/campaign.py:41-44` `db_target()`: `REVISIONIST_DB`, default `revisionist.db` in the working directory. A `revisionist.db` sits at the main repo root.
  - `src/revisionist/engine/store.py:196` `SqliteStore`: `PRAGMA journal_mode=WAL` and `foreign_keys=ON`. Schema from inline `_SCHEMA` via `executescript`.
  - Tables: `events`, `snapshots`. Triggers make `events` append-only.
  - SQLite schema is not in migration files.
- Postgres:
  - `src/revisionist/engine/campaign.py:47-48` `is_postgres()`. `src/revisionist/engine/pg_store.py:29` `PostgresEventStore` (psycopg).
  - `src/revisionist/engine/pg_store.py:24` `MIGRATIONS` = `src/revisionist/engine/migrations/`. `src/revisionist/engine/pg_store.py:109` `migration_files()` (sorted `NNNN_*.sql`).
  - `src/revisionist/engine/pg_store.py:113` `migrate()`: advisory lock, `schema_migrations` table, each file in its own transaction with a version row, `{app_role}` substituted.
  - Run by `revisionist db migrate` (`src/revisionist/cli.py:890-905`) with `REVISIONIST_ADMIN_DSN` (`src/revisionist/cli.py:897`). App role defaults to `revisionist_app` (`REVISIONIST_APP_ROLE`, `src/revisionist/cli.py:893`).
- Migrations (`src/revisionist/engine/migrations/`):
  - `0001_init.sql`: `events`, `snapshots`.
  - `0002_schedule.sql`: `schedule`.
  - `0003_discord.sql`: `discord_seats`, `discord_deliveries`, `discord_bugs`.
  - `0004_rename.sql`: renames the append-only trigger function `wyrd_append_only` to `revisionist_append_only`.
  - `0005_discord_invites.sql`: `discord_invites`.
  - `0006_discord_channels.sql`: `discord_channels`.
  - `0007_seal_keys.sql`: `seal_keys`.
  - `0008_retire.sql`: adds `schedule.retired_at` (retired campaigns never tick again).
  - `0009_web.sql`: `web_accounts` (`src/revisionist/engine/migrations/0009_web.sql:6`), `web_recovery_codes` (`src/revisionist/engine/migrations/0009_web.sql:16`), `web_sessions` (`src/revisionist/engine/migrations/0009_web.sql:23`), `web_seats` (`src/revisionist/engine/migrations/0009_web.sql:32`). Grants to `{app_role}` (`src/revisionist/engine/migrations/0009_web.sql:41-42`).
  - `0010_web_hosts.sql`: `web_hosts`, the account that started a web game (invites, begins, advances it). A game started from Discord or the CLI has none.
  - `0011_web_finished.sql`: adds `web_seats.finished_at`. An ended game keeps its web seats so each player can open its reveal; a finished seat is no longer held.
  - `0012_web_notices.sql`: `web_notice_addresses` (an account's notice address and IANA zone) and `web_notices_sent` (one row per seat and wake once its notice has gone). Read as empty until migrated (`src/revisionist/engine/notice.py`).
  - `0013_web_held_orders.sql`: `web_held_orders` (an order a seat gave after committing, kept until the next wake opens; `filed_in` and `dropped` record what became of it). Read as empty until migrated (`src/revisionist/engine/web/held.py`).
  - `0015_player_reports.sql`: `player_reports` (one row per report: game, seat, account, kind, wake, log position, state hash, the words sealed to the seat, status, reply, when filed and marked) and `player_report_digests` (one row per day whose digest has gone). Rows in `discord_bugs` stay where they are; the Discord `/bug` still files there. Run by hand on each served database before a restart (`revisionist db migrate`); until then the report actions answer `Reports are not set up on this server yet.`
- Event log: `src/revisionist/core/events.py` (event models). `src/revisionist/core/fold.py:107` `apply()`, `src/revisionist/core/fold.py:119` `replay()`. `src/revisionist/engine/store.py:103` `load_state()`. The Postgres store reads from a snapshot plus the tail (`src/revisionist/engine/pg_store.py`).
- Schema export: `src/revisionist/schema_export.py:33` writes `schema/revisionist.schema.json`, which is committed. `tests/test_schema.py:85` checks it is current. `src/revisionist/core/__init__.py:23` `SCHEMA_VERSION = "72"`.
- Worlds: `worlds/autumn-1941.yaml`, `worlds/engine-v2-slice-1941.yaml`, `worlds/realism-slice-1941.yaml`, `worlds/realism-toy.yaml`, `worlds/salt-strait.yaml`, `worlds/salt-strait-duo.yaml`. Resolved from `src/revisionist/engine/campaign.py:33` `WORLDS_DIR` by `world_path()` (`src/revisionist/engine/campaign.py:85`). Sidecar text for two of them: `worlds/dossiers/autumn-1941.yaml` and `worlds/dossiers/engine-v2-slice-1941.yaml`. Drafts `tests/drafts/florence-1478.yaml` and `washington-1962.yaml` are fixtures.
- Briefings: `src/revisionist/engine/campaign.py:226-235` `briefings_dir()`: `REVISIONIST_BRIEFINGS_DIR`, else `<db>-briefings` beside a SQLite file, else `./revisionist-briefings`. Files `t<tick>-<seat>.md` from `FileDeliverer` (`src/revisionist/engine/campaign.py:208-223`).
- Setting card waiting for `establish confirm`: `src/revisionist/cli.py:231-234` `_card_file()`, `revisionist-card.json` beside briefings.
- Backups: `deploy/backup/revisionist-backup.sh` runs `pg_dump -Fc` into `REVISIONIST_BACKUP_DIR`. Prunes by age. Copies the map objects (`db map-objects copy --all`) into `map-objects/` beside the dumps, never pruned. Copies both off-box. Restore drill: section 1.

## 7. Tests
- Run (CI order, `.github/workflows/ci.yml`):
  - `uv sync --frozen` (`.github/workflows/ci.yml:42`), `uv run --frozen ruff check .` (`.github/workflows/ci.yml:43`), `ruff format --check .` (`.github/workflows/ci.yml:44`), `uv run --frozen mypy` (`.github/workflows/ci.yml:45`), `uv run --frozen pytest --cov=revisionist.core --cov-report=term-missing` (`.github/workflows/ci.yml:46`), then `node --test test/*.test.js` in `web/` (`.github/workflows/ci.yml:47-48`).
  - Config: `pyproject.toml:43-49` ruff, `pyproject.toml:51-55` mypy (strict, `src` and `tests`), `pyproject.toml:57-59` pytest (`testpaths=tests`, `-q`).
- Postgres tests:
  - `tests/pg.py:23` reads `REVISIONIST_TEST_PG_ADMIN_DSN`. Without it the tests skip, unless `REVISIONIST_REQUIRE_PG=1` makes them fail (`tests/pg.py:34-39`).
  - CI runs a Postgres 16 service (`.github/workflows/ci.yml:14`) and sets `REVISIONIST_REQUIRE_PG` (`.github/workflows/ci.yml:28`).
  - Fixtures: `tests/conftest.py:13-22` (`pg_cluster`, session scope; `pg_db`, per test). `tests/pg.py` `Cluster` builds a template database.
- Autouse fixtures:
  - `tests/conftest.py:23-29` strips `REVISIONIST_*` from the environment for each test.
  - `tests/conftest.py:31-` blocks Discord network calls.
- Model replay: `tests/recordings/two-rivers-agent.json` and `two-rivers-tick-1.json`, read by `RecordedTransport`. Refresh with `REVISIONIST_RECORD=1 uv run pytest tests/test_llm.py -k live` (`tests/test_llm.py:254`) or `tests/test_agent.py:326`.
- Realism model replay: `tests/recordings/realism-*.json`, hand-written (each entry is marked `hand_written`; no model wrote them). Regenerate after a prompt change with `uv run --frozen python -m tests.handwritten`; scenarios in `tests/prose_scenario.py` and `tests/counsel_scenario.py`.
- Helpers: `tests/fixtures.py`, `tests/discord_fakes.py` (`FakeDiscord` `tests/discord_fakes.py:20`), `tests/pg.py`.
- Browser tests:
  - `web/test/e2e/smoke.py` and `web/test/e2e/realism_smoke.py`: Playwright against a live `revisionist web serve`. `web/test/e2e/serve_canned.py` serves canned responses for them. Manual; not in CI.
  - `web/test/*.test.js` (`npm test`): unit and wiring tests for the client's pure rules and views, run in CI (`.github/workflows/ci.yml:47-48`). `npm run lint` (ESLint) is not in CI.
  - Docker: none found (no Docker files).
- Coverage by area:
  - Core rules: `test_fold`, `test_referee`, `test_referee_d1`, `test_referee_contest`, `test_contest`, `test_goals`, `test_goal_rule`, `test_goal_offer_cap`, `test_goal_labels`, `test_intel`, `test_perceived_odds`, `test_project`, `test_places`, `test_roster`, `test_calendar`, `test_history`, `test_tick_history`, `test_dossier_and_world_state`, `test_order_results`, `test_report`, `test_schema`, `test_purity` (name only, not opened).
  - Tick and engine: `test_tick`, `test_season`, `test_scheduler`, `test_one_game`, `test_world_compile`, `test_draft`, `test_pitch`, `test_briefing_orders`, `test_advise`, `test_agent`, `test_deputy_history`, `test_prompt_diet`, `test_model_override`, `test_llm`, `test_character_search`, `test_character_names`.
  - Session Zero: `test_session_zero`, `test_session_zero_steps`, `test_session_zero_confirm`, `test_session_zero_aliases`, `test_session_zero_v3_contract`.
  - Storage, sealing, verify: `test_store`, `test_db`, `test_seal`, `test_seal_pg`, `test_host_ops`, `test_human_boundary`, `test_verify_record_cli`, `test_verify_record_search`, `test_verify_why_cli`, `test_verify_why_discord`, `test_verify_host_link`, `test_verify_full_season`.
  - CLI: `test_cli`, `test_cli_establish`, `test_env_isolation` (runs the CLI as a subprocess), `test_deploy` (runs `deploy/backup` scripts).
  - Discord: `test_discord_bot`, `test_discord_format`, `test_discord_delivery`, `test_discord_duo`, `test_discord_host`, `test_discord_public`, `test_discord_establish`, `test_discord_game_matrix`, `test_discord_report_after_season`, `test_channel_carryover`, `test_durable_replies`.
  - Web: `tests/test_web.py` (fixture `web`, helper class `Web`; password hashing, cookie flags, signup and signin rules, throttle, same-origin writes, seat auth, static containment, CSP, Session Zero to play, seat held by one client, leak scan counting web players, retire releasing web seats, CLI refusing web-held seats, snapshot, canary withholding). Further files: `tests/test_web_*.py`, covering the agenda, dossiers, new game, the Phase 4 contract, pick, reach, realism, the record block, results, reveal, the in-tray, the wake and the map.
  - Other: `test_drift_report` (not opened).
- Stale bytecode: `tests/__pycache__/test_probe_*.pyc` exist with no source file.

## 8. Config and env vars
Environment variables (all read in code unless noted):
- `REVISIONIST_DB`: `src/revisionist/engine/campaign.py:44`. SQLite path or `postgresql://` URL. Default `revisionist.db`. `revisionist web serve` needs a `postgresql://` URL here (`src/revisionist/cli.py:1046`).
- `REVISIONIST_BRIEFINGS_DIR`: `src/revisionist/engine/campaign.py:229`.
- `REVISIONIST_MASTER_KEY_FILE`: `src/revisionist/engine/seal.py:213` (`MASTER_KEY_ENV`), `src/revisionist/engine/seal.py:219`; also `src/revisionist/engine/campaign.py:72`. Enables sealing.
- `CREDENTIALS_DIRECTORY` (systemd credentials): `src/revisionist/engine/seal.py:226`, `src/revisionist/engine/campaign.py:73`.
- `REVISIONIST_ADMIN_DSN`: `src/revisionist/cli.py:897` (`db migrate`), `src/revisionist/cli.py:993` (`admin erase`), `deploy/backup/revisionist-backup.sh:12`, `deploy/backup/revisionist-restore-drill.sh:11`.
- `REVISIONIST_APP_ROLE`: `src/revisionist/cli.py:893` (Typer `envvar`; default `revisionist_app`).
- `REVISIONIST_DISCORD_TOKEN`: `src/revisionist/cli.py:1307` (`discord run`), `src/revisionist/engine/discord/delivery.py:35` (`TOKEN_ENV`).
- `REVISIONIST_DISCORD_GUILD_ID`: `src/revisionist/cli.py:1194` (`link`), `src/revisionist/cli.py:1282` (`channel`), `src/revisionist/cli.py:1308` (`run`).
- `REVISIONIST_DISCORD_HOST_ID`: `src/revisionist/cli.py:121` (`_guard`), `src/revisionist/cli.py:699` (`_holdings`), `src/revisionist/cli.py:1322` (`discord run`).
- `REVISIONIST_MODEL_<CALL>`: `src/revisionist/engine/llm.py:203-207`. Overrides the model per call class; must start with `claude-`. Examples in `tests/test_model_override.py:39-53`.
- `REVISIONIST_SCHEDULER_TRANSPORT`: `src/revisionist/cli.py:1064` (`SCHEDULER_TRANSPORT_ENV`). `claude` or `openrouter`: what `scheduler run` ticks on when `--transport` is not given, else `claude`. Each instance's env file sets it; the templated unit passes it as `--transport ${REVISIONIST_SCHEDULER_TRANSPORT}` (`deploy/systemd/revisionist-scheduler@.service:18`), so a file without it fails at start.
- `REVISIONIST_OPENROUTER_KEY`: `src/revisionist/engine/openrouter.py:42` (`KEY_ENV`). The key of an `openrouter` instance, read by `web serve --transport openrouter`, `scheduler run --transport openrouter` and `web check-transport`; it goes only into the request's Authorization header. `REVISIONIST_OPENROUTER_MODELS`: `src/revisionist/engine/openrouter.py:43` (`MODELS_ENV`). JSON `{"kind": ["vendor/model:free", ...]}`; each kind given replaces the default's.
- `REVISIONIST_NOTICE_SMTP`: `src/revisionist/engine/notice.py:47` (`SMTP_ENV`). `smtp://` (STARTTLS) or `smtps://` `user:password@host:port`; wake notices go by email. `REVISIONIST_NOTICE_FROM`: `src/revisionist/engine/notice.py:48` (`FROM_ENV`). The sender address; default is the login. `REVISIONIST_NOTICE_OUTBOX`: `src/revisionist/engine/notice.py:46` (`OUTBOX_ENV`). A file; with no SMTP set, one JSON line per notice is appended there (a dry run). With none of the three set nothing is sent. Read by `sender_from_env()` (`src/revisionist/engine/notice.py:179`).
- `REVISIONIST_REPORTS_DIR`: `src/revisionist/engine/web/reports.py` (`DIR_ENV`). A folder only the operator reads; each player report is written there as `report-<n>.md`, mode 600, its words in plain. Unset: reports are stored and listed only.
- `REVISIONIST_REPORTS_DIGEST_TO`: `src/revisionist/engine/notice.py` (`DIGEST_TO_ENV`). Where `revisionist reports digest` sends the day's count of reports. Unset: no digest.
- `REVISIONIST_RECORD`: `src/revisionist/engine/llm.py:245`. `1` records live calls into a recording file.
- `REVISIONIST_MAP_OBJECTS`: `src/revisionist/engine/maps.py:16` (`OBJECTS_ENV`). The map-objects directory; default `worlds/maps/objects/`. `map_object()` (`src/revisionist/engine/maps.py:29`) reads `<sha256>.json` from it, or else the world-named file in `worlds/maps/` when its bytes hash the same; it never returns a map whose hash differs.
- `REVISIONIST_MAP_DATA`: `scripts/map_build.py:691` (`build --data` falls back to it). The directory of the cached Natural Earth files the map build reads, outside the repo; build-time only, the game never reads it (`worlds/maps/README.md`, `worlds/maps/SOURCES.md`).
- `REVISIONIST_MARK_SECRET`: `src/revisionist/engine/web/map_api.py` (`mark_secret`). Required persistent deployment secret, exactly 64 hex digits (32 random bytes). `server.App` validates it at startup; missing or malformed configuration fails closed. `mark_key` MACs map/label/piece keys; `step_key` uses the same conversion for stored movement marks. Never sent to a seat or stored in events; preserve it across restore to retain key stability.
- `REVISIONIST_PUBLIC_NAMES`: `src/revisionist/engine/web/guard.py` (`PUBLIC_NAMES_ENV`), read on every request. The names `web serve` is reached by, comma separated, each a host or `host:port` (a name with no port matches every port). Set: a request whose Host is not listed is refused with 421 on every method, and a write's Origin, or else Referer, must be listed. Unset: a write whose Host is not an IP address, `localhost` or a `.ts.net` name is refused with 421 (`deploy/SECURITY.md`).
- `REVISIONIST_TRUST_PROXY`: `src/revisionist/engine/web/limits.py` (`TRUST_PROXY_ENV`). `1` counts sign-ups, sign-ins and recoveries by the last address in `X-Forwarded-For` (the one the proxy in front wrote); anything else counts by the socket's address. Set it only when a proxy that writes the header sits in front of `web serve`.
- Web: `revisionist web serve` takes its database from `REVISIONIST_DB` (above) and its briefings directory from `REVISIONIST_BRIEFINGS_DIR` (above).
- Backups:
  - `REVISIONIST_BACKUP_DEST` (`deploy/backup/revisionist-backup.sh:13`, `deploy/backup/revisionist-backup.sh:28`): rsync target or `rclone:<remote>:<path>`.
  - `REVISIONIST_BACKUP_DIR` (`deploy/backup/revisionist-backup.sh:14`; also `deploy/backup/revisionist-restore-drill.sh:12`): default `~/.local/share/revisionist/backups`.
  - `REVISIONIST_BACKUP_KEEP_DAYS` (`deploy/backup/revisionist-backup.sh:15`): default 14.
  - `REVISIONIST_BIN` (`deploy/backup/revisionist-restore-drill.sh:13`): the `revisionist` command.
- Tests:
  - `REVISIONIST_TEST_PG_ADMIN_DSN` (`tests/pg.py:23`; `tests/conftest.py:10`; `.github/workflows/ci.yml:26`).
  - `REVISIONIST_REQUIRE_PG` (`tests/pg.py:38`; `.github/workflows/ci.yml:28`; `tests/test_deploy.py:104`).
- Child-process filter: `src/revisionist/engine/llm.py:138` removes `REVISIONIST_*` from the environment passed to `claude`.
- Set by systemd, not read in code: `PATH` (`deploy/systemd/revisionist-discord.service:13`, `deploy/systemd/revisionist-scheduler.service:12`), `WorkingDirectory` (`deploy/systemd/revisionist-discord.service:14`), `EnvironmentFile` (`revisionist.env` in `discord.service:11` and `scheduler.service:10`; `revisionist-admin.env` in `backup.service:9`).

Browser storage (the client, `web/js/`; no server-side store):
- `rv.theme`: the theme, `terminal` or `paper` (`web/js/theme.js:6`). Missing or unknown reads as Terminal.
- `rv.effects`: the screen effects, on only when the value is `"on"` (`web/js/theme.js:7`, `web/js/theme.js:20`).
- `rv.intro.<game id>`: the opening crawl and splash shown once per game per browser (`web/js/views/realism-intro.js:8`).
- `rv.chat.seen.<campaign id>`: the messenger lines seen per thread (`web/js/views/realism-chat.js:7`).
- `rv.happened.<campaign id>`: the last wake shown in "What happened" (`web/js/views/realism-happened.js:5`).
- The browser keeps no other key. The session is the `rv_session` cookie, set by the server (section 5).

Config keys (not env):
- `src/revisionist/core/settings.py:44` `Settings`, set by `establish confirm` options (`src/revisionist/cli.py:263`): `plausibility` (default PLAUSIBLE), `inertia` (TENDENCIES), `lethality` (HARD), `betrayal` (CUTTHROAT), `tone` ("grounded"), `tick_hours` (24, range 1–168).
- World YAML: `worlds/*.yaml`, parsed by `WorldFile` (`src/revisionist/engine/campaign.py:96-97`).
- Discord `BotConfig` (`src/revisionist/engine/discord/handlers.py:136`).

## Unclear / not verified
- `revisionist.env` and `revisionist-admin.env` contents are not in the repo; `docs/deploy.md` is the only reference.
- `docs/deploy.md:283-285` still has `wyrd-*` unit names in a teardown section.
