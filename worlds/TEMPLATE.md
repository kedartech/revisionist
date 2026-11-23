# The world template

A world is a file of answers. The rules name no place, nation or era, so everything particular
to a scenario is in its world file. This document lists every question a world answers, the
world-file keys that answer it, and where a rule reads the answer. A scenario from any era is
filled in by answering these questions; no rule changes.

`scripts/world_check.py <world>` reads this document and a world, and prints for each question
whether the world answers it. `tests/test_world_template.py` fails when the world loader accepts
a key that no row here names, so this document cannot fall behind the loader.

## How to read a row

- **Question**: what the world says, in plain words.
- **Keys**: the world-file keys that answer it, as paths of field names joined by dots. A path
  passes through list items and through the free keys of a mapping without naming them:
  `sea_zones.region` is the `region` of each item of `sea_zones`. `a.{b, c}` is shorthand
  for `a.b` and `a.c`. A key named in a row whose standing is not "on main" is the name the
  building item proposes; that item fixes it.
- **Allowed values**: the closed set a rule reads, where there is one. Free wording is read by
  people and by the prose writer only.
- **Switch**: the rule (a name in the world's `rules`) that reads the answer. `-` means every
  realism world reads it; "legacy" means only the older ruleset does.
- **When absent**: what the rules do when the world leaves the line out: the default they use,
  or the mechanism that is off for want of it.
- **Needed**: `always` when every world must answer it; `with` and rule names when a world that
  switches on one of those rules must answer it; `-` otherwise.
- **Standing**: "on main" when the loader accepts the keys today; "this run:" and the plain name
  of the item that builds it; "parked" when no item is planned.

Two values are languages of their own and are read as a whole: a **condition** (a mapping with
`check:` one of `holds_office`, `controls_asset`, `entity_is`, `meter_at`,
`commitment_in_force`, `disposition_at`, `act_of`, `ordered`, `quantity_at`, `holds_area`,
`income_at`, `support_at`, `agreement_in_force`, `contest_won`, `at_war`, `regard_at`, `all_of`,
`any_of`; `src/revisionist/core/goals.py`), and an **act's effect** (a mapping with `kind:` one of
the effect kinds below; `src/revisionist/core/realism/effect.py`). A key that takes one of them
is a single row here.

Effect kinds, where a row says "an effect kind": `move_force`, `engagement`, `allocate`,
`appointment`, `measure`, `statement`, `investigate`, `deal`, `disposition`, `disclosure`,
`figure`, `group`.

Channels, where a row says "a channel": `in_person`, `telephone`, `cable`, `letter`, `courier`,
`radio`, `press`.

## Rules of the template

1. Where a rule reads an answer, the answer is one of a closed set of values. Where only people
   read it, it is free wording.
2. A world built from the record gives each authored number a source (`source:` a key of
   `sources`) or marks it a gap (`gap: true`). An invented world cites its own source entry that
   says so. A gap mark is the world saying the record is silent; it is kept apart from the
   default a rule uses when a line is absent, and the check reports the two apart.
3. A missing optional part switches its mechanism off, and the world still runs.
4. A world that switches on a rule and lacks the decider that rule needs fails the check. No
   absence ever gives a person an authority: a person with no domain commands nothing outright,
   an order outside every domain he holds is refused or held, and a question with no decider is
   one nobody can grant.
5. No part assumes a legislature, a press, a single capital, a monthly budget, three armed
   services, or a state that pays its troops.
6. A world on real coordinates (`map.coords: lonlat`) covers the whole globe; the grain may be
   coarse away from where the scenario is fought.

## The world check

```
uv run python scripts/world_check.py WORLD [WORLD ...]
uv run python scripts/world_check.py --keys
```

For each question it prints one of: `answered`; `answered, marked a gap (n of m)`, where n of the
m entries that answer it carry `gap: true`; `absent:` and what is off or what default stands;
`absent and required`, when a rule the world switches on needs the answer. Any question absent
and required makes the exit status 1. `--keys` lists loader keys with no row here. It reads the
world and does not compile it: `revisionist world check WORLD` is the command that validates a
world as a new game would and lists its unsourced numbers.

A key written with an empty value (`outlets: []`) answers its question: the world has declared
that it has none. A question a switched-on rule needs is not answered by an empty value: `locks: []`
names no decider.

## Adding a key

An item that adds a world key adds its row here in the same change: the question, the key, its
allowed values, the switch that reads it, what the rules do without it, whether a switched-on
rule needs it, and its standing. A world other than the one that first needs the key carries it
as well.

## 1. The world

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The world's file name and its title | `world`, `name` | a slug of lowercase letters, digits, `_` and `-`; free wording | - | the loader refuses the file | always | on main |
| Which ruleset the world plays | `ruleset` | `legacy`, `realism` | - | the older ruleset | - | on main |
| Which rules are switched on | `rules` | `territories`, `holders`, `economy`, `supply`, `fuel`, `battles`, `reports`, `groups`, `agreements`, `conference`, `contests`, `aims`, `aid`, `writing`, `clause_reader`, `written_orders`, `command`, `locks`, `laws`, `ask_answers`, `deciders`, `own_aim`; `holders` needs `territories`, `economy` needs `holders`, `fuel` needs `economy` | - | none of the territory game's rules is on | - | on main |
| Where and when the game opens | `start`, `start_date` | free wording; a date | - | no opening in history: Session Zero is not offered and no contest is needed | - | on main |
| The season: the day it ends and its length in real days | `settings.{end_date, real_days}` | a date; 1 to 365 days | - | a fixed number of turns | - | on main |
| How long a turn and a shared wake last | `settings.{tick_hours, world_days_per_tick, wake_hours}` | 1 to 168 hours; world days of one or more | - | a 24-hour turn of 7 world days, and a 12-hour wake | - | on main |
| The table's limits and tone | `settings`, `settings.{plausibility, inertia, lethality, betrayal, elimination, agent_harm, compromised_aide, mode, tone, starting_slots, slot_cap, lines, veils, content_rating, max_human_seats}` | `plausibility`: `strict`, `plausible`, `pulp`; `inertia`: `none`, `tendencies`, `strong`; `lethality`: `soft`, `hard`, `brutal`; `betrayal`: `cooperative`, `intrigue`, `cutthroat`; `mode`: `goals`, `open`; up to 10 human seats | - | the defaults in `src/revisionist/core/settings.py` | - | on main |
| How many people the roster holds, least and most | `roster_limit` | two whole numbers within 2 to 40 | - | 8 to 12 | - | this run: the roster bound follows the world |
| The period of income and the period of allocation | `income_period` | a number of days | - | the rules' own month | - | parked |
| How fast word travels by each kind of channel | `word_days` | days by channel | - | each channel's days fixed in the rules | - | parked |
| The published sources numbers are cited to, each marked verified or not | `sources`, `sources.{key, title, note, verified}` | free wording; `verified` true only once coverage and licence are checked | - | no number can be cited: every authored number must be a gap | - | on main |
| Each authored number cited to a source, or marked a gap | `feeds.{source, gap}`, `pipelines.{source, gap}`, `quantities.{source, gap}`, `features.{source, gap}`, `wars.{source, gap}`, `territories.{source, gap}`, `fuel_stocks.{source, gap}`, `trade_lines.{source, gap}`, `pacts.{source, gap}`, `conferences.{source, gap}`, `developments.{source, gap}` | a key of `sources` (in `developments`, a citation in words), or `gap: true`; exactly one | - | the loader refuses an entry that has neither | - | on main |
| Readings chosen where the record is disputed or silent | `notes` | free wording, 200 characters each | - | none | - | on main |

## 2. The map and what it yields

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The map file the board is drawn from | `map`, `map.{coords, file, sha256, box}` | `coords`: `lonlat`, `flat`; a `.json` file under `maps/` beside the world; its hash; `[west, south, east, north]`, needed on a flat map | `territories` | no board: the territory rules cannot be switched on | with `territories` | on main |
| Whether the map covers the whole globe | `map.cover` | `whole` | `territories` | the map may leave land as backdrop | - | this run: a whole map leaves nothing out |
| The kinds of terrain, and what each adds to a defender | `terrain`, `terrain.{key, kind, defence}` | `kind`: `land`, `sea`; `defence` 0 to 2 | `territories`, `battles` | no terrain: no area can be declared | - | on main |
| The regions areas lie in, nested | `regions`, `regions.{key, name, parent}` | a region key, never in a cycle | `territories` | no region: no area can be declared | - | on main |
| The land areas: name, region, terrain, the places in each and its finer shapes | `territories`, `territories.{key, name, region, terrain, sites, districts}` | region, terrain and place keys | `territories` | no land area on the board | - | on main |
| Who holds each territory at the start | `territories.holder` | a polity key; the compiler refuses any other kind | `holders` | the territory is held by nobody | - | on main |
| What each territory yields | `territories.yields` | by resource key, zero or more | `economy` | the territory yields nothing | - | on main |
| The sea zones | `sea_zones`, `sea_zones.{key, name, region, terrain}` | region and sea terrain keys | `territories` | no sea on the board | - | on main |
| Which areas border, and the crossings between areas that share no border | `adjacency`, `adjacency.{a, b, crossing}` | a pair of area keys, or a pair with a crossing named in words | `territories` | no area touches another: no piece can step | - | on main |
| The resources territories yield, each with its one role | `resources`, `resources.{key, name, unit, role}` | `role`: `output`, `manpower`, `fuel`, `supply`, `prestige` | `economy` | nothing is yielded | - | on main |
| The places on the map: where each lies, its theatre, the area it lies in, the sea a port opens on, and the sides and domains a base serves | `entities.{at, theatre, location, within, port_on, base}`, `entities.base.{sides, domains}` | latitude and longitude, or `[y, x]` on a flat map; area keys; `domains`: `land`, `sea`, `air` | `territories`, `supply` | the place is not on the board; with no base, no piece is supplied from it | - | on main |
| The seat of government for each nation: the place where its government sits, kept apart from places with political weight | `entities.capital` | a place within a territory, or the territory itself | `holders` | no seat: no wake's notice before the nation's capital falls, and "capital threatened" never moves a group | - | on main |
| Whether the government's seat moves with a named person or body | `entities.seat_moves` | yes, with the person or body; no | `holders` | the seat stays where the world puts it | - | parked |
| Places with political weight, and for which audience (a group, a nation, a faith), with the cost of abandoning each against losing it in a fight | `places` | a territory, the nation it matters to, the groups it moves and by how much; abandoning costs twice a loss, three times when the holder's piece stood there within 7 days | `places` | no place is weighted: losing ground moves groups only as "territory lost" | - | this run: places with political weight |
| The kinds of piece the world names, how fast each moves by terrain, its strength, fuel, reach and what it carries | `piece_kinds`, `piece_kinds.{key, name, domain, days_per_step, max_strength, fuel_per_step, range_steps, carries}` | `domain`: `land`, `sea`, `air`, `envoy`; days per step for every terrain its domain enters; reach only for an air kind | `territories` | every force is one of the five fixed kinds of feature | - | on main |
| How well a kind of piece sees and hides | `piece_kinds.{detect, conceal}` | 0 to 100 | `reports` | it sees nothing beyond contact and hides nothing | - | on main |
| A kind's own figures in battle and its picture | `piece_kinds.{attack, defence, on_terrain, against, strike_steps, covers, may_attack, holds_ground, picture}` | figures 1 to 5; a picture from the fixed list | `kinds_in_battle` | every kind fights with the rules' one arithmetic | - | this run: a kind of piece carries its own figures |
| What raising a piece of a kind costs, how long it takes, and the base it needs | `piece_kinds.{cost, lead_days, raised_at}` | output and manpower points; days; a domain of base | `raising` | no piece is raised | - | this run: raising a new piece |
| How sure a sighting must be before it names a kind | `sighting_margin` | detection above concealment by a number of points | `kinds_in_battle` | 20 points | - | this run: a sighting names a kind only when it is seen well enough |
| The kinds of weather, and which holds in each region each month | `weather` | each kind's effect on steps, figures, air and closed zones; every region and month | `weather` | no weather | - | this run: weather by season |
| Each nation's fuel stock on the start date | `fuel_stocks`, `fuel_stocks.{polity, amount}` | a polity key; zero or more, in its fuel resource's unit | `fuel` | the nation starts with the rules' stock of months of its fuel income | - | on main |
| The trade lines in force on the start date | `trade_lines`, `trade_lines.{key, exporter, importer, resource, amount, cut}` | polity and resource keys; an amount a month; whether it starts cut | `fuel` | no trade line | - | on main |
| A nation's pool of shipping for lifting its land pieces | `entities.lift_pool` | a quantity key | `territories` | the nation lifts no land piece by sea | - | on main |
| The aid finding and the production priority | `production`, `production.{findings, priority}`, `production.findings.{form, draws_on, shares, eligible}`, `production.priority.{form, grows_lift_on}` | form names; quantity keys by polity; a choice of the form | `aid` | no finding is run, and no lift pool grows by a priority | - | on main |

## 3. Nations and who decides

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The nations, factions, bodies, people and places of the world | `entities`, `entities.{key, kind, name, parent, tags}` | `kind`: `polity`, `faction`, `person`, `org`, `location`; `parent` an entity key | - | the world has nobody in it | always | on main |
| The wars in force on the start date | `wars`, `wars.{a, b, since, declared}` | polity keys, the one that began it first; a date; declared or not | - | every nation starts at peace | - | on main |
| Who allows an order a lock holds: a person, or a nation's chambers with the head of its government | `locks`, `locks.key`, `locks.decider`, `locks.decider.{person, nation, chambers, head}` | a person key; or a polity key, its chamber keys and the person at the head of its government | `locks` | no order is held for a decision | with `locks` | on main |
| Which order a lock holds, and under which condition | `locks.order`, `locks.order.{form, params, effect, zone, force}`, `locks.when`, `locks.when.{check, clause, zone, rule, form, where, posture}` | a form and some of its choices, or an effect kind with a zone or a force; `check`: `law_not_in_force`, `posture_not_set`; `rule`: `hold_fire`, `defend`, `escort`, `shoot_on_sight` | `locks` | the order needs the decision always | - | on main |
| Who is above each person: the superior who prevails, and who decides an order outside his domains | `cards.principals` | person keys | `command`, `locks` | nobody is above him: no superior prevails, and an order outside his domains has no one to allow it | with `command`, `locks` | on main |
| Who decides each kind of question: war, peace, money, posts, the office | `locks.question` | `permission`, `war`, `peace`, `money`, `posts`, `office`; with `deciders` off every row is a question of permission | `deciders` | every lock is a question of permission | with `deciders` | on main |
| Who sits on a council that decides, and how many must agree | `locks.decider.council`, `locks.decider.council.{members, needed, head}` | `members`: person keys, each with a card; `needed`: a count from 1 to the membership; `head`: the person key an ask goes to. With `deciders` off the head decides alone | `deciders` | no council: a lock's decider is one person or a body | with `deciders` | on main |
| Who decides to accept an armistice or an end to a war | `locks.question` | the lock row of kind `peace` | `peace` | the nation cannot accept a peace | with `peace` | this run: peace: an armistice and terms |
| The laws each nation has, what each binds and what it does | `laws`, `laws.{key, title, nation, clauses, passed, does, daily_life}`, `laws.does.{kind, amount}` | a key; free wording; a polity key; clauses each a `kind` (`money`, `power`, `limit`), a `subject` and, for money, an `amount`; the key of the quantity that reads 1 once the law has passed; `does.kind`: `arms_merchant_ships`, or `adds_manpower` with a whole `amount`; `daily_life`: true or false | `laws` | the locks read the rules' own table of laws; votes and shipping read that table until they read the world's laws | - | on main |
| The pacts in force on the start date | `pacts`, `pacts.{key, name, parties, wording, clauses, public}`, `pacts.clauses.{type, binds, on, force, area, region, present, nation, days, form, share, text}` | polity keys; `type`: `place`, `keep_out`, `no_war`, `no_attack`, `defend`, `form`, `aid`, `vote`, `unchecked` | `agreements` | no agreement in force on the first day | - | on main |
| The conferences the world schedules | `conferences`, `conferences.{key, caller, invited, wording, clauses, opens, voting_day, public, unanimous}`, `conferences.clauses.{type, binds, on, force, area, region, present, nation, days, form, share, text}` | polity keys, the caller among the invited; clauses as a pact's | `conference` | no conference opens unless a seat calls one | - | on main |
| Election dates inside or near the season, which chamber each redraws, and whose term ends | `elections` | the nation, the chamber or chambers, the day, and optionally a post | `elections` | no chamber is redrawn | - | this run: elections redraw a chamber |
| Whether an armed body holds a veto over the government | `armed_bodies.veto` | yes, and which body; no | - | no veto | - | parked |
| Whether a nation can be chosen by a player | `cards.playable` | a nation can be chosen when a person of it has a playable card | - | nobody can be claimed: every person is run by code | - | on main |
| What the nation may break into: the units that can leave it, each a region or a faction led by a person | `breaks_into` | regions or factions with their leader | - | the nation cannot break | - | parked |
| Who holds a territory and receives its yields: a nation, a person or a faction | `territories.held_by` | a polity, a person or a faction key | `holders` | only a nation holds territory | - | parked |

## 4. Groups at home

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| Each nation's groups at home: key, name, a free label for its kind, starting and baseline support | `groups`, `groups.{nation, groups, themes}`, `groups.groups.{key, name, kind, start, baseline}` | a polity key; support 0 to 100 | `groups` | the nation has no groups: the home rules are off for it | - | on main |
| What each group feeds, with a weight | `groups.groups.feeds` | `votes`, `standing`, `manpower`, `output`, `opinion` | `groups` | the group feeds nothing | - | on main |
| What moves each group, and by how much | `groups.groups.moved_by` | `battle_won`, `battle_lost`, `territory_taken`, `territory_lost`, `capital_threatened`, `losses_at_sea`, `agreement_broken`, `measure_passed`, `war_declared`, and with `classes` on `daily_life_passed` (a law touching daily life passed), and with `losses` on `battle_losses` (points a step lost); signed points | `groups` | nothing moves the group | - | on main |
| The chambers: each bloc's chamber and its seats | `groups.groups.{chamber, seats}` | a chamber key and one or more seats, given together | `groups` | the group is not a bloc: no chamber counts it | - | on main |
| A bloc's part of each vote, its default, and its stance on each kind of clause | `groups.groups.{votes, vote_default, stances}`, `groups.groups.votes.{voting, yeas}`, `groups.groups.vote_default.{voting, yeas}` | members voting and yeas among them, by measure and vote; stances on `money`, `power`, `limit` in points | `groups` | the bloc's part of a vote is read from the rules' own default | - | on main |
| Whether a group hears another nation's writing | `groups.groups.abroad` | true or false | `writing` | it hears only its own nation's | - | on main |
| The themes a nation's writing may name, and how far each moves each group | `groups.themes`, `groups.themes.{key, name, moves}` | by group key, signed points within the day's cap | `writing` | writing names no theme | - | on main |
| The size of losses as a happening, and how far it moves each group | `groups.groups.moved_by` | `battle_losses`: signed points a step lost, capped at 3 a group a day; mixed unless `happenings` classes it, half felt, the felt share landing over the 21 days after; a battle won counts half | `losses`, with `groups` | losses move no group except at sea | - | on main |
| A bloc's price list | `groups.groups.prices`, `groups.groups.prices.{key, sentence, condition, days, points, loss}` | a key, once in the bloc; free wording; a condition built from the checks aims use, holding at least one check an act changes (`ordered`, `quantity_at`, `holds_office`, `agreement_in_force`); days from 1 to 366 after the measure passes; points of yes share from 1 to 20; the support lost if unmet, 0 to 100. Only a chamber's bloc has prices, and a measure is a law of the bloc's nation (`laws`) | `offers`, with `groups` and `laws` | no bloc can be offered a price | - | on main |
| Whether a group is a service of the armed forces, and which posts see it | `groups.groups.service` | yes, with the posts; no | - | every group is seen by its nation | - | parked |

## 5. Offices and posts

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The offices and other holdings: kind, tier, holder, place, loyalty and who knows of it | `assets`, `assets.{key, kind, name, tier, controller, location, loyalty, scope}`, `assets.scope.{visibility, known_by}` | `kind`: `force`, `wealth`, `network`, `office`, `info`, `facility`; tier 0 to 5; `public`, or `visibility` `restricted`, `private`, `covert` with seat keys | - | no holding: an aim of holding an office has nothing to read | - | on main |
| A person's office in words, the powers it carries and what constrains it | `cards.{office, powers, constraints}` | free wording | - | none | - | on main |
| Each domain of authority: what it covers, who carries its orders out, and which forces it commands | `cards.authority`, `cards.authority.{name, effects, executor, forces, summary}` | effect kinds; person and force keys | `command`, `locks` | the person commands nothing outright | - | on main |
| Who succeeds the holder | `cards.successor` | a person key | - | nobody is named to succeed | - | on main |
| The post a person holds, apart from the person | `cards.post` | an office asset's key, an office the person controls, no other card's post | `posts` | the card is its person's alone, as today | - | on main |
| What a post rests on, and how its holder is removed | `cards.post.{rests_on, removed_by}` | one or two groups or bodies; a body's vote, a council, one person, the end of a term, or not at all | `office` | the holder faces no question on his office | - | this run: the office question as a formal sitting |
| The support line and the days under it at which the base turns on the holder | `cards.post.turn_below` | a support line, and days for the warning and for the question | `office` | 30, 14 days and 21 days | - | this run: blocs turn on the leader |
| The ladder below a post, and who may move its holder | `cards.post.{ladder, moved_by}` | post keys, never in a loop | `posts` | a dismissal leaves the holder with no post, and only a decider's grant moves him | - | this run: the ladder of posts |
| Which kinds of question a post decides outright | `cards.post.decides` | `permission`, `war`, `peace`, `money`, `posts`, `office` | `deciders` | the post decides only through the lock rows | with `deciders` | this run: player, person and post kept apart |

## 6. Armed bodies and forces

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The armed bodies the world declares, not assumed to be an army, a navy and an air arm | `armed_bodies` | a list | - | forces belong to their side alone | - | parked |
| Who pays each armed body, and who each answers to | `armed_bodies.{paid_by, answers_to}` | the state, a region, its commander or a patron; an office or a person | - | the state pays every force | - | parked |
| Each force, front or route: its kind, side, strength, places, and the day it enters service | `features`, `features.{key, kind, name, side, tier, places, as_of, in_service, piece}` | `kind`: `fleet`, `army`, `air`, `front`, `route`, `piece`; tier 0 to 5; a `piece` names one of the world's kinds | - | no force on the board | - | on main |
| The moves the record says a force made, what it took and whether it moved concealed | `features.legs`, `features.legs.{since, places, takes, concealed}` | a date; place or area keys; territory keys | `holders`, `reports` | the force stays where it starts | - | on main |
| Each force's named deputy | `features.deputy` | a person key | - | no deputy | - | parked |
| Who raised each force: the centre, a region or a person | `features.raised_by` | the centre, a region key or a person key | - | the centre raised it | - | parked |
| What a commander may do with no permission | `cards.post.attempts` | from the closed list: cross a border, fire first, blockade | `defiance` | nothing is done without permission | - | this run: acting without permission, and refusing an order from above |
| Each nation's intelligence: its sources in rank order, who reports each and by what channel, its codebreaking and its agents | `intelligence`, `intelligence.{nation, sources, codebreaking, agents}`, `intelligence.sources.{source, person, channel, skew}`, `intelligence.agents.{area, until}` | `source`: `contact`, `air`, `patrol`, `codebreaking`, `agent`; a channel; skew -5 to 5; codebreaking 0 to 3 | `reports` | the nation learns by contact only | - | on main |

## 7. People

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| Each person's card: who it is, whether a player may take it, and the path | `cards`, `cards.{person, playable, path}` | a person key; `path`: `political`, `military` | `command` | the person has no card and is run by nobody | - | on main |
| The person's character: voice, loyalty, competence, doctrine, interests, personal notes, how far ahead he plans, and how a letter to him opens | `cards.{voice, loyalty, competence, doctrine, interests, personal, horizon_days, addressed_as}` | loyalty -5 to 5; competence 0 to 5; 1 to 365 days | - | the defaults: loyalty 0, competence 3 | - | on main |
| The inner circle, and the channel each reaches him by | `cards.inner_circle`, `cards.inner_circle.{person, channel}` | a person key; a channel | - | he hears from nobody close | - | on main |
| His reach: rank, the chain who answer his summons, and whether he heads it | `cards.reach`, `cards.reach.{rank, chain, heads}` | rank 0 to 5; person keys | - | rank 0, no chain | - | on main |
| Whom he stands with, and what he is set against | `cards.{allies, opposes}`, `cards.opposes.{against, over, irreducible}` | polity or person keys; at most six oppositions | - | none | - | on main |
| Ties to other people: regard, what each would take, what each could be pressed with, and who knows | `relationships`, `relationships.{key, a, b, disposition, price_tags, leverage_tags, scope}`, `relationships.scope.{visibility, known_by}` | entity keys; regard -5 to 5 | - | regard 0 between any two | - | on main |
| What a person wants and holds to, named once as topics | `cards.{wants, holds_to}`, `topics`, `topics.{key, name, levers, effects, words}` | topic keys; form names, effect kinds, lower-case words | - | he wants nothing and holds to nothing | - | on main |
| The roster: each character's pitch and reach, whether real or composite, his means, his side in each contest, and other names | `roster`, `roster.{entity, pitch, reach, composite, means, sides, aliases}`, `roster.sides.{contest, side}` | a person key; `composite` true or false, always written; asset keys | - | nobody can be claimed | - | on main |
| Whether a person is playable by a rule, with a floor the world sets and a hold-back flag | `playable_floor`, `cards.held_back` | a rank and a force tier; true or false | `playable_rule` | playable as each card is flagged | - | this run: playable by rule |
| Loyalty in three layers: to the office above, to the person above, to the cause | `cards.loyalty_to` | -5 to 5 each | - | one loyalty | - | parked |

## 8. Aims

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| A person's aims in words | `cards.aims` | free wording, at most three | - | he has no aim | - | on main |
| What makes an aim a goal: its condition, its rule in words, its period, and whether it may be replaced | `cards.aim_rules`, `cards.aim_rules.{aim, condition, rule, opens, deadline, replaceable}` | aim 1 to 3; a condition; dates | `aims` | the aim is words only and scores nothing | - | on main |
| Aim patterns for each kind of post, with blanks a player fills | `aim_patterns`, `aim_patterns.{key, posts, sentence, condition, blanks, government, deadline}`, `aim_patterns.blanks.{name, values, kind}`, `cards.post_kind` | a key; `posts`: kinds of post, each a card's `post_kind` or its path (`political`, `military`); a sentence naming each blank as `{name}`; a condition over the checks aims use, each blank written `$name` (`$nation` and `$person` stand for the person's own nation and the person); a blank's `values`, world keys, group keys or whole numbers, or its `kind`: `territory_not_held`, `territory_held`, `other_nation`, `own_group`; `government`: true or false; `deadline`: a date, else the replaced aim's | `own_aim` | a player writes no aim of his own | - | on main |
| For a replacement character, the two aims both required | `cards.aim_rules.replaceable` | the aims not marked replaceable; a replacement character must hold both (the replacement character, built this run, reads them) | `aims` | a replacement has no aim that is not replaceable | - | on main |
| The contests: kind, prize, sides, track, momentum, the day each ends, and who knows | `contests`, `contests.{key, kind, name, prize, sides, track, momentum, countdown_days, scope}`, `contests.scope.{visibility, known_by}` | `kind`: `rivalry`, `trial`; two to four sides, or one on trial; track -100 to 100 | `contests` | no contest | - | on main |
| What moves a contest's track | `contests.moves`, `contests.moves.{kind, toward, step, region, territory, quantity, nation, group, line, falling, between}` | `kind`: `battle`, `holder`, `flag`, `line`, `agreement_made`, `agreement_broken`; a side | `contests` | only the countdown decides it | - | on main |
| The mandates: what triggers each, who it goes to, who issues it, and the condition it asks for | `mandates`, `mandates.{key, kind, trigger, to, issuer, text, condition, days}`, `mandates.trigger.{on, history, quantity, op, value, effect}` | `kind`: `order`, `crisis`, `blowback`, `opportunity`; `on`: `history`, `quantity`, `act`; `op`: `ge`, `le`; an effect kind; a condition | - | no mandate is issued | - | on main |

## 9. Happenings and public word

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The history schedule: dated events, each with the condition under which it still happens, and its headline | `schedule`, `schedule.{key, name, on_date, condition, weight, scope, headline, subject, obj}`, `schedule.scope.{visibility, known_by}` | a date; a condition; weight 1 to 3; entity keys | - | history has no clock | - | on main |
| The deck of developments: when each may fall, its chance, condition, headline, effects and the orders it suggests | `developments`, `developments.{key, name, category, window, chance, condition, headline, subject, obj, effects, asks}`, `developments.window.{start, end}`, `developments.effects.{kind, quantity, percent, of, toward, change}` | `category`: `technology`, `public_figures`, `espionage`, `unrest`, `weather`; chance 1 to 100; a figure moved by a percent or a regard moved; read from `developments/<world>.yaml` beside the world | - | no development falls | - | on main |
| The class of each kind of happening | `happenings`, `happenings.{kind, reach}` | `kind`: a kind of happening a group may be moved by (part 4, plus `daily_life_passed`, a law touching daily life passed); `reach`: `felt`, `reported`, `secret`; each kind once. A secret kind moves no group | `classes` | every happening is reported | - | on main |
| For a mixed kind, the share of it that is felt | `happenings.felt` | a share from 0 to 1, on a reported kind (a felt kind is felt whole; a secret kind has none) | `classes` | a felt kind is felt whole, a reported one not at all | - | on main |
| The outlets of public word: whom each answers to and its voice | `outlets`, `outlets.{key, polity, name, voice}` | an org entity key and its polity; free wording; may be empty | - | no outlet: a reported happening still reaches each audience, at the world's speed of word and with no outlet's slant | - | on main |

## 10. Papers, forms and answers

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The papers that reach each person: author, kind, channel, classification, how often and how late, what each reports and sights, and its bias | `feeds`, `feeds.{key, name, author, kind, channel, classification, every_days, latency_days, assumed, reports, sights, bias}`, `feeds.bias.{skew_pct, noise_pct, omit_pct, delay_days}`, `cards.feeds` | `kind`: `report`, `cable`, `memo`, `letter`, `poll`, `press`, `whip_count`, `intercept`, `transcript`; a channel; `classification`: `open`, `restricted`, `confidential`, `secret`, `most_secret`; quantity and feature keys | - | the person reads nothing | - | on main |
| The figures of the world: owner, value, unit, the day it stands, whether public, and whether code computes it | `quantities`, `quantities.{key, owner, name, value, unit, as_of, public, computed}` | entity keys; a number, or none for a gap or a computed figure | - | no figure | - | on main |
| The paths an order takes: who handles each step, a decision or a clerk's, how long, and what each may do | `pipelines`, `pipelines.{key, name, steps}`, `pipelines.steps.{person, kind, days, assumed, allowed}`, `cards.pipelines` | `kind`: `decision`, `clerical`; `allowed`: `expedite`, `stall`, `leak`, `amend`, `refuse`, `pass` | - | an order has no path and cannot be sent | - | on main |
| The forms a person may give: the path each takes, the rule that resolves it, its choices, and the choices allowed only at war | `cards.levers`, `cards.levers.{name, pipeline, resolver, params, label, summary, needs_war}`, `cards.levers.params.{name, kind, lo, hi, choices, label, choice_labels}`, `cards.levers.needs_war.{nation, refusal}` | `resolver`: `votes`, `shipping`, `production`, `opinion`, `movement`, `war`, `economy`, `trade`, `intel`; `kind`: `int`, `enum`, `entity`, `text` | - | the person can give no form | - | on main |
| The escort level a form's choice sets | `cards.levers.escort_level` | 0, 1 or 2 on every choice of one parameter, or none | - | shipping reads no escort level from the form | - | on main |
| What a person nobody plays does back: when, toward whom, the act, how soon and how often | `cards.answers`, `cards.answers.{key, aim, when, gate, act, delay_days, cooldown_days, until, helps}`, `cards.answers.when.{lever, params, effect, party, by, human, every_days, start}`, `cards.answers.act.{lever, params, effect}` | an effect kind; `gate`: `hostile`, `obstructing`, `neutral`, `cooperative`, `aligned`; an act's effect | - | he does nothing back | - | on main |

## 11. The older ruleset

| Question | Keys | Allowed values | Switch | When absent | Needed | Standing |
|---|---|---|---|---|---|---|
| The seats at the table, whom each embodies, and its chief of staff | `seats`, `seats.{key, kind, name, embodies, controller, slots, objectives, standing_orders, agent}`, `seats.agent.{entity, name, role, voice, backstory, relationship}` | `kind`: `player`, `faction`, `outlet`, `npc`; `controller`: `human`, `ai`; a realism world writes `seats: []` | legacy | no seat is named | - | on main |
| Each seat's secret goal | `goals`, `goals.{key, seat, text, condition, canary}` | a seat key; a condition | legacy | no goal | - | on main |
| Meters: an owner's named figure and its bounds | `meters`, `meters.{key, owner, name, value, lo, hi, max_delta_per_tick, scope}`, `meters.scope.{visibility, known_by}` | entity keys; bounds | legacy | no meter | - | on main |
| Clocks: operations, objectives, threats, opportunities and capabilities | `clocks`, `clocks.{key, kind, name, owner, target, segments_total, segments_filled, exposure, holds_slot, scope}`, `clocks.scope.{visibility, known_by}` | `kind`: `operation`, `objective`, `threat`, `opportunity`, `capability`; 1 to 12 segments | legacy | no clock | - | on main |
| Facts: what is true of whom, how exposed, and who knows | `facts`, `facts.{key, subject, predicate, obj, truth, exposure, scope, canary}`, `facts.scope.{visibility, known_by}` | entity keys; exposure 0 to 5 | legacy | no fact | - | on main |
| Commitments between parties, and their clauses | `commitments`, `commitments.{key, parties, clauses, status, scope}`, `commitments.clauses.{kind, party, beneficiary, asset, verb, amount, until_tick}`, `commitments.scope.{visibility, known_by}` | `kind`: `transfer`, `abstain`, `support`, `payment`; `status`: `offered`, `accepted`, `broken`, `expired`, `withdrawn` | legacy | no commitment | - | on main |

## The pre-modern check, written in

The draft template was checked on paper against a pre-modern case. Its four changes are rows
above:

1. **A seat of government apart from places with political weight.** The seat is where the
   government sits (`entities.capital`, part 2); a place with political weight is its own row
   (`places`, part 2), and losing one is its own happening whether or not it is the seat.
   Whether the seat moves with a person or a body is parked.
2. **A world with no outlet.** `outlets: []` is an answer (part 9). With no outlet, a reported
   happening still reaches each audience, at the world's speed of word and with no slant.
3. **A unit that can leave as a region or a faction** led by a person (part 3): parked.
4. **A holder that is a person or a faction** (part 3): parked. Today a territory's holder must
   be a polity: the compiler refuses any other kind of entity
   (`src/revisionist/core/world_compile.py`, the check of each territory's holder).
