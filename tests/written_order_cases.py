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
    """Each ask's effect, or ``{"target": key}`` for an approach with no typed effect, or
    ``{"war": key}`` for a declaration of war. An effect's ``detail`` names the values of
    its form's parameters the effect cannot hold."""
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


NATIONAL_SERVICE: Effect = {
    "kind": "measure",
    "title": "National Service",
    "clauses": [
        {"kind": "power", "subject": "call up unmarried women and men to fifty-one", "amount": None}
    ],
}
"""Britain's law as a written bill: the code table has no row for it, so the Commons' blocs count it
by the key its title's words make."""


def approach(target: str) -> Effect:
    return {"target": target}


def detail(effect: Effect, **params: str) -> Effect:
    """``effect`` with the values of the form's parameters it cannot hold (a strength, a
    route), as the reader names them beside it."""
    return effect | {"detail": params}


def war(target: str) -> Effect:
    """A written declaration of war on ``target``, as the reader gives it beside the asks."""
    return {"war": target}


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
        detail(give("uk", "lend_lease", 50, "percent"), route="hx_route"),
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
        detail(move("us_atlantic_fleet", "reykjavik"), strength="2"),
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
        {"detail": {"message": "We stand with you."}},
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
        detail(engage("hx_route", "escort"), priority="atlantic"),
    ),
    f41(
        "churchill",
        "production_priority",
        {"sector": "escorts", "force": "home_fleet"},
        "Escorts first in production, for the Home Fleet.",
        detail(give("uk", "escorts", 1, "priority"), force="home_fleet"),
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
        detail(move("home_fleet", "reykjavik"), strength="2"),
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
        detail(say("broadcast", "usa"), audience="america"),
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
    f41(
        "churchill",
        "send_bill",
        {"bill": "national_service", "urgency": "ordinary"},
        "Put the National Service bill to the Commons.",
        NATIONAL_SERVICE,
    ),
    # Stalin
    f41(
        "stalin",
        "state_defence_order",
        {"sector": "tanks", "force": "soviet_western_front"},
        "Tanks first, for the Western Front.",
        detail(give("ussr", "tanks", 1, "priority"), force="soviet_western_front"),
    ),
    f41(
        "stalin",
        "aid_request",
        {"item": "tanks"},
        "Ask the Americans for tanks.",
        {"detail": {"item": "tanks"}},
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
        detail(engage("north_atlantic", "shoot_on_sight"), posture="unrestricted_atlantic"),
    ),
    f41(
        "hitler",
        "production_priority",
        {"sector": "uboats", "force": "uboat_arm", "adds_to": "uboats_operational"},
        "U-boats first in production.",
        detail(
            give("germany", "uboats", 1, "priority"),
            force="uboat_arm",
            adds_to="uboats_operational",
        ),
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
        war("usa"),
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
        detail(give("japan", "shipping", 1, "requisition"), tonnage_class="army"),
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
        detail(give("japan", "shipping", 1, "requisition"), tonnage_class="army"),
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
        engage("tripoli_route", "escort"),
    ),
    f41(
        "mussolini",
        "production_priority",
        {"sector": "tanks", "force": "italian_army_libya"},
        "Tanks first, for the army in Libya.",
        detail(give("italy", "tanks", 1, "priority"), force="italian_army_libya"),
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
        detail(give("china", "ammunition", 1, "priority"), force="ninth_war_area"),
    ),
    f41(
        "chiang",
        "appeal_abroad",
        {"audience": "america"},
        "Appeal to America for help.",
        detail(say("appeal_abroad", "usa"), audience="america"),
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
        detail(move("us_atlantic_fleet", "reykjavik"), strength="2"),
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
        detail(move("home_fleet", "reykjavik"), strength="2"),
    ),
    # Admiral Dönitz: the moves no lock holds
    f41(
        "doenitz",
        "uboat_move",
        {"force": "uboat_arm", "to": "lorient"},
        "Bring the U-boats in to Lorient.",
        move("uboat_arm", "lorient"),
    ),
    f41(
        "doenitz",
        "uboat_detach",
        {"force": "uboat_arm", "to": "lorient", "strength": "2"},
        "Send two of the U-boat flotillas in to Lorient.",
        detail(move("uboat_arm", "lorient"), strength="2"),
    ),
    # Admiral Yamamoto: the moves no lock holds
    f41(
        "yamamoto",
        "combined_fleet_move",
        {"force": "combined_fleet", "to": "kure"},
        "Bring the Combined Fleet in to Kure.",
        move("combined_fleet", "kure"),
    ),
    f41(
        "yamamoto",
        "combined_fleet_detach",
        {"force": "combined_fleet", "to": "kure", "strength": "1"},
        "Send one of the fleet's divisions in to Kure.",
        detail(move("combined_fleet", "kure"), strength="1"),
    ),
    # Admiral Iachino: the moves no lock holds
    f41(
        "iachino",
        "battle_fleet_move",
        {"force": "italian_fleet", "to": "tripoli"},
        "Take the battle fleet to Tripoli.",
        move("italian_fleet", "tripoli"),
    ),
    f41(
        "iachino",
        "battle_fleet_detach",
        {"force": "italian_fleet", "to": "tripoli", "strength": "2"},
        "Send two of the fleet's divisions on to Tripoli.",
        detail(move("italian_fleet", "tripoli"), strength="2"),
    ),
    # Marshal Timoshenko: the move no lock holds, and the concealment
    f41(
        "timoshenko",
        "western_front_move",
        {"force": "soviet_western_front", "to": "vyazma"},
        "Move the Western Front up to Vyazma.",
        move("soviet_western_front", "vyazma"),
    ),
    f41(
        "timoshenko",
        "western_front_conceal",
        {"intel": "conceal", "piece": "soviet_western_front", "concealed": "yes"},
        "Hide the Western Front.",
        hide("soviet_western_front"),
    ),
    # General Xue: the move no lock holds, and the concealment
    f41(
        "xue_yue",
        "ninth_war_area_move",
        {"force": "ninth_war_area", "to": "wuhan"},
        "Move the Ninth War Area's armies up to Wuhan.",
        move("ninth_war_area", "wuhan"),
    ),
    f41(
        "xue_yue",
        "ninth_war_area_conceal",
        {"intel": "conceal", "piece": "ninth_war_area", "concealed": "yes"},
        "Hide the Ninth War Area's armies.",
        hide("ninth_war_area"),
    ),
    # President Ryti: the army order and the agent, both through the Commander-in-Chief
    f41(
        "ryti",
        "finnish_army_order",
        {"force": "finnish_army", "to": "helsinki"},
        "The Finnish Army is to stand at Helsinki.",
        move("finnish_army", "helsinki"),
    ),
    f41(
        "ryti",
        "finnish_agent",
        {"intel": "agent", "area": "leningrad_area"},
        "Put an agent behind the lines at Leningrad.",
        agent("leningrad_area"),
    ),
    # Marshal Mannerheim: the move no lock holds, and the concealment
    f41(
        "mannerheim",
        "finnish_army_move",
        {"force": "finnish_army", "to": "helsinki"},
        "Move the Finnish Army to Helsinki.",
        move("finnish_army", "helsinki"),
    ),
    f41(
        "mannerheim",
        "finnish_army_conceal",
        {"intel": "conceal", "piece": "finnish_army", "concealed": "yes"},
        "Hide the Finnish Army.",
        hide("finnish_army"),
    ),
    # The raising forms (KDA): read as the Salt Strait one is, an ask with no effect whose
    # detail names each of its parameters.
    f41(
        "churchill",
        "raise_piece",
        {"kind": "infantry", "place": "london"},
        "Raise new infantry in London.",
        {"detail": {"kind": "infantry", "place": "london"}},
    ),
    f41(
        "stalin",
        "raise_piece",
        {"kind": "infantry", "place": "moscow"},
        "Raise new infantry in Moscow.",
        {"detail": {"kind": "infantry", "place": "moscow"}},
    ),
    f41(
        "hitler",
        "raise_piece",
        {"kind": "armour", "place": "berlin"},
        "Raise new armour in Berlin.",
        {"detail": {"kind": "armour", "place": "berlin"}},
    ),
    f41(
        "konoe",
        "raise_piece",
        {"kind": "infantry", "place": "tokyo"},
        "Raise new infantry in Tokyo.",
        {"detail": {"kind": "infantry", "place": "tokyo"}},
    ),
    f41(
        "tojo",
        "raise_piece",
        {"kind": "garrison", "place": "kure"},
        "Raise a new garrison at Kure.",
        {"detail": {"kind": "garrison", "place": "kure"}},
    ),
    f41(
        "mussolini",
        "raise_piece",
        {"kind": "infantry", "place": "rome"},
        "Raise new infantry in Rome.",
        {"detail": {"kind": "infantry", "place": "rome"}},
    ),
    f41(
        "chiang",
        "raise_piece",
        {"kind": "infantry", "place": "chungking"},
        "Raise new infantry at Chungking.",
        {"detail": {"kind": "infantry", "place": "chungking"}},
    ),
)
"""Every form on every playable card of Autumn 1941; Admiral King's naval order once in
each zone it names, the war zone included; Admiral Tovey's, Admiral Dönitz's, Admiral
Yamamoto's, Admiral Iachino's two forms, Marshal Timoshenko's two, General Xue's two and
Marshal Mannerheim's two where no lock holds them, and President Ryti's two."""


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
        fsalt("declare_war", {"target": enemy}, "Declare war.", war(enemy)),
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
        detail(patrol("varda_galleys"), order="guard", zone="strait"),
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
        detail(patrol("varda_galleys"), order="guard", zone="strait"),
    ),
    fsalt(
        "brask",
        "sail",
        {"force": "varda_galleys", "to": "free_port"},
        "Sail the galleys to the Free Port.",
        move("varda_galleys", "free_port"),
    ),
    fsalt(
        "oren_vale",
        "raise_piece",
        {"kind": "levy", "place": "esk_harbour"},
        "Raise a new levy at Esk Harbour.",
        {"detail": {"kind": "levy", "place": "esk_harbour"}},
    ),
)
"""Every form on every playable card of Salt Strait. A form no effect kind holds (raising a
piece) is read as an ask with no effect whose detail names each of its parameters."""

# --- the open differences ----------------------------------------------------------------

FIXES: dict[str, str] = {}
"""Each case whose written order and form still differ, and the fix item that owns the
difference: the first one found, where a case has more than one."""

CASES: tuple[Case, ...] = tuple(
    replace(c, fix=FIXES.get(c.name)) for c in NINETEEN_41 + SALT_STRAIT
)


# --- canned rulings: written orders no form covers ---------------------------------------

RULED_BY = "cable_to_churchill"
RULED_READING: tuple[Effect, ...] = (approach("churchill"),)
"""The case whose sentence, read as a plain approach to the Prime Minister that names no
message, the estimator rules on: an approach no form of the President's gives. Read with
its message, the same sentence is the cable form."""

PLANTED_FACT = "planted_fact"
PLANTED_FIGURE = "planted_figure"
"""A fact and a figure no resolver computes, planted by the test: neither shipped world has
one at its open, and a disclosure and a figure's move need one to name."""

RULINGS: dict[str, Effect] = {
    "move_force": patrol("us_pacific_fleet"),
    "engagement": engage("atlantic", "escort", "us_atlantic_fleet"),
    "allocate": give("uk", "lend_lease", 10, "percent"),
    "appointment": {"kind": "appointment", "person": "hopkins", "office": "envoy"},
    "measure": {
        "kind": "measure",
        "title": "Aid to Britain",
        "clauses": [{"kind": "power", "subject": "aid to britain"}],
    },
    "statement": say("aid_to_allies"),
    "investigate": {"kind": "investigate", "target": "germany", "question": "intent"},
    "deal": {"kind": "deal", "counterparty": "uk", "offer": ["destroyers"], "ask": ["bases"]},
    "disposition": {"kind": "disposition", "of": "uk", "toward": "usa", "change": 2},
    "disclosure": {"kind": "disclosure", "fact": PLANTED_FACT},
    "figure": {"kind": "figure", "quantity": PLANTED_FIGURE, "percent": 5},
}
"""One canned ruling per effect kind the estimator may return, each the estimator's whole
reply on the approach ``RULED_BY`` stands for, as world keys. Each lands as ruled."""

PAST_THE_CAP: dict[str, tuple[tuple[Effect, ...], tuple[Effect, ...]]] = {
    "disposition": (
        (RULINGS["disposition"], RULINGS["disposition"]),
        (RULINGS["disposition"],),
    ),
    "figure": (
        ({"kind": "figure", "quantity": PLANTED_FIGURE, "percent": 25},),
        ({"kind": "figure", "quantity": PLANTED_FIGURE, "percent": 10},),
    ),
    "effects": ((RULINGS["statement"],) * 9, (RULINGS["statement"],) * 8),
}
"""Rulings past a cap, and what lands: a disposition moves at most 2 in one order, a figure
at most 10 percent in one order, and a ruling holds at most 8 effects."""
