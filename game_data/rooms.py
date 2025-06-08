# game_data/rooms.py

from typing import Union, Dict # Required for type hints in Python < 3.10

class Room:
    def __init__(self, room_id: str, name: str, description: str, exits: dict, items: list = None, npcs: list = None):
        """
        Represents a single room in the MUD.

        Args:
            room_id (str): Unique identifier for the room (e.g., "start_room").
            name (str): Display name of the room (e.g., "Starting Chamber").
            description (str): Detailed description of the room.
            exits (dict): Dictionary mapping directions (e.g., "north") to target room_ids.
            items (list): List of Item objects currently in the room.
            npcs (list): List of NPC objects currently in the room.
        """
        self.room_id = room_id
        self.name = name
        self.description = description
        self.exits = exits
        self.items = items if items is not None else []
        self.npcs = npcs if npcs is not None else []

    def get_full_description(self) -> str:
        """Returns a comprehensive description of the room, including items and NPCs."""
        desc = f"**{self.name}**\n{self.description}"
        if self.items:
            item_names = [item.name for item in self.items]
            desc += f"\nItems here: {', '.join(item_names)}."
        if self.npcs:
            npc_names = [npc.name for npc in self.npcs]
            desc += f"\nNPCs here: {', '.join(npc_names)}."
        if self.exits:
            desc += f"\nExits: {', '.join(self.exits.keys())}."
        return desc

    def add_item(self, item):
        """Adds an item to the room."""
        self.items.append(item)

    def remove_item(self, item_id: str):
        """Removes an item from the room by its ID."""
        self.items = [item for item in self.items if item.item_id != item_id]

    def add_npc(self, npc):
        """Adds an NPC to the room."""
        self.npcs.append(npc)

    def remove_npc(self, npc_id: str):
        """Removes an NPC from the room by its ID."""
        self.npcs = [npc for npc in self.npcs if npc.npc_id != npc_id]

    def get_exit(self, direction: str) -> Union[str, None]:
        """Returns the room_id for a given exit direction, or None if no exit."""
        return self.exits.get(direction)

# --- World Data Definitions ---
# THIS IS THE PART THAT WAS LIKELY MISSING OR MISPLACED
RAW_WORLD_DATA = {
    "start_room": {
        "name": "Starting Chamber",
        "description": "You are in a dimly lit starting chamber. A dusty old map lies on the ground.",
        "exits": {"north": "forest_path"},
        "items": ["dusty map"], # Just IDs for now, we'll map to Item objects later
        "npcs": []
    },
    "forest_path": {
        "name": "Forest Path",
        "description": "A winding path through a dense forest. You hear birds chirping.",
        "exits": {"south": "start_room", "east": "clearing"},
        "items": [],
        "npcs": ["goblin"]
    },
    "clearing": {
        "name": "Sunny Clearing",
        "description": "A small, sunny clearing. A sparkling gem catches your eye.",
        "exits": {"west": "forest_path"},
        "items": ["sparkling gem"],
        "npcs": []
    }
}

# --- World Data Loading Function ---
def load_world_data(item_definitions: Dict = None, npc_definitions: Dict = None) -> Dict[str, Room]:
    """
    Loads raw world data and converts it into Room objects.
    Optionally maps item/NPC IDs to their respective objects.
    """
    world_objects = {}
    item_definitions = item_definitions if item_definitions is not None else {}
    npc_definitions = npc_definitions if npc_definitions is not None else {}

    for room_id, data in RAW_WORLD_DATA.items(): # This line caused the error if RAW_WORLD_DATA wasn't defined
        # Ensure items and npcs are lists, even if empty in RAW_WORLD_DATA
        room_items = [item_definitions[item_id] for item_id in data.get('items', []) if item_id in item_definitions]
        room_npcs = [npc_definitions[npc_id] for npc_id in data.get('npcs', []) if npc_id in npc_definitions]

        room = Room(
            room_id=room_id,
            name=data['name'],
            description=data['description'],
            exits=data['exits'],
            items=room_items,
            npcs=room_npcs
        )
        world_objects[room_id] = room
    return world_objects
