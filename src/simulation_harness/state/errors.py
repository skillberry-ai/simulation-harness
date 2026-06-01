"""Custom exception classes for state store operations."""


class StoreError(Exception):
    """Base exception for all state store errors."""
    
    pass


class NotFoundError(StoreError):
    """Raised when an entity is not found by its primary key."""
    
    def __init__(self, store: str, id: str):
        """Initialize NotFoundError.
        
        Args:
            store: The store name where the entity was not found
            id: The primary key value that was not found
        """
        self.store = store
        self.id = id
        super().__init__(f"Entity not found in store '{store}' with id '{id}'")


class DuplicateKeyError(StoreError):
    """Raised when attempting to insert an entity with a duplicate primary key."""
    
    def __init__(self, store: str, id: str):
        """Initialize DuplicateKeyError.
        
        Args:
            store: The store name where the duplicate was detected
            id: The duplicate primary key value
        """
        self.store = store
        self.id = id
        super().__init__(f"Duplicate key in store '{store}': id '{id}' already exists")


class ValidationError(StoreError):
    """Raised when an entity fails schema validation."""
    
    def __init__(self, store: str, message: str, field_path: str | None = None):
        """Initialize ValidationError.
        
        Args:
            store: The store name where validation failed
            message: Human-readable validation error message
            field_path: Optional dotted path to the field that failed validation
        """
        self.store = store
        self.message = message
        self.field_path = field_path
        
        full_message = f"Validation error in store '{store}': {message}"
        if field_path:
            full_message = f"Validation error in store '{store}' at field '{field_path}': {message}"
        
        super().__init__(full_message)


class UnknownStoreError(StoreError):
    """Raised when attempting to access a store that doesn't exist."""
    
    def __init__(self, store: str, available_stores: list[str]):
        """Initialize UnknownStoreError.
        
        Args:
            store: The requested store name that doesn't exist
            available_stores: List of available store names
        """
        self.store = store
        self.available_stores = available_stores
        super().__init__(
            f"Unknown store '{store}'. Available stores: {', '.join(available_stores)}"
        )


class BadQueryError(StoreError):
    """Raised when a query (where clause, sort, etc.) is malformed."""
    
    def __init__(self, message: str):
        """Initialize BadQueryError.
        
        Args:
            message: Description of what's wrong with the query
        """
        self.message = message
        super().__init__(f"Bad query: {message}")

# Made with Bob
