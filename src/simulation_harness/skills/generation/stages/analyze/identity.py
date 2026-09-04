"""Deterministic derivation of entity identity from OpenAPI schemas.

Pure: no LLM, no I/O, no clock, no randomness. This module owns the *contract*
half of the analyze stage — the entity set, its collections, and its primary
keys — which ``state/loader.py`` reads back out of the generated
``schema.json`` at runtime. Because the contract is load-bearing at runtime, it
must not vary between two generations of the same spec; that is why it is code
and not a prompt.
"""

from __future__ import annotations

import re

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")

# Nouns ending in these are singular despite the trailing "s", so they still
# need pluralizing: address -> addresses, status -> statuses, axis -> axes.
_SINGULAR_S_ENDINGS = ("ss", "us", "is")


def snake(name: str) -> str:
    """``OrderItem`` -> ``order_item``. Already-snake names pass through."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def camel(noun: str) -> str:
    """``payment_method`` -> ``PaymentMethod``."""
    return "".join(part.capitalize() for part in noun.split("_") if part)


def pluralize(noun: str) -> str:
    """English-ish pluralizer for collection names.

    A noun already ending in ``s`` (other than the singular ``ss``/``us``/``is``
    endings) is treated as already plural and returned unchanged, so
    ``attachments`` does not become ``attachmentses``.
    """
    if noun.endswith("s") and not noun.endswith(_SINGULAR_S_ENDINGS):
        return noun
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    if noun.endswith("y") and noun[-2:-1] not in "aeiou":
        return noun[:-1] + "ies"
    return noun + "s"


def identity_key(name: str, schema: dict, *, synthetic: bool) -> str | None:
    """The property that identifies instances of ``schema``, or ``None``.

    ``None`` means **undecidable**: the caller must route the schema to the
    scoped LLM fallback rather than guess. Guessing is what the old free-form
    extract stage did, and it is the source of the run-to-run contract drift
    this work removes.

    ``synthetic`` marks a schema whose key is a generated operation id
    (``get_order_details__response``) rather than a spec-declared type name.
    Only those get rule 4 (sole ``<noun>_id``): a synthetic key can never
    name-match, so its single ``*_id`` is the only signal available, whereas a
    *named* schema carrying one foreign-looking id is genuinely ambiguous.
    """
    declared = schema.get("x-primary-key")
    if isinstance(declared, str) and declared:
        return declared
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None
    candidates = [p for p in props if isinstance(p, str) and p.endswith("_id")]
    own = snake(name)
    # Longest noun first so "order_item_id" beats "item_id" for OrderItem, and
    # so the outcome does not depend on property declaration order.
    for candidate in sorted(candidates, key=lambda c: (-len(c), c)):
        noun = candidate[:-3]
        if noun and (own == noun or own.endswith(noun)):
            return candidate
    if "id" in props:
        return "id"
    if synthetic and len(candidates) == 1:
        return candidates[0]
    return None


def noun_for(key: str, schema_name: str) -> str:
    """The entity noun implied by an identity key.

    The noun comes from the **key**, not the schema name — that is what makes
    ``get_order_details__response`` and ``get_order__response`` collapse into
    one ``orders`` collection. Only a bare ``id`` has to fall back to the schema
    name, which is exactly why a bare ``id`` never clusters across names.
    """
    if key.endswith("_id") and len(key) > 3:
        return snake(key[:-3])
    if key == "id":
        return snake(schema_name)
    return snake(key)
