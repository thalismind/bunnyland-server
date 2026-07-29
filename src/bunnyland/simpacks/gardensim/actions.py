"""Action metadata owned by bunnyland.gardensim."""

from ...core.actions import (
    EXTENDED_ACTION_COST,
    MAJOR_ACTION_COST,
    ActionDefinition,
    define_action,
)

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "till",
        ("soil_id",),
        tool_name="till",
        description=(
            "Break up a patch of soil so it is ready for planting. Till "
            "bare soil before you can sow any seeds in it."
        ),
        patterns=("till {soil_id}",),
    ),
    define_action(
        "plant",
        ("soil_id", "seed_id"),
        tool_name="plant",
        description=(
            "Sow a seed from your inventory into tilled soil to start a new crop growing. "
            "The seed must suit the current season unless the soil sits in a greenhouse."
        ),
        patterns=("plant {seed_id} in {soil_id}", "plant {seed_id} into {soil_id}"),
    ),
    define_action(
        "water-crop",
        ("soil_id",),
        tool_name="water_crop",
        description=(
            "Water a soil patch to keep its crop growing; a watering lasts "
            "about a day. Water daily so growth does not stall."
        ),
        patterns=("water {soil_id}",),
    ),
    define_action(
        "fertilize",
        ("soil_id", "fertilizer_id"),
        tool_name="fertilize",
        description=(
            "Apply fertilizer from your inventory to a soil patch to enrich "
            "it for the crop growing there. This consumes the fertilizer item."
        ),
        patterns=("fertilize {soil_id} with {fertilizer_id}",),
    ),
    define_action(
        "weed-crop",
        ("soil_id",),
        tool_name="weed_crop",
        description=(
            "Pull the weeds out of a soil patch, which also nudges its crop "
            "quality up a little. Inspect a crop to see whether weeds have taken hold."
        ),
    ),
    define_action(
        "treat-pests",
        ("soil_id",),
        tool_name="treat_pests",
        description=(
            "Clear the pests off a soil patch to protect its crop and raise "
            "its quality. Inspect a crop first to check for an infestation."
        ),
    ),
    define_action(
        "clear-dead-crop",
        ("soil_id",),
        tool_name="clear_dead_crop",
        description=(
            "Remove a withered, dead crop from a soil patch so you can "
            "replant it. This only works once the crop has actually died."
        ),
        patterns=("clear dead crop from {soil_id}",),
    ),
    define_action(
        "tap-tree",
        ("tree_id",),
        tool_name="tap_tree",
        description=(
            "Drive a tap into a mature tree so it begins producing sap you "
            "can harvest later. The tree must be grown, alive, and not already tapped."
        ),
        patterns=("tap {tree_id}", "tap tree {tree_id}"),
    ),
    define_action(
        "start-machine",
        ("machine_id", "recipe_id"),
        tool_name="start_machine",
        description=(
            "Load a processing machine with a recipe and start it running, spending the "
            "recipe's inputs from your inventory. The machine must be idle and unbroken."
        ),
    ),
    define_action(
        "collect-machine-output",
        ("machine_id",),
        tool_name="collect_machine_output",
        description=(
            "Take the finished goods out of a processing machine once its "
            "run is done, freeing the machine for its next task."
        ),
    ),
    define_action(
        "cancel-machine",
        ("machine_id",),
        tool_name="cancel_machine",
        description=(
            "Stop a machine's current processing task and free it up. Inputs "
            "already spent on the task are not refunded."
        ),
    ),
    define_action(
        "repair-machine",
        ("machine_id", "tool_id"),
        tool_name="repair_machine",
        description=(
            "Fix a broken-down machine and restore it to working quality. "
            "Some breakdowns require a matching repair tool held in your inventory."
        ),
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "feed-animal",
        ("animal_id", "feed_type"),
        tool_name="feed_animal",
        description=(
            "Feed a farm animal from your stores to keep it fed for the day "
            "and lift its mood. Carry the right feed in your inventory first."
        ),
    ),
    define_action(
        "pet-animal",
        ("animal_id",),
        tool_name="pet_animal",
        description=(
            "Pet a farm animal to raise its friendship and mood. Each animal "
            "can only be petted once per day."
        ),
    ),
    define_action(
        "breed-animal",
        ("animal_id", "mate_id", "gestation_seconds"),
        tool_name="breed_animal",
        description=(
            "Pair two farm animals of the same species to breed, starting a "
            "gestation timer for their offspring. Neither animal can already be expecting."
        ),
        cost=EXTENDED_ACTION_COST,
    ),
    define_action(
        "collect-animal-product",
        ("animal_id",),
        tool_name="collect_animal_product",
        description=(
            "Gather a ready product, such as milk, eggs, or wool, from a "
            "farm animal. This only works once the animal has produced something."
        ),
    ),
    define_action(
        "fish",
        ("spot_id",),
        tool_name="fish",
        description=(
            "Cast at a fishing spot to catch a fish and add it to your "
            "inventory. Some spots are seasonal or need the right bait on hand."
        ),
        patterns=("fish {spot_id}",),
    ),
    define_action(
        "mine",
        ("node_id",),
        tool_name="mine",
        description=(
            "Break open a mining node to extract its ore or stone, which "
            "depletes the node in the process."
        ),
        patterns=("mine {node_id}",),
    ),
    define_action(
        "discover-ladder",
        ("ladder_id",),
        tool_name="discover_ladder",
        description=(
            "Reveal a hidden ladder so it can be used to descend to the next "
            "area of the mine."
        ),
    ),
    define_action(
        "open-geode",
        ("geode_id",),
        tool_name="open_geode",
        description=(
            "Crack open a geode you are carrying to reveal the mineral "
            "inside. The geode must be in your inventory."
        ),
    ),
    define_action(
        "forage",
        ("forage_id",),
        tool_name="forage",
        description=(
            "Gather a wild forageable in the room and add it to your "
            "inventory. Some forageables only appear in certain seasons."
        ),
        patterns=("forage {forage_id}",),
    ),
    define_action(
        "give-gift",
        ("target_id", "item_id"),
        tool_name="give_gift",
        description=(
            "Hand an item from your inventory to another character as a gift, shifting how "
            "they feel about you. Gifts they love raise friendship most; disliked ones hurt it."
        ),
    ),
    define_action(
        "join-festival",
        ("festival_id",),
        tool_name="join_festival",
        description=(
            "Join a seasonal festival happening nearby to take part in it. "
            "The festival must be active in the current season."
        ),
        cost=MAJOR_ACTION_COST,
    ),
    define_action(
        "contribute-bundle",
        ("bundle_id", "resource_type", "quantity"),
        tool_name="contribute_bundle",
        description=(
            "Turn in resources from your inventory toward a community "
            "bundle's requirements. Filling every requirement completes the bundle."
        ),
    ),
    define_action(
        "claim-mail",
        ("mail_id",),
        tool_name="claim_mail",
        description=(
            "Open a piece of mail addressed to you and collect any reward it "
            "carries. Each letter can only be claimed once."
        ),
    ),
    define_action(
        "complete-farm-quest",
        ("quest_id",),
        tool_name="complete_farm_quest",
        description=(
            "Turn in the requested items to finish a farm quest and receive "
            "its reward. Make sure you are carrying everything it asks for."
        ),
    ),
    define_action(
        "ship-items",
        ("bin_id", "resource_type", "quantity", "unit_price"),
        tool_name="ship_items",
        description=(
            "Drop resources into a shipping bin to sell them and bank the "
            "earnings. Shipped goods are also recorded in your collection log."
        ),
    ),
    define_action(
        "donate-museum",
        ("museum_id", "resource_type"),
        tool_name="donate_museum",
        description=(
            "Donate a resource to a museum collection to add it to the "
            "exhibit. Each kind of item can only be donated once."
        ),
    ),
    define_action(
        "claim-reward",
        ("reward_id",),
        tool_name="claim_reward",
        description=(
            "Collect the payout from a reward you have earned, adding it to "
            "your inventory. Each reward can only be claimed once."
        ),
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
