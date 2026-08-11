"""Private, non-world-mutating media context for character chat."""

from __future__ import annotations

from collections.abc import Sequence

from relics import EntityId

from ..core import CharacterComponent, RoomComponent, parse_entity_id
from ..core.ecs import container_of, entity_name
from ..core.world_actor import WorldActor
from ..imagegen import ImageGenService, MediaSceneSnapshot, VideoGenService
from .character_chat import MEDIA_ACTION_WARNING, ChatOnlyTool, ChatOnlyToolHandler
from .models import (
    CharacterChatHistoryMessage,
    ChatMediaCreativeDirection,
)

CHAT_MEDIA_CONTEXT_CHARS = 12_000
CHAT_MEDIA_FIELD_CHARS = 500


async def capture_chat_media_scene(
    actor: WorldActor,
    service: ImageGenService | VideoGenService,
    character_id: str | EntityId,
) -> tuple[str, MediaSceneSnapshot]:
    """Capture a read-only scene without recording a world-history occurrence."""

    parsed = (
        character_id if isinstance(character_id, EntityId) else parse_entity_id(character_id)
    )
    async with actor._lock:
        if parsed is None or not actor.world.has_entity(parsed):
            raise ValueError("character does not exist")
        character = actor.world.get_entity(parsed)
        if not character.has_component(CharacterComponent):
            raise TypeError("entity is not a character")
        room_id = container_of(character)
        if room_id is None or not actor.world.has_entity(room_id):
            raise ValueError("character has no room to illustrate")
        room = actor.world.get_entity(room_id)
        if not room.has_component(RoomComponent):
            raise ValueError("character has no room to illustrate")
        snapshot = service.scene_projection.capture(
            viewer=character,
            room=room,
            primary=None,
        )
        subject = f"A private conversation with {entity_name(character)}"
    return subject, snapshot


def chat_media_prompt_context(
    *,
    history_summary: str,
    history: Sequence[CharacterChatHistoryMessage],
    direction: ChatMediaCreativeDirection,
    current_message: str = "",
) -> str:
    """Render bounded narrative direction; callers retain no transcript server-side."""

    lines = [
        "Illustrate the private conversation below while preserving the trusted world scene.",
    ]
    direction_fields = (
        ("Visual focus", direction.focus),
        ("Fictional scene action", direction.scene_action),
        ("Mood", direction.mood),
        ("Composition", direction.composition),
        ("Style notes", direction.style_notes),
    )
    for label, value in direction_fields:
        if value.strip():
            lines.append(f"{label}: {value.strip()}")
    if history_summary.strip():
        lines.extend(("Conversation summary:", history_summary.strip()[:4_000]))
    transcript = [
        f"{'Human' if message.role == 'user' else 'Character'}: {message.text.strip()}"
        for message in history
        if message.text.strip()
    ]
    if current_message.strip():
        transcript.append(f"Human now: {current_message.strip()}")
    prefix = "\n".join(lines)
    if not transcript:
        return prefix[:CHAT_MEDIA_CONTEXT_CHARS]
    available = CHAT_MEDIA_CONTEXT_CHARS - len(prefix) - len("\nRecent conversation:\n")
    recent = "\n".join(transcript)
    if len(recent) > available:
        recent = recent[-max(available, 0) :]
    return f"{prefix}\nRecent conversation:\n{recent}"


def chat_media_tool(
    kind: str,
    handler: ChatOnlyToolHandler,
) -> ChatOnlyTool:
    """Build one expressive chat-only image or video request tool."""

    if kind not in {"chat_image", "chat_video"}:
        raise ValueError("chat media kind must be chat_image or chat_video")
    medium = "image" if kind == "chat_image" else "video"
    return ChatOnlyTool(
        name=f"request_chat_{medium}",
        description=(
            f"Request a private {medium} illustrating this conversation. Set the visual "
            "focus and optionally describe fictional action, mood, composition, and style "
            f"to express yourself. {MEDIA_ACTION_WARNING}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "maxLength": CHAT_MEDIA_FIELD_CHARS,
                    "description": "The character, subject, or detail viewers should notice.",
                },
                "scene_action": {
                    "type": "string",
                    "maxLength": CHAT_MEDIA_FIELD_CHARS,
                    "description": (
                        "Fictional visual action to portray. This does not happen in "
                        "Bunnyland and cannot change world state."
                    ),
                },
                "mood": {
                    "type": "string",
                    "maxLength": CHAT_MEDIA_FIELD_CHARS,
                    "description": "Emotional tone, atmosphere, lighting, or energy.",
                },
                "composition": {
                    "type": "string",
                    "maxLength": CHAT_MEDIA_FIELD_CHARS,
                    "description": "Framing, camera position, movement, or visual emphasis.",
                },
                "style_notes": {
                    "type": "string",
                    "maxLength": CHAT_MEDIA_FIELD_CHARS,
                    "description": "Optional rendering or cinematic style preferences.",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


__all__ = [
    "CHAT_MEDIA_CONTEXT_CHARS",
    "capture_chat_media_scene",
    "chat_media_prompt_context",
    "chat_media_tool",
]
