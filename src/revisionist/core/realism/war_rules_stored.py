"""The Autumn 1941 names the war rules keep for a stored game (WRL).

A game without the territory rules, as every stored game is, takes its war checks by the
form's name: these names. A territory game reads which check a form takes from the world
(its rule, its parameters, a choice's ``needs_war``) and never this module.
"""

DECLARE = "declare_war"
"""The declaration of war's form."""
DETACH = "detach_fleet"
"""The fleet detachment's form."""
SHOOT_FORM, SHOOT_PARAM, SHOOT_CHOICE = "uboat_directive", "posture", "attack_us_shipping"
"""The U-boat directive, its parameter, and the choice that needs the war."""
SHOOT_NATION = "usa"
"""The nation that choice needs its issuer's nation at war with."""
SHOOT_REFUSAL = "so the U-boats cannot be ordered to attack American ships on sight."
"""The end of the words the seat is told when its nation is not."""
