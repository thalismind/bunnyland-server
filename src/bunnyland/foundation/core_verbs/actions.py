"""Action metadata owned by bunnyland.core_verbs."""

from ...core.actions import (
    FOCUS_COST,
    FREE_COST,
    MAJOR_ACTION_COST,
    SPEECH_COST,
    ActionDefinition,
    ActionPattern,
    define_action,
)
from ...core.commands import Lane

ACTION_DEFINITIONS: tuple[ActionDefinition, ...] = (
    define_action(
        "look",
        tool_name="look",
        description=(
            "Look around your current room and see who and what is here, "
            "along with the exits you can take. Start here when you are unsure what to do next."
        ),
        cost=FREE_COST,
        patterns=(ActionPattern("look", {}), ActionPattern("look around", {})),
        examples=("look",),
        chat_safe=True,
    ),
    define_action(
        "inspect",
        ("target_id",),
        tool_name="inspect",
        description=(
            "Examine one specific item, character, or feature up close for "
            "details you cannot see at a glance. Look around first to find valid targets."
        ),
        cost=FREE_COST,
        patterns=("inspect {target_id}", "look at {target_id}", "examine {target_id}"),
        examples=("inspect woven basket",),
        chat_safe=True,
    ),
    define_action(
        "move",
        ("direction", "exit_id"),
        tool_name="move",
        description=(
            "Move into another room or area. Check the current room for "
            "available exits, then move by direction (such as north) or by exit id."
        ),
        patterns=(
            "go {direction}",
            "move {direction}",
            "walk {direction}",
            "run {direction}",
            "go {exit_id}",
            "move {exit_id}",
            "walk {exit_id}",
            "run {exit_id}",
            ActionPattern("north", {"direction": "north"}),
            ActionPattern("south", {"direction": "south"}),
            ActionPattern("east", {"direction": "east"}),
            ActionPattern("west", {"direction": "west"}),
            ActionPattern("up", {"direction": "up"}),
            ActionPattern("down", {"direction": "down"}),
            ActionPattern("inside", {"direction": "inside"}),
            ActionPattern("outside", {"direction": "outside"}),
            ActionPattern("in", {"direction": "in"}),
            ActionPattern("out", {"direction": "out"}),
        ),
        examples=("go north",),
    ),
    define_action(
        "take",
        ("item_id",),
        tool_name="take",
        description=(
            "Pick up an item from the room or an open container and add it "
            "to your inventory. Look or inspect first to find items you can take."
        ),
        patterns=(
            "take {item_id}",
            "get {item_id}",
            "grab {item_id}",
            "pick up {item_id}",
            "pick {item_id}",
        ),
        examples=("take brass key",),
    ),
    define_action(
        "put",
        ("item_id", "target_container_id"),
        tool_name="put",
        description=(
            "Place an item you are carrying into or onto a container or "
            "surface. Make sure the item is in your inventory first."
        ),
        patterns=(
            "put {item_id} in {target_container_id}",
            "put {item_id} into {target_container_id}",
            "put {item_id} on {target_container_id}",
            "put {item_id} onto {target_container_id}",
        ),
    ),
    define_action(
        "drop",
        ("item_id",),
        tool_name="drop",
        description=(
            "Drop an item from your inventory onto the ground in your "
            "current room, leaving it behind for others to find."
        ),
        patterns=("drop {item_id}", "put {item_id}"),
        examples=("drop brass key",),
    ),
    define_action(
        "open",
        ("target_id",),
        tool_name="open",
        description=(
            "Open a door, container, or other closeable thing so you can "
            "pass through it or reach what is inside. Locked things must be unlocked first."
        ),
        patterns=("open {target_id}",),
        examples=("open woven basket",),
    ),
    define_action(
        "close",
        ("target_id",),
        tool_name="close",
        description=(
            "Close a door or container, for privacy, safety, or to keep "
            "its contents out of sight."
        ),
        patterns=("close {target_id}",),
    ),
    define_action(
        "lock",
        ("target_id", "tool_id"),
        tool_name="lock",
        description=(
            "Lock a door or container so others cannot open it. You "
            "usually need the matching key or tool in hand."
        ),
        patterns=("lock {target_id} with {tool_id}", "lock {target_id}"),
    ),
    define_action(
        "unlock",
        ("target_id", "tool_id"),
        tool_name="unlock",
        description=(
            "Unlock a locked door or container with the right key or tool. "
            "Inspect the lock to learn what it needs."
        ),
        patterns=("unlock {target_id} with {tool_id}", "unlock {target_id}"),
        examples=("unlock burrow door with brass key",),
    ),
    define_action(
        "hold",
        ("item_id",),
        tool_name="hold",
        description=(
            "Take an item into your hands so you can wield or use it. Some "
            "actions require the right item to be held first."
        ),
        patterns=("hold {item_id}", "equip {item_id}"),
    ),
    define_action(
        "unhold",
        ("item_id",),
        tool_name="unhold",
        description=(
            "Stop holding an item and return it to your inventory, freeing "
            "your hands for something else."
        ),
        patterns=("unhold {item_id}", "unequip {item_id}"),
    ),
    define_action(
        "wear",
        ("item_id",),
        tool_name="wear",
        description=(
            "Put on a wearable item such as clothing or armor, for warmth, "
            "protection, or appearance."
        ),
        patterns=("wear {item_id}",),
    ),
    define_action(
        "remove",
        ("item_id",),
        tool_name="remove",
        description="Take off something you are currently wearing.",
        patterns=("remove {item_id}",),
    ),
    define_action(
        "use",
        ("item_id", "target_id", "tool_id"),
        tool_name="use",
        description=(
            "Use an item on its own, on a target, or together with another "
            "tool. Inspect the item or target first if you are unsure what will happen."
        ),
        patterns=(
            "use {item_id}",
            "use {item_id} on {target_id}",
            "use {item_id} with {target_id}",
        ),
    ),
    define_action(
        "identify",
        ("target_id", "species_name"),
        tool_name="identify",
        description=(
            "Identify an unknown creature, plant, or object and learn what "
            "species or kind it is."
        ),
        patterns=("identify {target_id}",),
    ),
    define_action(
        "harvest",
        ("target_id", "product_type", "sample_type", "quantity"),
        tool_name="harvest",
        description=(
            "Gather a product or sample from a resource, creature, or "
            "plant in the room, such as harvesting crops or taking a specimen."
        ),
        patterns=("harvest {target_id}", "harvest sample {sample_type}"),
    ),
    define_action(
        "bribe",
        ("target_id",),
        tool_name="bribe",
        description=(
            "Offer a character something of value to win their cooperation. "
            "Whether it works depends on who you are dealing with."
        ),
        patterns=("bribe {target_id}",),
    ),
    define_action(
        "build",
        ("target_id", "name", "capacity", "feeding_pen", "quarantine"),
        tool_name="build",
        description=(
            "Construct a new structure or enclosure at a buildable "
            "location. This is a major effort that consumes most of your turn."
        ),
        cost=MAJOR_ACTION_COST,
        patterns=("build at {target_id}",),
    ),
    define_action(
        "claim",
        ("target_id",),
        tool_name="claim",
        description=(
            "Claim a territory, resource, or structure so it becomes yours "
            "to control and manage. This is a major, deliberate action."
        ),
        cost=MAJOR_ACTION_COST,
        patterns=("claim {target_id}",),
    ),
    define_action(
        "command",
        ("target_id", "instruction", "command_target_id"),
        tool_name="command",
        description=(
            "Give an order to a character or creature you control, telling "
            "them what to do. Name the target and give a clear instruction."
        ),
        required=("target_id", "instruction"),
        patterns=("command {target_id} to {instruction}",),
    ),
    define_action(
        "sneak",
        tool_name="sneak",
        description=(
            "Move and act quietly, trying to avoid being noticed by others "
            "nearby."
        ),
        patterns=(ActionPattern("sneak", {}),),
    ),
    define_action(
        "drink",
        ("source_id",),
        tool_name="drink",
        description=(
            "Drink from a water source or container to quench your thirst."
        ),
        patterns=("drink {source_id}",),
    ),
    define_action(
        "write",
        ("target_id", "text"),
        tool_name="write",
        description=(
            "Write a message or note onto a writable surface or object so "
            "others can read it later."
        ),
        cost=SPEECH_COST,
        patterns=("write {text} on {target_id}",),
    ),
    define_action(
        "rest",
        ("duration_seconds",),
        tool_name="rest",
        description=(
            "Rest in place to recover fatigue, stamina, and stress. An optional positive "
            "duration ends the rest automatically; danger or another successful action "
            "ends it early."
        ),
        cost=FREE_COST,
        patterns=(ActionPattern("rest", {}),),
    ),
    define_action(
        "sleep",
        ("duration_seconds",),
        tool_name="sleep",
        description=(
            "Sleep until explicitly woken or an optional positive duration expires. "
            "Sleeping recovers fatigue, stamina, and stress but leaves you vulnerable."
        ),
        cost=FREE_COST,
        patterns=(ActionPattern("sleep", {}),),
    ),
    define_action(
        "wake",
        tool_name="wake",
        description="Wake up from sleep and return to normal activity.",
        cost=FREE_COST,
        patterns=(ActionPattern("wake", {}),),
    ),
    define_action(
        "wait",
        tool_name="wait",
        description=(
            "Wait and pass the turn without taking another action, letting "
            "the world move around you."
        ),
        cost=FREE_COST,
        patterns=(ActionPattern("wait", {}), ActionPattern("yield", {})),
        examples=("wait",),
        chat_safe=True,
    ),
    define_action(
        "say",
        ("text", "intent", "approach"),
        tool_name="say",
        description=(
            "Speak aloud to everyone in your current room. Set what you "
            "say, and optionally your intent or approach to shape the delivery."
        ),
        cost=SPEECH_COST,
        required=("text",),
        patterns=("say {text}",),
        chat_safe=True,
    ),
    define_action(
        "tell",
        ("target_id", "text", "intent", "approach", "audible"),
        tool_name="tell",
        description=(
            "Speak directly to one specific character. Choose who to tell "
            "and what to say; set audible to let others in the room overhear."
        ),
        cost=SPEECH_COST,
        required=("target_id", "text"),
        patterns=("tell {target_id:word} {text}",),
        chat_safe=True,
    ),
    define_action(
        "start-conversation",
        ("target_ids", "topic", "timeout_seconds"),
        tool_name="start_conversation",
        description=(
            "Begin a focused conversation with one or more characters "
            "about a topic, opening a back-and-forth exchange."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
        patterns=("start conversation with {target_ids}",),
    ),
    define_action(
        "conversation-line",
        ("conversation_id", "text", "intent", "approach"),
        tool_name="conversation_line",
        description=(
            "Add your next line to a conversation you have already joined, "
            "continuing the exchange."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
    define_action(
        "end-conversation",
        ("conversation_id", "reason"),
        tool_name="end_conversation",
        description=(
            "End a conversation you are part of, closing the focused "
            "exchange when it is finished."
        ),
        lane=Lane.FOCUS,
        cost=FOCUS_COST,
    ),
)

__all__ = ["ACTION_DEFINITIONS"]
