"""Chroma-backed action catalogue search helpers."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence

from ..core.actions import ActionDefinition

_ACTION_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EMBEDDING_DIMENSIONS = 64
_COLLECTION_PREFIX = "bunnyland-action-verbs"

_TOKEN_ALIASES = {
    "ask": "speak",
    "chat": "speak",
    "discard": "drop",
    "drink": "consume",
    "eat": "consume",
    "enter": "move",
    "examine": "look",
    "exit": "move",
    "get": "take",
    "go": "move",
    "grab": "take",
    "inspect": "look",
    "leave": "move",
    "look": "look",
    "move": "move",
    "north": "move",
    "pick": "take",
    "say": "speak",
    "sip": "consume",
    "south": "move",
    "speak": "speak",
    "talk": "speak",
    "tell": "speak",
    "travel": "move",
    "use": "use",
    "view": "look",
    "walk": "move",
}


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in _ACTION_TOKEN_RE.findall(text.lower()):
        tokens.append(token)
        alias = _TOKEN_ALIASES.get(token)
        if alias is not None and alias != token:
            tokens.append(alias)
    return tokens


class ActionSearchEmbedding:
    """Small deterministic embedding for offline Chroma action search."""

    def __call__(self, input):  # noqa: A002 - Chroma validates this parameter name.
        return [self._embed(text) for text in input]

    def embed_query(self, input):  # noqa: A002 - Chroma validates this parameter name.
        return self(input)

    @staticmethod
    def name() -> str:
        return "bunnyland-action-search"

    @staticmethod
    def build_from_config(config):
        del config
        return ActionSearchEmbedding()

    def get_config(self) -> dict:
        return {}

    def default_space(self) -> str:
        return "l2"

    def supported_spaces(self) -> list[str]:
        return ["l2"]

    def is_legacy(self) -> bool:
        return False

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * _EMBEDDING_DIMENSIONS
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=2).digest()
            index = int.from_bytes(digest, "big") % _EMBEDDING_DIMENSIONS
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 0.001
            return vector
        return [value / norm for value in vector]


def _action_document(definition: ActionDefinition) -> str:
    arguments = definition.arguments or {}
    examples = [example.text for example in definition.examples]
    patterns = [pattern.text for pattern in definition.natural_patterns]
    argument_text = [
        " ".join(
            part
            for part in (
                key,
                argument.title,
                argument.kind,
                argument.description,
            )
            if part
        )
        for key, argument in arguments.items()
    ]
    return "\n".join(
        part
        for part in (
            definition.command_type,
            definition.title,
            definition.name,
            definition.description,
            " ".join(patterns),
            " ".join(examples),
            " ".join(argument_text),
        )
        if part
    )


def _catalogue_key(definitions: Sequence[ActionDefinition]) -> str:
    digest = hashlib.blake2b(digest_size=8)
    for definition in definitions:
        digest.update(definition.command_type.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_action_document(definition).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class ChromaActionSearchIndex:
    """Action catalogue vector index built in a Chroma collection."""

    def __init__(self, client=None, embedding_function=None) -> None:
        if client is None:
            try:
                import chromadb
            except ImportError as exc:  # pragma: no cover - requires missing extra
                raise RuntimeError(
                    "smart action search requires the 'chroma' extra: "
                    "pip install bunnyland[chroma]"
                ) from exc
            client = chromadb.EphemeralClient()
        self._client = client
        self._embedding_function = embedding_function or ActionSearchEmbedding()
        self._loaded_keys: set[str] = set()

    def search(
        self, definitions: Sequence[ActionDefinition], *, query: str
    ) -> list[ActionDefinition]:
        if not definitions:
            return []
        collection = self._collection(definitions)
        result = collection.query(query_texts=[query], n_results=len(definitions))
        ids = (result.get("ids") or [[]])[0]
        by_id = {definition.command_type: definition for definition in definitions}
        return [by_id[id_] for id_ in ids if id_ in by_id]

    def _collection(self, definitions: Sequence[ActionDefinition]):
        key = _catalogue_key(definitions)
        collection = self._client.get_or_create_collection(
            name=f"{_COLLECTION_PREFIX}-{key}",
            embedding_function=self._embedding_function,
        )
        if key not in self._loaded_keys:
            collection.upsert(
                ids=[definition.command_type for definition in definitions],
                documents=[_action_document(definition) for definition in definitions],
                metadatas=[
                    {"command_type": definition.command_type} for definition in definitions
                ],
            )
            self._loaded_keys.add(key)
        return collection


_SMART_ACTION_INDEX: ChromaActionSearchIndex | None = None


def smart_action_search(
    definitions: Iterable[ActionDefinition], *, query: str
) -> list[ActionDefinition]:
    """Rank action definitions by vector relevance using a Chroma collection."""

    global _SMART_ACTION_INDEX
    definitions = tuple(definitions)
    if _SMART_ACTION_INDEX is None:
        _SMART_ACTION_INDEX = ChromaActionSearchIndex()
    return _SMART_ACTION_INDEX.search(definitions, query=query)


__all__ = [
    "ActionSearchEmbedding",
    "ChromaActionSearchIndex",
    "smart_action_search",
]
