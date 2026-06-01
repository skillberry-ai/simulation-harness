"""Schema validation for state store entities."""

import jsonschema
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import ValidationError


def validate_entity(store: str, entity: dict, schema: dict, full_schema: dict) -> None:
    """Validate an entity against its schema definition.

    Args:
        store: The store name (for error messages)
        entity: The entity to validate
        schema: The resolved schema for this entity type (from $defs)
        full_schema: The complete schema document (for $ref resolution)

    Raises:
        ValidationError: If the entity fails validation
    """
    try:
        # Create a temporary schema that includes $defs from full_schema
        # This allows $ref resolution within the entity schema
        schema_with_defs = {**schema, "$defs": full_schema.get("$defs", {})}

        # Create a registry with this schema
        resource = Resource.from_contents(
            schema_with_defs, default_specification=DRAFT202012
        )
        registry = Registry().with_resource(uri="", resource=resource)

        # Create validator with the registry for $ref resolution
        validator = Draft202012Validator(schema_with_defs, registry=registry)

        # Validate the entity
        validator.validate(entity)

    except jsonschema.ValidationError as e:
        # Extract field path from the validation error
        field_path = (
            ".".join(str(p) for p in e.absolute_path) if e.absolute_path else None
        )

        # Create a more readable error message
        message = e.message
        if e.validator == "required":
            missing_field = e.message.split("'")[1] if "'" in e.message else "unknown"
            message = f"Missing required field: {missing_field}"
        elif e.validator == "type":
            message = f"Invalid type: {e.message}"
        elif e.validator == "enum":
            message = f"Invalid value: {e.message}"
        elif e.validator in ("minimum", "maximum", "minLength", "maxLength"):
            message = f"Constraint violation: {e.message}"

        raise ValidationError(store=store, message=message, field_path=field_path)

    except jsonschema.SchemaError as e:
        # Schema itself is invalid - this is a programming error
        raise ValidationError(
            store=store, message=f"Invalid schema definition: {e.message}"
        )


def validate_primary_key_present(store: str, entity: dict, pk_field: str) -> None:
    """Validate that the primary key field is present in the entity.

    Args:
        store: The store name (for error messages)
        entity: The entity to check
        pk_field: The primary key field name

    Raises:
        ValidationError: If the primary key is missing
    """
    if pk_field not in entity:
        raise ValidationError(
            store=store,
            message=f"Primary key field '{pk_field}' is required",
            field_path=pk_field,
        )

    # Also check that the value is not None or empty string
    pk_value = entity[pk_field]
    if pk_value is None or (isinstance(pk_value, str) and not pk_value.strip()):
        raise ValidationError(
            store=store,
            message=f"Primary key field '{pk_field}' cannot be empty",
            field_path=pk_field,
        )


# Made with Bob
