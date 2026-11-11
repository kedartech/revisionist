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
- `deploy/systemd/revisionist-backup.service:10`: `ExecStart=%h/.local/bin/revisionist-backup`. Oneshot, admin env file `deploy/systemd/revisionist-backup.service:9`. Installed from `deploy/backup/revisionist-backup.sh` (`docs/deploy.md:95`).
- `deploy/systemd/revisionist-backup.timer:5`: `OnCalendar=*-*-* 03:30:00`, `RandomizedDelaySec=15min` (`deploy/systemd/revisionist-backup.timer:7`).
- `deploy/backup/revisionist-restore-drill.sh:1-37`: manual drill, not on a timer. Installed as `revisionist-restore-drill` (`docs/deploy.md:96`). Runs `revisionist db verify` at `deploy/backup/revisionist-restore-drill.sh:37`.
- Bot entry: `src/revisionist/cli.py:1304-1339` (`discord run`) → `src/revisionist/engine/discord/bot.py:464` `run()` → `RevisionistBot.run(token)`.
- Scheduler entry: `src/revisionist/engine/scheduler.py:288` `run()`, called from `src/revisionist/cli.py:1068`.
- Solo entry: `revisionist tick` (`src/revisionist/cli.py:587`), run by hand on SQLite.
- Web entry: `revisionist web serve` (`src/revisionist/cli.py:1348`) runs in the foreground. Plain HTTP. No systemd unit or deploy file covers it (`deploy/` and `docs/deploy.md` have none).

## 2. CLI commands
Exit codes: 1 error, 2 refused, 3 leak (`src/revisionist/cli.py:60-62`). `--seat` takes an ID or a name (`src/revisionist/cli.py:103-106`). `--offline` is `src/revisionist/cli.py:56-58`.

Top-level:
- `version` (`src/revisionist/cli.py:131`): print engine version.
- `new WORLD [--seat PERSON]` (`src/revisionist/cli.py:148`): compile a world YAML (name in `worlds/` or a path) and start a campaign. A realism world needs `--seat` (a person's key or name), which claims them and closes Session Zero; a legacy world refuses it.
- `dashboard [--seat]` (`src/revisionist/cli.py:333`): standing, means, goal progress.
- `status [--seat]` (`src/revisionist/cli.py:376`): campaign status as your seat sees it.
- `briefing [--seat]` (`src/revisionist/cli.py:387`): agent briefing. Exit 3 if withheld.
- `order TEXT [--seat] [--visibility private|public|covert] [--spin ≤280]` (`src/revisionist/cli.py:410`): file an order.
- `tick [--offline]` (`src/revisionist/cli.py:587`): resolve one tick. `--offline` uses the scripted resolver and narrator. On a realism campaign it runs `run_realism_tick` (`src/revisionist/engine/realism_tick.py:135`) and prints the wake and the new date. Code decides every outcome; the only model call is the PROSE stage, one call per document author per wake through `ClaudeProseWriter` (`src/revisionist/engine/prose.py:146`). The prose writer is picked in `src/revisionist/engine/runner.py:83`: `TemplateProseWriter` (plain period sentences, no model) when offline.
- `lever NAME [key=value ...] [--seat]` (`src/revisionist/cli.py:458`): realism. File an order by pulling a lever on your card; every parameter is checked against its spec. Prints the order id and its first step.
- `step ORDER ACTION [key=value ...] [--seat]` (`src/revisionist/cli.py:476`): realism. Act at the step of your order that waits on you (`pass`, `refuse`, `amend` with edits, ...). A final step that enacts the order runs its resolver in the same batch, so its quantities (vote counts) are set before the next tick.
- `consult PERSON "QUESTION" [--seat]` (`src/revisionist/cli.py:520`): realism. Ask a person on your card (by surname, full name or entity id) over your card's channel to them. The counsel model speaks as that person from their projection only (`core/realism/person.project_person`). Lands a `counsel_held` record private to your seat, plus `cost_logged`; changes nothing in the world and files nothing. Exit 2 for someone not within reach.
- `aide [--seat] [--offline]` (`src/revisionist/cli.py:552`): realism. Your aide's brief from your projected view: a summary of unread pages, the decisions waiting on you, and up to three draft orders from your levers, printed as `revisionist lever ...` commands and never filed. `--offline` uses the template aide (no model).
- `why TARGET [--break-glass] [--reason]` (`src/revisionist/cli.py:630`): trace an intent or event through the log.
- `replay --to TICK` (`src/revisionist/cli.py:658`): rebuild state at a tick and print its hash.
- `cost` (`src/revisionist/cli.py:667`): model spend per tick and in total; on a realism campaign also per in-world day.
- `leaks [--humans]` (`src/revisionist/cli.py:674`): canary scan. `--humans` needs Postgres and Discord links.
- `history [--seat]` (`src/revisionist/cli.py:846`): tick-0 brief from the record.
- `agent --name --role [--voice] [--backstory] [--relationship] [--seat]` (`src/revisionist/cli.py:857`): design your agent's persona.
- `begin` (`src/revisionist/cli.py:877`): close Session Zero and start play.

Groups:
- `world` (`src/revisionist/cli.py:195-196`):
  - `check WORLD` (`src/revisionist/cli.py:200`): validate a world file as `new` would, and list what is still unsourced. `--gaps-only` prints only the gap list.
- `establish` (`src/revisionist/cli.py:228`):
  - `pitch TEXT [--effort 1-4]` (`src/revisionist/cli.py:238`): read a pitch into a setting card.
  - `confirm N [--strike] [--end YYYY-MM-DD] [--days 1-365] [--plausibility] [--inertia] [--lethality] [--betrayal] [--tone] [--tick-hours 1-168] [--effort]` (`src/revisionist/cli.py:263`): open the game from start point N.
- `season` (`src/revisionist/cli.py:344`):
  - `end` (`src/revisionist/cli.py:348`): full reveal, winners; ticks stop.
  - `report` (`src/revisionist/cli.py:364`): season report.
- `character` (`src/revisionist/cli.py:707`):
  - `roster` (`src/revisionist/cli.py:737`), `search DESCRIPTION` (`src/revisionist/cli.py:744`), `claim NAME [--new]` (`src/revisionist/cli.py:757`), `pick NAME [--new]` (`src/revisionist/cli.py:770`).
- `goal` (`src/revisionist/cli.py:709`):
  - `suggest {history|could_have}` (`src/revisionist/cli.py:784`), `own TEXT` (`src/revisionist/cli.py:803`), `confirm LABEL` (`src/revisionist/cli.py:816`).
  - `flags` (`src/revisionist/cli.py:827`), `approve SEAT` (`src/revisionist/cli.py:833`): host balance flags.
- `db` (`src/revisionist/cli.py:883`):
  - `migrate [--app-role]` (`src/revisionist/cli.py:890`): apply migrations as `REVISIONIST_ADMIN_DSN`.
  - `copy --from SQLITE --to PG_URL [--campaign]` (`src/revisionist/cli.py:907`), `verify [--campaign]` (`src/revisionist/cli.py:938`).
- `admin` (`src/revisionist/cli.py:954`):
  - `show EVENT_ID [--reason]` (`src/revisionist/cli.py:958`): print an event; a sealed private one is logged as an admin read.
  - `erase --seat [--reason] [--campaign]` (`src/revisionist/cli.py:976`): destroy a seat's key.
  - `new-master-key PATH` (`src/revisionist/cli.py:1016`).
- `scheduler` (`src/revisionist/cli.py:1037`):
  - `run [--campaign] [--offline]` (`src/revisionist/cli.py:1064`), `status` (`src/revisionist/cli.py:1090`), `advance` (`src/revisionist/cli.py:1118`), `pause [--reason]` (`src/revisionist/cli.py:1124`), `resume` (`src/revisionist/cli.py:1133`).
- `discord` (`src/revisionist/cli.py:1141`):
  - `link --user ID [--campaign] [--seat]` (`src/revisionist/cli.py:1184`), `unlink` (`src/revisionist/cli.py:1207`), `invite [--campaign] [--seat] [--hours 1-720]` (`src/revisionist/cli.py:1223`), `invites` (`src/revisionist/cli.py:1257`), `channel public CHANNEL_ID` (`src/revisionist/cli.py:1270`), `seats` (`src/revisionist/cli.py:1293`), `run` (`src/revisionist/cli.py:1305`).
- `web` (`src/revisionist/cli.py:1341`):
  - `serve [--host 127.0.0.1] [--port 8740] [--static DIR] [--offline-prose]` (`src/revisionist/cli.py:1348`). `--offline-prose` makes the realism `advance` write pages with `TemplateProseWriter` instead of `ClaudeProseWriter`. The server is built at `src/revisionist/cli.py:1372`.

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

Realism:
- `src/revisionist/engine/realism_tick.py:135` `run_realism_tick(..., prose=writer)` (the web `advance` passes one too; see section 5): stages ADVANCE, PIPELINES, RESOLVE, FEEDS, then PROSE when a writer is passed (`play_tick` always passes one). PROSE gathers pages issued since the last `tick_closed` without prose, groups them by author, makes one writer call per author, drops prose that states a figure the page lacks (`core/realism/prose.invented_numbers`), and lands `document_written` events with their own `tick_stage_completed`. A `TransportError` leaves the pages bare and the tick still closes; call costs go on `tick_closed.costs`.
- `src/revisionist/engine/prose.py:53` `ProseWriter` protocol (takes `DocumentView`s and an `Author`, never `State`), `src/revisionist/engine/prose.py:146` `ClaudeProseWriter`, `src/revisionist/engine/prose.py:223` `TemplateProseWriter`. Prompt `src/revisionist/engine/prompts/document_prose.md`.
- `src/revisionist/engine/counsel.py:130` `consult()`: counsel; prompt `src/revisionist/engine/prompts/counsel.md`.
- `src/revisionist/engine/aide.py:319` `aide_for()`, `src/revisionist/engine/aide.py:222` `brief()`: the aide; prompt `src/revisionist/engine/prompts/aide.md`.
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
- `src/revisionist/engine/season.py:26` `end_season()` (full reveal, ticks stop), `src/revisionist/engine/season.py:55` `report()`.
- Retire: `src/revisionist/engine/scheduler.py:216` `ScheduleTable.retire()`; Discord handler `src/revisionist/engine/discord/handlers.py:516`.

Seats:
- `src/revisionist/engine/campaign.py:117` `human_seats()`, `src/revisionist/engine/campaign.py:122` `human_seat()`, `src/revisionist/engine/campaign.py:135` `resolve_seat()` (ID or name), `src/revisionist/engine/campaign.py:145` `faction_seats()`.
- `src/revisionist/engine/session_zero.py:405` `claim()`, `src/revisionist/engine/session_zero.py:445` `search()`, `src/revisionist/engine/session_zero.py:650` `pick()` (a real person from the record).
- `src/revisionist/engine/host_ops.py:182` `link_seat()`, `src/revisionist/engine/host_ops.py:207` `unlink_seat()`.
- `src/revisionist/engine/discord/tables.py:43` `SeatLinks` (`link` `src/revisionist/engine/discord/tables.py:47`, `unlink` `src/revisionist/engine/discord/tables.py:67`, `users` `src/revisionist/engine/discord/tables.py:96`). `src/revisionist/engine/discord/tables.py:129` `Invites` (`issue` `src/revisionist/engine/discord/tables.py:135`, `redeem` `src/revisionist/engine/discord/tables.py:146`).

Goals and mandates:
- `src/revisionist/engine/session_zero.py:800` `propose_goals()` (routes: history, could_have, own), `src/revisionist/engine/session_zero.py:908` `confirm_goal()`, `src/revisionist/engine/session_zero.py:987` `history_brief()`, `src/revisionist/engine/session_zero.py:1024` `design_agent()`.
- `src/revisionist/core/goals.py:354` `check()` (progress, met, undone), `src/revisionist/core/goals.py:378` `season_winners()`, `src/revisionist/core/goals.py:496` `balance()` (flags goals too strong for a seat's power).
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

## 5. Web/JSON API and client
Backend package: `src/revisionist/engine/web/`. Stdlib `ThreadingHTTPServer` (`src/revisionist/engine/web/server.py:1175` `serve()`), plain HTTP. Bind to a private address.

Modules:
- `src/revisionist/engine/web/server.py`: the HTTP server. `App` (`src/revisionist/engine/web/server.py:120`) holds the DSN, static dir, transport, clock and `offline_prose`; `make_handler()` (`src/revisionist/engine/web/server.py:928`) builds the request handler. Serves `web/` and the JSON routes below.
- `src/revisionist/engine/web/handlers.py`: `WebHandlers(Handlers)` (`src/revisionist/engine/web/handlers.py:30`). Reuses the Discord command code; the seat is looked up in `web_seats`, not `discord_seats`.
- `src/revisionist/engine/web/accounts.py`: accounts, sessions, recovery codes and web-held seats. Scrypt password hashes (`hash_password()`, `src/revisionist/engine/web/accounts.py:44`); `Accounts` (`src/revisionist/engine/web/accounts.py:92`), `WebSeats` (`src/revisionist/engine/web/accounts.py:217`).
- `src/revisionist/engine/web/snapshot.py`: the seat's JSON, built from its own view and log. `seat_snapshot()` (`src/revisionist/engine/web/snapshot.py:169`), `checked()` (`src/revisionist/engine/web/snapshot.py:299`, leak scan before sending; raises `WithheldError`, `src/revisionist/engine/web/snapshot.py:42`), `campaign_info()` (`src/revisionist/engine/web/snapshot.py:74`), `schedule_info()` (`src/revisionist/engine/web/snapshot.py:95`), `roster()` (`src/revisionist/engine/web/snapshot.py:103`).
- `src/revisionist/engine/web/realism_api.py`: TypedDict shapes for the realism JSON: documents, desk, situation, orders, map, wake, agenda, reach, reveal and record. Types only.
- `src/revisionist/engine/web/realism_snapshot.py`: builds the realism shapes from one seat's `View`: `seat_realism()` (`src/revisionist/engine/web/realism_snapshot.py:559`), `documents()` (`src/revisionist/engine/web/realism_snapshot.py:126`), `situation()` (`src/revisionist/engine/web/realism_snapshot.py:185`), `desk()` (`src/revisionist/engine/web/realism_snapshot.py:415`), `orders()` (`src/revisionist/engine/web/realism_snapshot.py:389`), `clock()` (`src/revisionist/engine/web/realism_snapshot.py:396`), `seat_map()` (`src/revisionist/engine/web/realism_snapshot.py:289`).
- `src/revisionist/engine/web/wake_api.py`: the shared wake: `commit()` (`src/revisionist/engine/web/wake_api.py:129`), `close()` (`src/revisionist/engine/web/wake_api.py:153`), `advance()` (`src/revisionist/engine/web/wake_api.py:176`), `wake_header()` (`src/revisionist/engine/web/wake_api.py:66`), `set_wake_hours()` (`src/revisionist/engine/web/wake_api.py:168`).
- `src/revisionist/engine/web/agenda_api.py`: the agenda: live mandates, the options offered at wake open, and the play style. `agenda()` (`src/revisionist/engine/web/agenda_api.py:99`), `set_style()` (`src/revisionist/engine/web/agenda_api.py:138`), `pick_option()` (`src/revisionist/engine/web/agenda_api.py:156`). A picked option is filed through the ordinary order path.
- `src/revisionist/engine/web/record_api.py`: the seat's record block, its orders and the latest wake: `record_block()` (`src/revisionist/engine/web/record_api.py:61`). Ledger keys become opaque tokens.
- `src/revisionist/engine/web/results.py`: how each routed order landed, spoken from the seat's own view: `results()` (`src/revisionist/engine/web/results.py:117`).
- `src/revisionist/engine/web/reach_groups.py`: who the seat can reach and how, in four groups: `reach()` (`src/revisionist/engine/web/reach_groups.py:30`).
- `src/revisionist/engine/web/reveal.py`: the end-of-game reveal: `build()` (`src/revisionist/engine/web/reveal.py:54`). The one read that does not pass `snapshot.checked`.
- `src/revisionist/engine/web/new_game_api.py`: a new realism game: `timeline()` (`src/revisionist/engine/web/new_game_api.py:19`), `figures()` (`src/revisionist/engine/web/new_game_api.py:27`), `start()` (`src/revisionist/engine/web/new_game_api.py:48`).
- `src/revisionist/engine/web/dossiers.py`: dossier and setting text from `worlds/dossiers/<world>.yaml`: `load()` (`src/revisionist/engine/web/dossiers.py:179`), `for_people()` (`src/revisionist/engine/web/dossiers.py:220`), `setting()` (`src/revisionist/engine/web/dossiers.py:242`).
- `src/revisionist/engine/web/tray.py`: in-tray rules the client cannot work out alone: `acknowledgement()` (`src/revisionist/engine/web/tray.py:14`) says which papers only acknowledge an order; `feed_group()` (`src/revisionist/engine/web/tray.py:32`) says which belong to a feed.
- `src/revisionist/engine/web/__init__.py`: the package docstring: accounts, web-held seats and the JSON API.

Routes (`src/revisionist/engine/web/server.py`):
- `do_GET` (`src/revisionist/engine/web/server.py:1003`):
  - `GET /api/me` (`src/revisionist/engine/web/server.py:1006`): `{"account": null}` if signed out, else `App.state_for()` (`src/revisionist/engine/web/server.py:182`).
  - Other `GET /api/*` → 404 (`src/revisionist/engine/web/server.py:1013`). Any other `GET` → static file, or `index.html` for client routes (`src/revisionist/engine/web/server.py:1015`, `_static` at `src/revisionist/engine/web/server.py:1152`).
- `do_POST` (`src/revisionist/engine/web/server.py:1025`). Every write first runs `_same_origin()` (`src/revisionist/engine/web/server.py:986`).
  - `POST /api/signup` (`src/revisionist/engine/web/server.py:1030` → `_signup` `src/revisionist/engine/web/server.py:1073`): 201 with session cookie and recovery codes.
  - `POST /api/signin` (`src/revisionist/engine/web/server.py:1032` → `_signin` `src/revisionist/engine/web/server.py:1092`).
  - `POST /api/recover` (`src/revisionist/engine/web/server.py:1034` → `_recover` `src/revisionist/engine/web/server.py:1115`).
  - `POST /api/signout` (`src/revisionist/engine/web/server.py:1036` → `_signout` `src/revisionist/engine/web/server.py:1140`).
  - `POST /api/seat/<action>` (`src/revisionist/engine/web/server.py:1038-1045`): needs a session, dispatches via `SEAT_ACTIONS` (`src/revisionist/engine/web/server.py:831`). Replies whose text is in `REFUSALS` (`src/revisionist/engine/web/server.py:912`) return `refused: true`.
  - `POST /api/new/<action>` (`src/revisionist/engine/web/server.py:1046` → `App.new_game()` `src/revisionist/engine/web/server.py:582`). Actions: `worlds`, `timeline`, `figures` (`src/revisionist/engine/web/server.py:587-592`), and the start of a game.
  - `POST /api/game/<action>` (`src/revisionist/engine/web/server.py:1050` → `App.game()` `src/revisionist/engine/web/server.py:514`). Actions: `reveal`, `leave`, `wake-hours`, `pause`, `resume` (`src/revisionist/engine/web/server.py:523-558`).
  - `POST /api/realism/<action>` (`src/revisionist/engine/web/server.py:1054` → `App.realism()` `src/revisionist/engine/web/server.py:259`). Actions: `read` (`src/revisionist/engine/web/server.py:281`, logs `document_read`), `flag` (`src/revisionist/engine/web/server.py:291`, logs `document_flagged`; 404 for a document outside the seat's view), `lever` (`src/revisionist/engine/web/server.py:300`), `directive` and `sign` (`src/revisionist/engine/web/server.py:307`), `aide` (`src/revisionist/engine/web/server.py:348`), `consult` (`src/revisionist/engine/web/server.py:367`), `help` (`src/revisionist/engine/web/server.py:381`), `step` (`src/revisionist/engine/web/server.py:386`), `advance` (`src/revisionist/engine/web/server.py:399`), `commit` and `close` (`src/revisionist/engine/web/server.py:408`), `style` (`src/revisionist/engine/web/server.py:425`), `option` (`src/revisionist/engine/web/server.py:428`), `order` (`src/revisionist/engine/web/server.py:431`), `file` (`src/revisionist/engine/web/server.py:451`). `advance` passes a prose writer to `run_realism_tick`: `ClaudeProseWriter(transport_factory())`, or `TemplateProseWriter()` when the `App` was built with `offline_prose=True`. Pages the writer drops are logged at warning level and stay bare. Replies are in words; the CLI keeps `wake_line`.
- Seat actions (`SEAT_ACTIONS` keys, `src/revisionist/engine/web/server.py:831`, mapped to `WebHandlers`): `join`, `roster`, `search`, `claim`, `pick`, `goal`, `confirm`, `history`, `agent`, `order`, `ask`, `dossier`, `dispatch`, `status`, `report`, `bug`.
- Realism seat block, `view.realism` in `GET /api/me`: `documents`, `desk`, `situation`, `orders`, `clock`, `record`, `reach`, `map`, `agenda`. `situation()` is the Situation tab: each body line with a unit and a number-or-silent value, from arrived pages only, grouped by line and by author, never averaged; a silent latest report is a gap dated by `last_given`.
- Errors: `ApiError` (`src/revisionist/engine/web/server.py:113`). `WithheldError` returns `{"error": WITHHELD}` (`except snapshot.WithheldError` in `do_GET` and `do_POST`).
- Auth and hardening (`src/revisionist/engine/web/server.py`):
  - Session cookie `rv_session` (`src/revisionist/engine/web/server.py:77`), HttpOnly, SameSite=Strict (`src/revisionist/engine/web/server.py:959`). Token hashed at rest (`src/revisionist/engine/web/accounts.py:69`).
  - Writes need a JSON content type and an `Origin` matching `Host` (`src/revisionist/engine/web/server.py:986`).
  - Body cap 64 KiB (`src/revisionist/engine/web/server.py:78`, `src/revisionist/engine/web/server.py:997`).
  - Sign-in and recovery throttle: 10 failures per handle per 15 min (`src/revisionist/engine/web/server.py:79`, `throttled()` `src/revisionist/engine/web/server.py:168`, `failed()` `src/revisionist/engine/web/server.py:176`).
  - CSP header on every response (`src/revisionist/engine/web/server.py:106`, `src/revisionist/engine/web/server.py:943`).
  - `secure_cookie` defaults to `False` (`src/revisionist/engine/web/server.py:131`). `src/revisionist/cli.py:1372` does not pass it, so the cookie never gets `Secure`.

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
- Event log: `src/revisionist/core/events.py` (event models). `src/revisionist/core/fold.py:107` `apply()`, `src/revisionist/core/fold.py:119` `replay()`. `src/revisionist/engine/store.py:103` `load_state()`. The Postgres store reads from a snapshot plus the tail (`src/revisionist/engine/pg_store.py`).
- Schema export: `src/revisionist/schema_export.py:33` writes `schema/revisionist.schema.json`, which is committed. `tests/test_schema.py:85` checks it is current. `src/revisionist/core/__init__.py:23` `SCHEMA_VERSION = "23"`.
- Worlds: `worlds/autumn-1941.yaml`, `worlds/engine-v2-slice-1941.yaml`, `worlds/realism-slice-1941.yaml`, `worlds/realism-toy.yaml`, `worlds/salt-strait.yaml`, `worlds/salt-strait-duo.yaml`. Resolved from `src/revisionist/engine/campaign.py:33` `WORLDS_DIR` by `world_path()` (`src/revisionist/engine/campaign.py:85`). Sidecar text for two of them: `worlds/dossiers/autumn-1941.yaml` and `worlds/dossiers/engine-v2-slice-1941.yaml`. Drafts `tests/drafts/florence-1478.yaml` and `washington-1962.yaml` are fixtures.
- Briefings: `src/revisionist/engine/campaign.py:226-235` `briefings_dir()`: `REVISIONIST_BRIEFINGS_DIR`, else `<db>-briefings` beside a SQLite file, else `./revisionist-briefings`. Files `t<tick>-<seat>.md` from `FileDeliverer` (`src/revisionist/engine/campaign.py:208-223`).
- Setting card waiting for `establish confirm`: `src/revisionist/cli.py:231-234` `_card_file()`, `revisionist-card.json` beside briefings.
- Backups: `deploy/backup/revisionist-backup.sh` runs `pg_dump -Fc` into `REVISIONIST_BACKUP_DIR`. Prunes by age. Copies off-box. Restore drill: section 1.

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
- `REVISIONIST_RECORD`: `src/revisionist/engine/llm.py:245`. `1` records live calls into a recording file.
- Web: the web package (`src/revisionist/engine/web/`) reads no `REVISIONIST_*` variable of its own. `revisionist web serve` takes its database from `REVISIONIST_DB` (above) and its briefings directory from `REVISIONIST_BRIEFINGS_DIR` (above).
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
