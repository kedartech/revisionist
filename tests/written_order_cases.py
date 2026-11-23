"""The table of written orders (WRT): one written sentence for every form in Autumn 1941
and in Salt Strait, and the reading it stands for.

A case names the form as a seat files it (its person, lever and parameters), the sentence
a player would write for the same order, and the reading the aide gives that sentence: its
asks, each a typed effect or an approach to a named person. Ids are written as world keys;
``test_written_order_parity`` turns them into the game's ids. Where an ask has no typed
effect, ``ruling`` is the estimator's reply for it, written by hand: no live model reads
any of this.

``fix`` names the item that owns a case's difference while it is open; the case is then a
strict expected failure, and the mark goes when that item merges.
"""

from dataclasses import dataclass, replace
from typing import Any

from revisionist.core.realism.resolvers.votes import HISTORICAL

Effect = dict[str, Any]

ENTITY_FIELDS = frozenset({"target", "recipient", "audience", "person", "to"})
"""Effect fields that hold an entity (a person, a nation or a place), as its world key."""
FEATURE_FIELDS = frozenset({"force", "flier"})
"""Effect fields that hold a piece, as its world key."""


@dataclass(frozen=True)
class Case:
    world: str
    """``1941`` (Autumn 1941) or ``salt`` (Salt Strait)."""
    person: str
    lever: str
    params: dict[str, str]
    sentence: str
    reading: tuple[Effect, ...]
    """Each ask's effect, or ``{"target": key}`` for an approach with no typed effect."""
    ruling: tuple[Effect, ...] = ()
    """The estimator's effects for an approach, as its reply carries them."""
    variant: str = ""
    """Tells two cases of one form apart (a naval order in each zone)."""
    fix: str | None = None

    @property
    def name(self) -> str:
        tail = f".{self.variant}" if self.variant else ""
        return f"{self.world}.{self.person}.{self.lever}{tail}"


# --- readings ----------------------------------------------------------------------------


def move(force: str, to: str) -> Effect:
    return {"kind": "move_force", "force": force, "to": to}


def patrol(force: str) -> Effect:
    return {"kind": "move_force", "force": force, "posture": "patrol"}


def recon(piece: str, area: str) -> Effect:
    return {
        "kind": "investigate",
        "target": area,
        "question": "recon",
        "intel": "recon",
        "flier": piece,
    }


def agent(area: str) -> Effect:
    return {"kind": "investigate", "target": area, "question": "agent", "intel": "agent"}


def codes(nation: str) -> Effect:
    return {
        "kind": "allocate",
        "recipient": nation,
        "what": "codebreaking",
        "amount": 0,
        "unit": "points",
        "intel": "codebreaking",
    }


def hide(piece: str) -> Effect:
    return {"kind": "engagement", "force": piece, "zone": "", "rule": "defend", "concealed": True}


def engage(zone: str, rule: str, force: str | None = None) -> Effect:
    out: Effect = {"kind": "engagement", "zone": zone, "rule": rule}
    return out | ({"force": force} if force is not None else {})


def say(theme: str, audience: str | None = None) -> Effect:
    out: Effect = {"kind": "statement", "theme": theme}
    return out | ({"audience": audience} if audience is not None else {})


def give(recipient: str, what: str, amount: int, unit: str) -> Effect:
    return {
        "kind": "allocate",
        "recipient": recipient,
        "what": what,
        "amount": amount,
        "unit": unit,
    }


def bill(key: str) -> Effect:
    return HISTORICAL[key].model_dump(mode="json")


def approach(target: str) -> Effect:
    return {"target": target}


# --- Autumn 1941 -------------------------------------------------------------------------

ORDER_RULE = {
    "escort_convoys": "escort",
    "shoot_on_sight": "shoot_on_sight",
    "hold_in_port": "hold_fire",
}
ORDER_WORDS = {
    "escort_convoys": "escort the convoys",
    "shoot_on_sight": "shoot on sight",
    "hold_in_port": "hold the ships in port",
}
ZONE_WORDS = {
    "western_atlantic": "the western Atlantic",
    "iceland_route": "the Iceland route",
    "war_zone": "the war zone",
    "pacific": "the Pacific",
}


def naval(person: str, lever: str, order: str, zone: str, force: str | None = None) -> "Case":
    return Case(
        "1941",
        person,
        lever,
        {"order": order, "zone": zone},
        f"The Atlantic Fleet is to {ORDER_WORDS[order]} in {ZONE_WORDS[zone]}.",
        (engage(zone, ORDER_RULE[order], force),),
        variant=zone if lever == "fleet_naval_order" else "",
    )


def f41(
    person: str, lever: str, params: dict[str, str], sentence: str, *reading: Effect, **kw: Any
) -> Case:
    return Case("1941", person, lever, params, sentence, tuple(reading), **kw)


NINETEEN_41: tuple[Case, ...] = (
    # The President
    f41(
        "roosevelt",
        "send_bill",
        {"bill": "neutrality_revision", "urgency": "ordinary"},
        "Send the revision of the Neutrality Act to Congress.",
        bill("neutrality_revision"),
    ),
    f41(
        "roosevelt",
        "lend_lease_finding",
        {"recipient": "uk", "share_pct": "50", "route": "hx_route"},
        "Britain is to have half of what Lend-Lease ships, by the HX convoys.",
        give("uk", "lend_lease", 50, "percent"),
    ),
    naval("roosevelt", "naval_order", "escort_convoys", "western_atlantic"),
    f41(
        "roosevelt",
        "move_fleet",
        {"force": "us_atlantic_fleet", "to": "argentia"},
        "Move the Atlantic Fleet to Argentia.",
        move("us_atlantic_fleet", "argentia"),
    ),
    f41(
        "roosevelt",
        "detach_fleet",
        {"force": "us_atlantic_fleet", "to": "reykjavik", "strength": "2"},
        "Detach two squadrons of the Atlantic Fleet to Reykjavik.",
        move("us_atlantic_fleet", "reykjavik"),
    ),
    f41(
        "roosevelt",
        "public_address",
        {"theme": "aid_to_allies"},
        "Speak to the nation on aid to our allies.",
        say("aid_to_allies"),
    ),
    f41(
        "roosevelt",
        "cable_to_churchill",
        {"message": "We stand with you."},
        "Cable the Prime Minister that we stand with him.",
        approach("churchill"),
    ),
    f41(
        "roosevelt",
        "fly_recon",
        {"intel": "recon", "piece": "hawaiian_air_force", "area": "central_pacific"},
        "Fly the Hawaiian air force over the central Pacific.",
        recon("hawaiian_air_force", "central_pacific"),
    ),
    f41(
        "roosevelt",
        "send_on_patrol",
        {"intel": "patrol", "piece": "us_pacific_fleet"},
        "Put the Pacific Fleet on patrol.",
        patrol("us_pacific_fleet"),
    ),
    f41(
        "roosevelt",
        "fund_the_codebreakers",
        {"intel": "codebreaking"},
        "Fund the codebreakers.",
        codes("usa"),
    ),
    # The Prime Minister
    f41(
        "churchill",
        "convoy_orders",
        {"priority": "atlantic", "route": "hx_route"},
        "The escorts are to see the HX convoys across the Atlantic first.",
        engage("hx_route", "escort"),
    ),
    f41(
        "churchill",
        "production_priority",
        {"sector": "escorts", "force": "home_fleet"},
        "Escorts first in production, for the Home Fleet.",
        give("uk", "escorts", 1, "priority"),
    ),
    f41(
        "churchill",
        "move_fleet",
        {"force": "home_fleet", "to": "reykjavik"},
        "Move the Home Fleet to Reykjavik.",
        move("home_fleet", "reykjavik"),
    ),
    f41(
        "churchill",
        "detach_fleet",
        {"force": "home_fleet", "to": "reykjavik", "strength": "2"},
        "Detach two squadrons of the Home Fleet to Reykjavik.",
        move("home_fleet", "reykjavik"),
    ),
    f41(
        "churchill",
        "move_army",
        {"force": "western_desert_force", "to": "tobruk"},
        "Send the Western Desert Force to Tobruk.",
        move("western_desert_force", "tobruk"),
    ),
    f41(
        "churchill",
        "broadcast",
        {"audience": "america"},
        "Broadcast to America.",
        say("broadcast", "usa"),
    ),
    f41(
        "churchill",
        "fly_recon",
        {"intel": "recon", "piece": "bomber_command", "area": "norway"},
        "Fly Bomber Command over Norway.",
        recon("bomber_command", "norway"),
    ),
    f41(
        "churchill",
        "send_on_patrol",
        {"intel": "patrol", "piece": "home_fleet"},
        "Put the Home Fleet on patrol.",
        patrol("home_fleet"),
    ),
    f41(
        "churchill",
        "send_an_agent",
        {"intel": "agent", "area": "occupied_france"},
        "Put an agent into occupied France.",
        agent("occupied_france"),
    ),
    f41(
        "churchill",
        "fund_the_codebreakers",
        {"intel": "codebreaking"},
        "Fund Bletchley Park.",
        codes("uk"),
    ),
    # Stalin
    f41(
        "stalin",
        "state_defence_order",
        {"sector": "tanks", "force": "soviet_western_front"},
        "Tanks first, for the Western Front.",
        give("ussr", "tanks", 1, "priority"),
    ),
    f41(
        "stalin",
        "aid_request",
        {"item": "tanks"},
        "Ask the Americans for tanks.",
        approach("roosevelt"),
    ),
    f41(
        "stalin",
        "move_army",
        {"force": "soviet_western_front", "to": "mozhaisk"},
        "Pull the Western Front back to Mozhaisk.",
        move("soviet_western_front", "mozhaisk"),
    ),
    f41(
        "stalin",
        "send_on_patrol",
        {"intel": "patrol", "piece": "baltic_fleet"},
        "Put the Baltic Fleet on patrol.",
        patrol("baltic_fleet"),
    ),
    f41(
        "stalin",
        "send_an_agent",
        {"intel": "agent", "area": "japan_east"},
        "Put an agent into Japan.",
        agent("japan_east"),
    ),
    # Hitler
    f41(
        "hitler",
        "uboat_directive",
        {"posture": "unrestricted_atlantic", "theatre": "north_atlantic"},
        "The U-boats are to wage unrestricted war in the North Atlantic.",
        engage("north_atlantic", "shoot_on_sight", "uboat_arm"),
    ),
    f41(
        "hitler",
        "production_priority",
        {"sector": "uboats", "force": "uboat_arm", "adds_to": "uboats_operational"},
        "U-boats first in production.",
        give("germany", "uboats", 1, "priority"),
    ),
    f41(
        "hitler",
        "move_army",
        {"force": "army_group_centre", "to": "vyazma"},
        "Army Group Centre is to take Vyazma.",
        move("army_group_centre", "vyazma"),
    ),
    f41(
        "hitler",
        "declare_war",
        {"target": "usa"},
        "Declare war on the United States.",
        approach("usa"),
    ),
    f41(
        "hitler",
        "fly_recon",
        {"intel": "recon", "piece": "luftwaffe_centre", "area": "leningrad_area"},
        "Fly the Luftwaffe over Leningrad.",
        recon("luftwaffe_centre", "leningrad_area"),
    ),
    f41(
        "hitler",
        "send_on_patrol",
        {"intel": "patrol", "piece": "uboat_arm"},
        "Send the U-boats out on patrol.",
        patrol("uboat_arm"),
    ),
    # Konoe
    f41(
        "konoe",
        "requisition_shipping",
        {"tonnage_class": "army"},
        "Requisition merchant shipping for the army.",
        give("japan", "shipping", 1, "requisition"),
    ),
    f41(
        "konoe",
        "mobilisation_plan",
        {"sector": "oil"},
        "Mobilise the economy for oil.",
        give("japan", "oil", 1, "priority"),
    ),
    f41(
        "konoe",
        "cabinet_statement",
        {"line": "conciliatory"},
        "The cabinet is to take a conciliatory line in public.",
        say("conciliatory"),
    ),
    f41(
        "konoe",
        "send_an_agent",
        {"intel": "agent", "area": "hawaii"},
        "Place an agent in Hawaii.",
        agent("hawaii"),
    ),
    # Tojo
    f41(
        "tojo",
        "requisition_shipping",
        {"tonnage_class": "army"},
        "Requisition merchant shipping for the army.",
        give("japan", "shipping", 1, "requisition"),
    ),
    f41(
        "tojo",
        "mobilisation_plan",
        {"sector": "steel"},
        "Mobilise the economy for steel.",
        give("japan", "steel", 1, "priority"),
    ),
    f41("tojo", "cabinet_statement", {"line": "firm"}, "Take a firm line in public.", say("firm")),
    f41(
        "tojo",
        "fly_recon",
        {"intel": "recon", "piece": "eleventh_air_fleet", "area": "philippines"},
        "Fly the Eleventh Air Fleet over the Philippines.",
        recon("eleventh_air_fleet", "philippines"),
    ),
    f41(
        "tojo",
        "send_on_patrol",
        {"intel": "patrol", "piece": "combined_fleet"},
        "Put the Combined Fleet on patrol.",
        patrol("combined_fleet"),
    ),
    f41(
        "tojo",
        "send_an_agent",
        {"intel": "agent", "area": "malaya"},
        "Place an agent in Malaya.",
        agent("malaya"),
    ),
    f41(
        "tojo",
        "hide_a_force",
        {"intel": "conceal", "piece": "combined_fleet", "concealed": "yes"},
        "Hide the Combined Fleet.",
        hide("combined_fleet"),
    ),
    # Mussolini
    f41(
        "mussolini",
        "libya_convoys",
        {"route": "tripoli_route"},
        "Run the Libya convoys to Tripoli.",
        engage("tripoli", "escort"),
    ),
    f41(
        "mussolini",
        "production_priority",
        {"sector": "tanks", "force": "italian_army_libya"},
        "Tanks first, for the army in Libya.",
        give("italy", "tanks", 1, "priority"),
    ),
    f41(
        "mussolini",
        "move_fleet",
        {"force": "italian_fleet", "to": "tripoli"},
        "Move the fleet to Tripoli.",
        move("italian_fleet", "tripoli"),
    ),
    f41(
        "mussolini",
        "move_army",
        {"force": "italian_army_libya", "to": "bardia"},
        "Send the army in Libya to Bardia.",
        move("italian_army_libya", "bardia"),
    ),
    f41(
        "mussolini",
        "send_on_patrol",
        {"intel": "patrol", "piece": "italian_fleet"},
        "Put the fleet on patrol.",
        patrol("italian_fleet"),
    ),
    # Chiang
    f41(
        "chiang",
        "arsenal_output",
        {"sector": "ammunition", "force": "ninth_war_area"},
        "The arsenals are to make ammunition for the Ninth War Area.",
        give("china", "ammunition", 1, "priority"),
    ),
    f41(
        "chiang",
        "appeal_abroad",
        {"audience": "america"},
        "Appeal to America for help.",
        say("appeal_abroad", "usa"),
    ),
    f41(
        "chiang",
        "move_army",
        {"force": "ninth_war_area", "to": "changsha"},
        "The Ninth War Area is to hold Changsha.",
        move("ninth_war_area", "changsha"),
    ),
    f41(
        "chiang",
        "send_an_agent",
        {"intel": "agent", "area": "wuhan_area"},
        "Place an agent in Wuhan.",
        agent("wuhan_area"),
    ),
    # Admiral King
    f41(
        "king",
        "move_fleet",
        {"force": "us_atlantic_fleet", "to": "argentia"},
        "Take the Atlantic Fleet to Argentia.",
        move("us_atlantic_fleet", "argentia"),
    ),
    f41(
        "king",
        "detach_fleet",
        {"force": "us_atlantic_fleet", "to": "reykjavik", "strength": "2"},
        "Detach two squadrons to Reykjavik.",
        move("us_atlantic_fleet", "reykjavik"),
    ),
    *(
        naval("king", "fleet_naval_order", "escort_convoys", zone, "us_atlantic_fleet")
        for zone in ("western_atlantic", "iceland_route", "war_zone")
    ),
    # Admiral Tovey: the moves no lock holds
    f41(
        "tovey",
        "home_fleet_move",
        {"force": "home_fleet", "to": "liverpool"},
        "Take the Home Fleet to Liverpool.",
        move("home_fleet", "liverpool"),
    ),
    f41(
        "tovey",
        "home_fleet_detach",
        {"force": "home_fleet", "to": "reykjavik", "strength": "2"},
        "Send two of the fleet's squadrons on to Reykjavik.",
        move("home_fleet", "reykjavik"),
    ),
)
"""Every form on every playable card of Autumn 1941; Admiral King's naval order once in
each zone it names, the war zone included; Admiral Tovey's two forms where no lock holds them."""


# --- Salt Strait -------------------------------------------------------------------------


def _salt(
    person: str, nation: str, enemy: str, area: str, spy: str, march: str
) -> tuple[Case, ...]:
    def fsalt(lever: str, params: dict[str, str], sentence: str, *reading: Effect) -> Case:
        return Case("salt", person, lever, params, sentence, tuple(reading))

    return (
        fsalt(
            "move_force",
            {"force": f"{nation}_levy", "to": march},
            "March the levy.",
            move(f"{nation}_levy", march),
        ),
        fsalt("declare_war", {"target": enemy}, "Declare war.", approach(enemy)),
        fsalt(
            "fly_balloon",
            {"intel": "recon", "piece": f"{nation}_balloons", "area": area},
            "Send the balloons up.",
            recon(f"{nation}_balloons", area),
        ),
        fsalt(
            "galley_patrol",
            {"intel": "patrol", "piece": f"{nation}_galleys"},
            "Put the galleys on patrol.",
            patrol(f"{nation}_galleys"),
        ),
        fsalt("place_a_spy", {"intel": "agent", "area": spy}, "Place a spy.", agent(spy)),
        fsalt(
            "pay_the_cipher_clerks",
            {"intel": "codebreaking"},
            "Pay the cipher clerks.",
            codes(nation),
        ),
        fsalt(
            "hide_a_force",
            {"intel": "conceal", "piece": f"{nation}_levy", "concealed": "yes"},
            "Hide the levy.",
            hide(f"{nation}_levy"),
        ),
    )


def fsalt(person: str, lever: str, params: dict[str, str], sentence: str, *reading: Effect) -> Case:
    return Case("salt", person, lever, params, sentence, tuple(reading))


SALT_WATCH = {"intel": "patrol", "piece": "varda_galleys", "order": "guard", "zone": "strait"}
SALT_CONVOY_ACT: Effect = {
    "kind": "measure",
    "title": "Salt Convoy Act",
    "clauses": [{"kind": "power", "subject": "arm the salt convoys", "amount": None}],
}
"""Varda's own law as a written bill: its title's words are the key the form's bill names."""

SALT_STRAIT: tuple[Case, ...] = (
    *_salt("oren_vale", "varda", "ostrel", "harrow_pass", "kesh_shore", "varda_saltworks"),
    *_salt("general_aske", "ostrel", "varda", "harrow_pass", "kesh_shore", "harrow_pass"),
    fsalt(
        "oren_vale",
        "set_watch",
        SALT_WATCH,
        "Put the galleys on watch on the strait.",
        patrol("varda_galleys"),
    ),
    fsalt(
        "oren_vale",
        "send_bill",
        {"bill": "salt_convoy_act", "urgency": "ordinary"},
        "Send the Salt Convoy Act to the Salt Assembly.",
        SALT_CONVOY_ACT,
    ),
    fsalt(
        "oren_vale",
        "move_galleys",
        {"force": "varda_galleys", "to": "saltworks"},
        "Send the galleys to the Saltworks.",
        move("varda_galleys", "saltworks"),
    ),
    fsalt(
        "brask",
        "galley_watch",
        SALT_WATCH,
        "Put the galleys on watch on the strait.",
        patrol("varda_galleys"),
    ),
    fsalt(
        "brask",
        "sail",
        {"force": "varda_galleys", "to": "free_port"},
        "Sail the galleys to the Free Port.",
        move("varda_galleys", "free_port"),
    ),
)
"""Every form on every playable card of Salt Strait."""

# --- the open differences ----------------------------------------------------------------

TIMING = "core lane fix item: a written order lands on the day its form would"
AUTHORITY = "data lane fix item: a card's authority covers every order its forms give"
WAR = "core lane fix item: a written declaration of war declares the war"
DETACH = "core lane fix item: a written detachment moves only the strength it names"
INERT = "core lane fix item for the forms that change nothing (EFD's list)"
AUDIENCE = (
    "core lane fix item: a written statement to another nation lands as its form does"
    " (the form is heard at home through its audience's theme)"
)
PRODUCTION = (
    "core lane fix item: a written production order lands as its form does"
    " (the form builds a step, mobilises, or brings the aid another nation let through)"
)
MESSAGE = (
    "core lane fix item: a written message lands as its form does"
    " (the form raises the regard of the person abroad who let it through)"
)
SHIPPING = (
    "core lane fix item: a written shipping order lands as its form does"
    " (the form acts through escort levels, losses and the lift pool)"
)

FIXES: dict[str, str] = {
    "1941.roosevelt.lend_lease_finding": TIMING,
    "1941.roosevelt.naval_order": SHIPPING,
    "1941.roosevelt.move_fleet": TIMING,
    "1941.roosevelt.detach_fleet": DETACH,
    "1941.roosevelt.cable_to_churchill": MESSAGE,
    "1941.roosevelt.fly_recon": AUTHORITY,
    "1941.roosevelt.send_on_patrol": TIMING,
    "1941.churchill.convoy_orders": SHIPPING,
    "1941.churchill.production_priority": AUTHORITY,
    "1941.churchill.move_fleet": TIMING,
    "1941.churchill.detach_fleet": DETACH,
    "1941.churchill.move_army": AUTHORITY,
    "1941.churchill.broadcast": AUDIENCE,
    "1941.churchill.fly_recon": AUTHORITY,
    "1941.churchill.send_on_patrol": TIMING,
    "1941.churchill.send_an_agent": AUTHORITY,
    "1941.churchill.fund_the_codebreakers": AUTHORITY,
    "1941.stalin.state_defence_order": PRODUCTION,
    "1941.stalin.aid_request": PRODUCTION,
    "1941.stalin.move_army": TIMING,
    "1941.stalin.send_on_patrol": AUTHORITY,
    "1941.stalin.send_an_agent": AUTHORITY,
    "1941.hitler.uboat_directive": SHIPPING,
    "1941.hitler.production_priority": AUTHORITY,
    "1941.hitler.move_army": TIMING,
    "1941.hitler.declare_war": WAR,
    "1941.hitler.fly_recon": AUTHORITY,
    "1941.hitler.send_on_patrol": TIMING,
    "1941.konoe.requisition_shipping": SHIPPING,
    "1941.konoe.mobilisation_plan": PRODUCTION,
    "1941.konoe.send_an_agent": AUTHORITY,
    "1941.tojo.requisition_shipping": SHIPPING,
    "1941.tojo.mobilisation_plan": PRODUCTION,
    "1941.tojo.fly_recon": AUTHORITY,
    "1941.tojo.send_on_patrol": AUTHORITY,
    "1941.tojo.send_an_agent": AUTHORITY,
    "1941.tojo.hide_a_force": AUTHORITY,
    "1941.mussolini.production_priority": PRODUCTION,
    "1941.mussolini.move_fleet": AUTHORITY,
    "1941.mussolini.move_army": AUTHORITY,
    "1941.mussolini.send_on_patrol": AUTHORITY,
    "1941.chiang.arsenal_output": PRODUCTION,
    "1941.chiang.appeal_abroad": AUDIENCE,
    "1941.chiang.move_army": AUTHORITY,
    "1941.chiang.send_an_agent": AUTHORITY,
    "1941.king.detach_fleet": DETACH,
    "1941.king.fleet_naval_order.western_atlantic": SHIPPING,
    "1941.king.fleet_naval_order.iceland_route": SHIPPING,
    "1941.king.fleet_naval_order.war_zone": SHIPPING,
    "1941.tovey.home_fleet_detach": DETACH,
    "salt.oren_vale.move_force": TIMING,
    "salt.oren_vale.declare_war": WAR,
    "salt.oren_vale.galley_patrol": TIMING,
    "salt.oren_vale.set_watch": TIMING,
    "salt.oren_vale.hide_a_force": TIMING,
    "salt.general_aske.move_force": TIMING,
    "salt.general_aske.declare_war": WAR,
    "salt.general_aske.galley_patrol": TIMING,
    "salt.general_aske.hide_a_force": TIMING,
    "salt.brask.galley_watch": TIMING,
}
"""Each case whose written order and form still differ, and the fix item that owns the
difference: the first one found, where a case has more than one."""

CASES: tuple[Case, ...] = tuple(
    replace(c, fix=FIXES.get(c.name)) for c in NINETEEN_41 + SALT_STRAIT
)
