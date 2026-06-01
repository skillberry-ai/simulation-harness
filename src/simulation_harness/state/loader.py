"""Loader for state store from skill directory."""

import json
import logging
from pathlib import Path

from .store import SimulationStore
from .errors import ValidationError

logger = logging.getLogger(__name__)


def load_store_from_skill(skill_dir: Path) -> SimulationStore:
    """Load a SimulationStore from a skill directory.
    
    Reads schema.json and db.json from the skill directory and creates
    a store with proper primary key inference.
    
    Args:
        skill_dir: Path to the skill directory containing schema.json and db.json
        
    Returns:
        Initialized SimulationStore with seed data loaded
        
    Raises:
        FileNotFoundError: If schema.json or db.json is missing
        json.JSONDecodeError: If files contain invalid JSON
        ValidationError: If seed data doesn't match schema
    """
    schema_path = skill_dir / "schema.json"
    db_path = skill_dir / "db.json"
    
    # Load files
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.json not found in {skill_dir}")
    
    if not db_path.exists():
        raise FileNotFoundError(f"db.json not found in {skill_dir}")
    
    schema = json.loads(schema_path.read_text())
    seed = json.loads(db_path.read_text())
    
    # Infer primary keys
    primary_keys = infer_primary_keys(schema, seed)
    
    # Validate that all stores in schema exist in seed
    schema_stores = set(schema.get("properties", {}).keys())
    seed_stores = set(seed.keys())
    
    missing_stores = schema_stores - seed_stores
    if missing_stores:
        raise ValidationError(
            store="<root>",
            message=f"Stores defined in schema but missing from db.json: {', '.join(missing_stores)}"
        )
    
    # Create and return the store
    return SimulationStore(schema=schema, seed=seed, primary_keys=primary_keys)


def infer_primary_keys(schema: dict, seed: dict) -> dict[str, str]:
    """Infer primary key field names for each store.
    
    Resolution order:
    1. If the entity $def has x-primary-key annotation, use it
    2. Else if the entity has a required field named "id", use "id" (with warning)
    3. Else fail with RuntimeError
    
    Args:
        schema: The complete schema.json document
        seed: The seed data from db.json (for store names)
        
    Returns:
        Dictionary mapping store_name -> primary_key_field_name
        
    Raises:
        RuntimeError: If a store has no x-primary-key and no required "id" field
    """
    primary_keys = {}
    defs = schema.get("$defs", {})
    properties = schema.get("properties", {})
    
    for store_name in seed.keys():
        # Get the entity type for this store
        store_schema = properties.get(store_name, {})
        items_ref = store_schema.get("items", {}).get("$ref", "")
        
        if not items_ref.startswith("#/$defs/"):
            # No $ref, can't infer - default to "id"
            logger.warning(
                f"Store '{store_name}' has no $ref to $defs; defaulting to pk='id'"
            )
            primary_keys[store_name] = "id"
            continue
        
        def_name = items_ref.split("/")[-1]
        entity_def = defs.get(def_name, {})
        
        # Check for x-primary-key annotation
        if "x-primary-key" in entity_def:
            pk_field = entity_def["x-primary-key"]
            primary_keys[store_name] = pk_field
            logger.debug(f"Store '{store_name}': using x-primary-key='{pk_field}'")
            continue
        
        # Fall back to "id" if it's a required field
        required_fields = entity_def.get("required", [])
        entity_properties = entity_def.get("properties", {})
        
        if "id" in required_fields and "id" in entity_properties:
            primary_keys[store_name] = "id"
            logger.info(
                f"Store '{store_name}': inferred pk='id' from required fields. "
                f"Consider adding x-primary-key annotation to {def_name} for stability."
            )
            continue
        
        # No annotation and no "id" field - fail
        raise RuntimeError(
            f"Store '{store_name}' (entity type '{def_name}') has no x-primary-key "
            f"annotation and no required 'id' field. Add x-primary-key to "
            f"schema.json $defs/{def_name} to specify the primary key."
        )
    
    return primary_keys

# Made with Bob
