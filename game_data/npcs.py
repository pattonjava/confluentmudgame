# game_data/npcs.py

from typing import Union # ADD THIS LINE

class NPC:
    def __init__(self, npc_id: str, name: str, description: str, dialogue: list = None):
        """
        Represents a Non-Player Character in the game world.
        # ... (rest of docstring)
        """
        self.npc_id = npc_id
        self.name = name
        self.description = description
        self.dialogue = dialogue if dialogue is not None else ["Hello traveler.", "Leave me alone.", "Grrr..."]

    def get_description(self) -> str:
        return f"{self.name}: {self.description}"

    def get_dialogue(self) -> str:
        """Returns a random dialogue line from the NPC."""
        import random
        return random.choice(self.dialogue)

# --- NPC Definitions ---
NPC_DEFINITIONS = {
    "goblin": NPC("goblin", "Goblin", "A small, green-skinned creature with beady eyes and a rusty dagger.", dialogue=["Grrr...", "You trespass!", "My preciousss..."])
}

# CHANGE THIS LINE:
def get_npc(npc_id: str) -> Union[NPC, None]: # Changed from NPC | None
    """Retrieves an NPC object by its ID."""
    return NPC_DEFINITIONS.get(npc_id)
