"""The 1941 yields (YLS): what each land territory yields, as a staging file.

``worlds/maps/src/autumn-1941/yields.yaml`` gives every land territory of the 1941 map its
industry, manpower, oil, supply (rail hubs and ports) and prestige, each with a source and its
evidence record or a ``gap: true`` mark, under scales stated once at the top of the file; and the
trade lines and fuel stocks in force on the start date. The item that converts the world (FLP)
folds the numbers into each territory's ``yields``, so the game plays as today until then. These
tests read the file against the map's world fragment (``worlds/maps/autumn-1941.world.yaml``) and
the 1941 start (``worlds/maps/src/autumn-1941/start.yaml``: the resources, the places and each
territory's holder).
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core.world import FuelStockDecl, SourceDecl, TradeLineDecl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "worlds" / "maps" / "src" / "autumn-1941"
YIELDS = SRC / "yields.yaml"
START = SRC / "start.yaml"
FRAGMENT = ROOT / "worlds" / "maps" / "autumn-1941.world.yaml"

CAPITAL_PLACE = {
    "usa": "washington",
    "uk": "london",
    "japan": "tokyo",
    "germany": "berlin",
    "italy": "rome",
    "ussr": "moscow",
    "china": "chungking",
}
"""Each seated nation's capital, as a place of the 1941 world."""

INDUSTRY_RATIO = {
    "usa": 42,
    "germany": 20,
    "ussr": 14,
    "uk": 10,
    "japan": 4,
    "italy": 3,
    "china": 1,
}
"""The plan's default industry totals per nation [proposed, until sourced]: Germany's 20 is its
own 14 and occupied Europe's 6."""

GERMANY_OWN = 14
OCCUPIED_EUROPE = 6

EVIDENCE_FIELDS = ("source", "edition", "locator", "claim", "calculation", "checked_by")
"""What an evidence record must give for a yield to count as sourced (rule 6)."""


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return dict(_yaml(YIELDS))


@pytest.fixture(scope="module")
def start() -> dict[str, Any]:
    return dict(_yaml(START))


@pytest.fixture(scope="module")
def fragment() -> dict[str, Any]:
    return dict(_yaml(FRAGMENT))


def _resources(start: dict[str, Any]) -> list[str]:
    return [str(r["key"]) for r in start["resources"]]


def _rows(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t["key"]): t for t in doc["territories"]}


def _holders(start: dict[str, Any]) -> dict[str, str]:
    return {str(h["territory"]): str(h["holder"]) for h in start["holders"]}


def _within(start: dict[str, Any], place: str) -> str:
    for e in start["entities"]:
        if e["kind"] == "location" and e["key"] == place:
            return str(e["within"])
    raise KeyError(place)


def _amount(doc: dict[str, Any], territory: str, resource: str) -> float:
    return float(_rows(doc)[territory][resource]["amount"])


def _total(doc: dict[str, Any], start: dict[str, Any], polity: str, resource: str) -> float:
    rows = _rows(doc)
    return sum(
        float(rows[t][resource]["amount"]) for t, h in _holders(start).items() if h == polity
    )


def _sources(doc: dict[str, Any]) -> set[str]:
    return {SourceDecl.model_validate(s).key for s in doc["sources"]}


def _evidence(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(e["key"]): e for e in doc.get("evidence") or []}


def _check_cited(doc: dict[str, Any], entry: dict[str, Any], where: str) -> None:
    """A sourced figure names an evidence record with every field; a gap names the source it
    would be taken from and why the figure is what it is."""
    gap, source = entry.get("gap") is True, entry.get("source")
    assert gap != (source is not None), f"{where}: give exactly one of source or gap: true"
    if source is not None:
        record = _evidence(doc).get(str(source))
        assert record is not None, f"{where}: source {source} has no evidence record"
        for field in EVIDENCE_FIELDS:
            assert str(record.get(field) or "").strip(), f"{where}: evidence lacks {field}"
        assert record["source"] in _sources(doc), f"{where}: evidence cites an unknown source"
    else:
        assert entry.get("named_source") in _sources(doc), f"{where}: gap names no source"
        assert str(entry.get("basis") or "").strip(), f"{where}: gap gives no basis"


# ------------------------------------------------ rule 1: every territory, five yields


def test_every_land_territory_has_a_row_and_no_sea_zone_has_one(
    doc: dict[str, Any], fragment: dict[str, Any]
) -> None:
    keys = [str(t["key"]) for t in doc["territories"]]
    assert len(keys) == len(set(keys))
    assert set(keys) == {str(t["key"]) for t in fragment["territories"]}


def test_every_row_has_a_yield_for_each_of_the_five_resources(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    resources = _resources(start)
    assert resources == ["industry", "manpower", "oil", "supply", "prestige"]
    for key, row in _rows(doc).items():
        assert set(row) == {"key", *resources}, key
        for r in resources:
            amount = row[r]["amount"]
            assert isinstance(amount, int | float) and amount >= 0, (key, r)


def test_every_yield_has_a_source_with_its_evidence_or_a_gap_mark(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    for key, row in _rows(doc).items():
        for r in _resources(start):
            _check_cited(doc, row[r], f"{key}.{r}")


def test_a_source_with_no_evidence_record_is_refused(doc: dict[str, Any]) -> None:
    entry = {"amount": 1, "source": "harrison_1998"}
    with pytest.raises(AssertionError, match="no evidence record"):
        _check_cited({**doc, "evidence": []}, entry, "probe")


def test_an_evidence_record_missing_who_checked_it_is_refused(doc: dict[str, Any]) -> None:
    record = {f: "x" for f in EVIDENCE_FIELDS} | {"key": "probe", "source": "harrison_1998"}
    record["checked_by"] = ""
    with pytest.raises(AssertionError, match="checked_by"):
        _check_cited({**doc, "evidence": [record]}, {"amount": 1, "source": "probe"}, "probe")


def test_a_full_evidence_record_makes_a_yield_sourced(doc: dict[str, Any]) -> None:
    record = {f: "x" for f in EVIDENCE_FIELDS} | {"key": "probe", "source": "harrison_1998"}
    _check_cited({**doc, "evidence": [record]}, {"amount": 1, "source": "probe"}, "probe")


def test_every_evidence_record_is_complete(doc: dict[str, Any]) -> None:
    for key, record in _evidence(doc).items():
        for field in EVIDENCE_FIELDS:
            assert str(record.get(field) or "").strip(), (key, field)


# ------------------------------------------------ rule 2: the scales, once, at the top


def test_the_scales_are_stated_once_at_the_top(doc: dict[str, Any], start: dict[str, Any]) -> None:
    text = YIELDS.read_text()
    assert next(iter(doc)) == "scales"
    assert text.count("\nscales:") + text.startswith("scales:") == 1
    scales = doc["scales"]
    assert list(scales) == _resources(start)
    for r, scale in scales.items():
        assert str(scale.get("unit") or "").strip(), r
        _check_cited(doc, scale, f"scales.{r}")


def test_industry_is_scaled_to_a_cited_measure_of_war_production(doc: dict[str, Any]) -> None:
    industry = doc["scales"]["industry"]
    assert industry["totals"] == INDUSTRY_RATIO
    assert str(industry.get("measure") or "").strip()


def test_manpower_is_from_1941_population_and_oil_from_1941_crude(doc: dict[str, Any]) -> None:
    assert "population" in doc["scales"]["manpower"]["measure"]
    assert "crude" in doc["scales"]["oil"]["measure"]
    assert doc["scales"]["oil"]["million_tonnes_a_year_per_point"] == 3


@pytest.mark.parametrize("nation", sorted(INDUSTRY_RATIO))
def test_each_nations_industry_keeps_the_ratio(
    doc: dict[str, Any], start: dict[str, Any], nation: str
) -> None:
    assert _total(doc, start, nation, "industry") == pytest.approx(INDUSTRY_RATIO[nation])


def test_germany_holds_its_own_14_and_occupied_europes_6(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    own = doc["scales"]["industry"]["germany_own"]
    assert all(_holders(start)[t] == "germany" for t in own)
    assert sum(_amount(doc, t, "industry") for t in own) == pytest.approx(GERMANY_OWN)
    occupied = _total(doc, start, "germany", "industry") - GERMANY_OWN
    assert occupied == pytest.approx(OCCUPIED_EUROPE)


def test_supply_counts_the_hubs_the_row_names(doc: dict[str, Any]) -> None:
    for key, row in _rows(doc).items():
        hubs = row["supply"].get("hubs") or []
        assert len(hubs) == len(set(hubs)), key
        assert row["supply"]["amount"] == len(hubs), key


# ------------------------------------------------ rule 3: the named anchors


@pytest.mark.parametrize("territory", ["kharkov_area", "leningrad_area", "donbas"])
def test_the_soviet_works_carry_industry(doc: dict[str, Any], territory: str) -> None:
    assert _amount(doc, territory, "industry") > 0


def test_kharkov_leningrad_and_the_donbas_are_among_the_soviet_unions_largest_works(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    soviet = [t for t, h in _holders(start).items() if h == "ussr"]
    ranked = sorted(soviet, key=lambda t: -_amount(doc, t, "industry"))
    assert {"kharkov_area", "leningrad_area", "donbas"} <= set(ranked[:5])


@pytest.mark.parametrize(
    ("place", "territory"),
    [("baku", "caucasus"), ("ploesti", "romania"), ("the Dutch East Indies", "dutch_east_indies")],
)
def test_the_oil_fields_carry_oil(doc: dict[str, Any], place: str, territory: str) -> None:
    assert _amount(doc, territory, "oil") > 0, place


def test_baku_is_the_largest_oil_outside_the_united_states(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    holders = _holders(start)
    rest = [t for t in _rows(doc) if holders[t] != "usa"]
    assert max(rest, key=lambda t: _amount(doc, t, "oil")) == "caucasus"


@pytest.mark.parametrize("place", ["smolensk", "vyazma"])
def test_smolensk_and_vyazma_are_rail_hubs(
    doc: dict[str, Any], start: dict[str, Any], place: str
) -> None:
    territory = _within(start, place)
    supply = _rows(doc)[territory]["supply"]
    names = {str(h).lower() for h in supply["hubs"]}
    assert place in names
    assert supply["amount"] >= 2


def test_kievs_prestige_is_above_poltavas(doc: dict[str, Any], start: dict[str, Any]) -> None:
    kiev, poltava = _within(start, "kiev"), _within(start, "poltava")
    assert kiev != poltava
    assert _amount(doc, kiev, "prestige") > _amount(doc, poltava, "prestige")


@pytest.mark.parametrize("nation", sorted(CAPITAL_PLACE))
def test_each_capital_has_the_highest_prestige_in_its_nation(
    doc: dict[str, Any], start: dict[str, Any], nation: str
) -> None:
    capital = _within(start, CAPITAL_PLACE[nation])
    held = [t for t, h in _holders(start).items() if h == nation]
    assert capital in held
    top = _amount(doc, capital, "prestige")
    assert all(_amount(doc, t, "prestige") < top for t in held if t != capital), nation


# ------------------------------------------------ rule 4: trade lines and fuel stocks


def _polities(start: dict[str, Any]) -> set[str]:
    return set(CAPITAL_PLACE) | {str(e["key"]) for e in start["entities"] if e["kind"] == "polity"}


def _decl(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in ("named_source", "basis")}


def test_the_trade_lines_are_declared_with_sources(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    resources = set(_resources(start))
    lines = [TradeLineDecl.model_validate(_decl(t)) for t in doc["trade_lines"]]
    assert lines
    assert len({line.key for line in lines}) == len(lines)
    for raw, line in zip(doc["trade_lines"], lines, strict=True):
        assert {line.exporter, line.importer} <= _polities(start), line.key
        assert line.exporter != line.importer
        assert line.resource in resources
        _check_cited(doc, raw, f"trade_lines.{line.key}")


def test_the_oil_line_from_the_united_states_to_japan_is_cut_since_the_freeze(
    doc: dict[str, Any],
) -> None:
    lines = [TradeLineDecl.model_validate(_decl(t)) for t in doc["trade_lines"]]
    oil = [ln for ln in lines if (ln.exporter, ln.importer, ln.resource) == ("usa", "japan", "oil")]
    assert len(oil) == 1
    assert oil[0].cut is True
    assert oil[0].amount > 0


def test_the_fuel_stocks_are_declared_with_sources(
    doc: dict[str, Any], start: dict[str, Any]
) -> None:
    stocks = [FuelStockDecl.model_validate(_decl(s)) for s in doc["fuel_stocks"]]
    assert stocks
    assert len({s.polity for s in stocks}) == len(stocks)
    for raw, stock in zip(doc["fuel_stocks"], stocks, strict=True):
        assert stock.polity in _polities(start)
        _check_cited(doc, raw, f"fuel_stocks.{stock.polity}")


def test_japan_starts_with_a_fuel_stock(doc: dict[str, Any]) -> None:
    stocks = {str(s["polity"]): float(s["amount"]) for s in doc["fuel_stocks"]}
    assert stocks.get("japan", 0) > 0
