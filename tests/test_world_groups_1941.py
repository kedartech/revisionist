"""1941 groups at home for each nation (GRD).

Autumn 1941 switches on ``groups``. Each of the seven nations declares its groups at home,
each with a source line or ``gap: true`` (a comment on the group's ``- key:`` line: a group
has no citation field of its own). The United States has six blocs, a party's members and
the other members of each chamber, whose seats are the world's party-division quantities,
and whose rows for the four bills are the record the votes module holds, so that with every
bloc at its baseline each bill's tally is the recorded vote. The themes the nations' writing
already names (the address form's choices, the standing orders' statements) each move
groups, every group lists what moves it, and the American public starts at the Gallup figure
the world cites.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core.ids import EntityId, OrderId, derived_id
from revisionist.core.realism import groups
from revisionist.core.realism.resolvers import opinion, votes
from revisionist.core.state import Rule
from tests.test_realism_resolvers import Rig

WORLD = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"
SEVEN = ("usa", "uk", "ussr", "germany", "japan", "italy", "china")
CITED = re.compile(r"#\s*(?:source:\s*(?P<key>[a-z0-9_]+)|gap:\s*true)")
PARTY = {"D": "democrats", "R": "republicans", "other": "other"}
CHAMBER = {"house": "house", "concur": "house", "senate": "senate"}
BLOCS = {
    f"{chamber}_{party}": (chamber, party)
    for chamber in ("house", "senate")
    for party in ("democrats", "republicans", "other")
}
US_OTHERS = ("public", "non_interventionists", "labour", "press")


def raw() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return doc


def section(name: str) -> list[str]:
    """The lines of the top-level section ``name``, as written."""
    lines = WORLD.read_text().splitlines()
    first = lines.index(f"{name}:")
    rest = next(i for i in range(first + 1, len(lines)) if re.match(r"[a-z_]+:", lines[i]))
    return lines[first + 1 : rest]


def declared() -> dict[str, dict[str, Any]]:
    return {d["nation"]: d for d in raw()["groups"]}


def us_groups() -> dict[str, dict[str, Any]]:
    return {g["key"]: g for g in declared()["usa"]["groups"]}


def quantity(key: str) -> dict[str, Any]:
    return next(q for q in raw()["quantities"] if q["key"] == key)


@pytest.fixture(scope="module")
def rig() -> Rig:
    r = Rig()
    r.seat("roosevelt")
    r.close_session_zero()
    return r


def usa(r: Rig) -> EntityId:
    return EntityId(r.ids["usa"])


# --- the world file ----------------------------------------------------------------


def test_the_world_switches_on_groups(rig: Rig) -> None:
    assert "groups" in raw()["rules"]
    assert Rule.GROUPS in rig.state.rules


def test_each_of_the_seven_nations_declares_its_groups_once() -> None:
    nations = [d["nation"] for d in raw()["groups"]]
    assert sorted(nations) == sorted(SEVEN)
    for nation, d in declared().items():
        n = len(d["groups"])
        if nation == "usa":  # the six blocs and the four groups the plan names
            assert n == len(BLOCS) + len(US_OTHERS)
        else:
            assert 4 <= n <= 8, nation


def test_every_group_carries_a_source_or_a_gap() -> None:
    sources = {s["key"] for s in raw()["sources"]}
    entries = [ln for ln in section("groups") if re.match(r"\s+- key: ", ln)]
    assert len(entries) == sum(len(d["groups"]) for d in declared().values())
    assert [ln.strip() for ln in entries if not cited(ln, sources)] == []


def cited(line: str, sources: set[str]) -> bool:
    m = CITED.search(line)
    return m is not None and (m["key"] is None or m["key"] in sources)


def test_the_united_states_has_six_blocs_and_the_four_named_groups() -> None:
    found = us_groups()
    assert set(found) == set(BLOCS) | set(US_OTHERS)
    for key, (chamber, _) in BLOCS.items():
        assert found[key]["chamber"] == chamber, key
    assert all("chamber" not in found[k] for k in US_OTHERS)


def test_a_blocs_seats_are_the_party_division_raised_to_the_most_members_voting() -> None:
    for key, g in us_groups().items():
        if key not in BLOCS:
            continue
        rows = [*g.get("vote_default", {}).values()]
        rows += [v for m in g.get("votes", {}).values() for v in m.values()]
        most = max(v["voting"] for v in rows)
        assert g["seats"] == max(quantity(key)["value"], most), key


def test_every_bloc_starts_at_its_baseline() -> None:
    for key in BLOCS:
        g = us_groups()[key]
        assert g["start"] == g["baseline"], key


def recorded(bill: str, vote: str, party: str) -> tuple[int, int]:
    """The record's (members voting, yeas) for one party on one vote."""
    row = next(r for r in votes.TALLIES[bill][vote] if PARTY[r[0]] == party)
    return row[1] + row[2], row[1]


def test_each_blocs_rows_are_the_record_the_votes_module_holds() -> None:
    found = us_groups()
    for key, (chamber, party) in BLOCS.items():
        rows = found[key]["votes"]
        expected = {
            bill: {vote: recorded(bill, vote, party) for vote in by if CHAMBER[vote] == chamber}
            for bill, by in votes.TALLIES.items()
        }
        assert {
            bill: {vote: (v["voting"], v["yeas"]) for vote, v in by.items()}
            for bill, by in rows.items()
        } == expected, key
        novel = {
            vote: (y + n, y)
            for vote, rs in votes.NOVEL_ROWS.items()
            if CHAMBER[vote] == chamber
            for p, y, n in rs
            if PARTY[p] == party
        }
        default = found[key]["vote_default"]
        assert {vote: (v["voting"], v["yeas"]) for vote, v in default.items()} == novel, key


@pytest.mark.parametrize(("bill", "vote"), [(b, v) for b, by in votes.TALLIES.items() for v in by])
def test_with_every_bloc_at_its_baseline_each_bills_tally_is_the_recorded_vote(
    rig: Rig, bill: str, vote: str
) -> None:
    state, nation = rig.state, usa(rig)
    for g in groups.of(state, nation):
        assert groups.support(state, nation, g.key) == g.baseline, g.key
    rows = votes.TALLIES[bill][vote]
    want = (sum(y for _, y, _ in rows), sum(n for _, _, n in rows))
    for n in range(5):
        seed = OrderId(derived_id(rig.campaign, "grd-seed", n))
        got = votes.bloc_tally(state, nation, CHAMBER[vote], bill, vote, seed)
        assert got == want, (bill, vote, n)


def test_a_bill_the_record_does_not_hold_takes_the_borrowed_rows(rig: Rig) -> None:
    state, nation = rig.state, usa(rig)
    seed = OrderId(derived_id(rig.campaign, "grd-seed", "novel"))
    for vote, rows in votes.NOVEL_ROWS.items():
        want = (sum(y for _, y, _ in rows), sum(n for _, _, n in rows))
        assert votes.bloc_tally(state, nation, CHAMBER[vote], "a_new_act", vote, seed) == want


def test_the_american_public_starts_at_the_gallup_figure_the_world_cites(rig: Rig) -> None:
    gallup = quantity("gallup_fdr_about_right")
    assert gallup.get("source") == "gallup_1941" and isinstance(gallup["value"], int)
    public = us_groups()["public"]
    assert public["start"] == gallup["value"]
    assert opinion.figure(rig.state, usa(rig), start=True) == gallup["value"]
    assert opinion.figure(rig.state, usa(rig)) == gallup["value"]


def test_every_group_lists_what_moves_it() -> None:
    for nation, d in declared().items():
        for g in d["groups"]:
            assert g.get("moved_by"), (nation, g["key"])


def statement_themes() -> dict[str, set[str]]:
    """Each leader's nation and the themes its standing answers' statements name."""
    doc = raw()
    parent = {e["key"]: e.get("parent") for e in doc["entities"]}
    out: dict[str, set[str]] = {}
    for card in doc["cards"]:
        for answer in card.get("answers") or []:
            effect = (answer.get("act") or {}).get("effect") or {}
            if effect.get("kind") == "statement":
                out.setdefault(parent[card["person"]], set()).add(effect["theme"])
    return out


def address_themes() -> set[str]:
    doc = raw()
    card = next(c for c in doc["cards"] if c["person"] == "roosevelt")
    lever = next(lv for lv in card["levers"] if lv["name"] == "public_address")
    param = next(p for p in lever["params"] if p["name"] == "theme")
    return set(param["choices"]) | set(param["choice_labels"])


def test_the_themes_the_writing_already_names_each_move_groups(rig: Rig) -> None:
    themes = statement_themes()
    assert set(themes) <= set(SEVEN) and len(themes) == len(SEVEN)
    themes["usa"] |= address_themes()
    for nation, said in themes.items():
        polity = EntityId(rig.ids[nation])
        for text in sorted(said):
            theme = groups.named_theme(rig.state, polity, text)
            assert theme is not None, (nation, text)
            assert theme.moves, (nation, text)


def test_a_statement_names_its_own_theme_not_a_shorter_one(rig: Rig) -> None:
    uk = EntityId(rig.ids["uk"])
    found = groups.named_theme(rig.state, uk, "a warning to Japan over Malaya")
    assert found is not None and "malaya" in found.key
