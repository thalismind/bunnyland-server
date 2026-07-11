"""Action metadata owned by bunnyland.gardensim."""

from ...core.actions import (
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action("till", ("soil_id",), tool_name="till", patterns=("till {soil_id}",)),
    define_action(
        "plant",
        ("soil_id", "seed_id"),
        tool_name="plant",
        patterns=("plant {seed_id} in {soil_id}", "plant {seed_id} into {soil_id}"),
    ),
    define_action(
        "water-crop",
        ("soil_id",),
        tool_name="water_crop",
        patterns=("water {soil_id}",),
    ),
    define_action(
        "fertilize",
        ("soil_id", "fertilizer_id"),
        tool_name="fertilize",
        patterns=("fertilize {soil_id} with {fertilizer_id}",),
    ),
    define_action("weed-crop", ("soil_id",), tool_name="weed_crop"),
    define_action("treat-pests", ("soil_id",), tool_name="treat_pests"),
    define_action(
        "clear-dead-crop",
        ("soil_id",),
        tool_name="clear_dead_crop",
        patterns=("clear dead crop from {soil_id}",),
    ),
    define_action(
        "tap-tree",
        ("tree_id",),
        tool_name="tap_tree",
        patterns=("tap {tree_id}", "tap tree {tree_id}"),
    ),
    define_action("start-machine", ("machine_id", "recipe_id"), tool_name="start_machine"),
    define_action(
        "collect-machine-output",
        ("machine_id",),
        tool_name="collect_machine_output",
    ),
    define_action("cancel-machine", ("machine_id",), tool_name="cancel_machine"),
    define_action("repair-machine", ("machine_id",), tool_name="repair_machine"),
    define_action("feed-animal", ("animal_id", "feed_type"), tool_name="feed_animal"),
    define_action("pet-animal", ("animal_id",), tool_name="pet_animal"),
    define_action(
        "breed-animal",
        ("animal_id", "mate_id", "gestation_seconds"),
        tool_name="breed_animal",
    ),
    define_action(
        "collect-animal-product",
        ("animal_id",),
        tool_name="collect_animal_product",
    ),
    define_action("fish", ("spot_id",), tool_name="fish", patterns=("fish {spot_id}",)),
    define_action("mine", ("node_id",), tool_name="mine", patterns=("mine {node_id}",)),
    define_action("discover-ladder", ("ladder_id",), tool_name="discover_ladder"),
    define_action("open-geode", ("geode_id",), tool_name="open_geode"),
    define_action("forage", ("forage_id",), tool_name="forage", patterns=("forage {forage_id}",)),
    define_action("give-gift", ("target_id", "item_id"), tool_name="give_gift"),
    define_action("join-festival", ("festival_id",), tool_name="join_festival"),
    define_action(
        "contribute-bundle",
        ("bundle_id", "resource_type", "quantity"),
        tool_name="contribute_bundle",
    ),
    define_action("claim-mail", ("mail_id",), tool_name="claim_mail"),
    define_action("complete-farm-quest", ("quest_id",), tool_name="complete_farm_quest"),
    define_action(
        "ship-items",
        ("bin_id", "resource_type", "quantity", "unit_price"),
        tool_name="ship_items",
    ),
    define_action("donate-museum", ("museum_id", "resource_type"), tool_name="donate_museum"),
    define_action("claim-reward", ("reward_id",), tool_name="claim_reward"),
)

__all__ = ["ACTION_DEFINITIONS"]
