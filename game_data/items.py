# game_data/items.py

from typing import Union # ADD THIS LINE

class Item:
    def __init__(self, item_id: str, name: str, description: str, can_take: bool = True):
        """
        Represents an item in the game world.
        # ... (rest of docstring)
        """
        self.item_id = item_id
        self.name = name
        self.description = description
        self.can_take = can_take

    def get_description(self) -> str:
        return f"{self.name}: {self.description}"

# --- Item Definitions ---
ITEM_DEFINITIONS = {
    "rusty sword": Item("rusty sword", "Rusty Sword", "A sword, covered in rust. It looks barely usable."),
    "sparkling gem": Item("sparkling gem", "Sparkling Gem", "A small gem that shimmers with an inner light. It might be valuable.", can_take=True),
    "dusty map": Item("dusty map", "Dusty Map", "An old, brittle map. The details are hard to make out.", can_take=True)
}

# CHANGE THIS LINE:
def get_item(item_id: str) -> Union[Item, None]: # Changed from Item | None
    """Retrieves an Item object by its ID."""
    return ITEM_DEFINITIONS.get(item_id)
