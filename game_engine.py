# game_engine.py

from confluent_kafka import Consumer, Producer, KafkaException, KafkaError
import sys
import logging
import json
import time
from typing import Dict, List, Any # Added List, Any for better typing of inventory
import mysql.connector # Import the MySQL connector

# Import game data
from game_data.rooms import Room, load_world_data
from game_data.items import Item, ITEM_DEFINITIONS, get_item
from game_data.npcs import NPC, NPC_DEFINITIONS, get_npc
import config # Import your config file

# Kafka configuration from config.py
KAFKA_BOOTSTRAP_SERVERS = config.KAFKA_BOOTSTRAP_SERVERS
PLAYER_COMMANDS_TOPIC = config.PLAYER_COMMANDS_TOPIC
GAME_EVENTS_TOPIC = config.GAME_EVENTS_TOPIC
PLAYER_EVENTS_TOPIC = config.PLAYER_EVENTS_TOPIC # Ensure this is defined in config.py

# MySQL Configuration from config.py
MYSQL_HOST = config.MYSQL_HOST
MYSQL_USER = config.MYSQL_USER
MYSQL_PASSWORD = config.MYSQL_PASSWORD
MYSQL_DATABASE = config.MYSQL_DATABASE

# Load the game world using defined items and NPCs
WORLD_MAP: Dict[str, Room] = load_world_data(
    item_definitions=ITEM_DEFINITIONS,
    npc_definitions=NPC_DEFINITIONS
)

# In-memory cache for player states (for active players)
# Still use this for speed during active play, but synchronize with DB
player_states: Dict[str, dict] = {}

# --- Define Help Commands ---
HELP_COMMANDS = {
    "look": "Examine your current surroundings (room, items, NPCs).",
    "move <direction>": "Move in a specified direction (e.g., 'move north', 'move east').",
    "take <item_name>": "Pick up an item from the room (e.g., 'take dusty map').",
    "inventory": "Check the items you are currently carrying.",
    "say <message>": "Speak to other players in the same room (e.g., 'say Hello there!').",
    "help": "Display this list of available commands and their descriptions.",
    "quit": "Exit the game."
}

# --- Kafka Producer for Game Events ---
producer_conf = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'client.id': 'game-engine-producer'
}
producer = Producer(producer_conf)

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        return conn
    except mysql.connector.Error as err:
        sys.stderr.write(f"Error connecting to MySQL: {err}\n")
        return None

def load_player_state(player_name: str) -> dict:
    """Loads player state from MySQL or initializes a new one."""
    conn = get_db_connection()
    if not conn:
        return None # Indicate failure to load

    try:
        cursor = conn.cursor(dictionary=True) # Return results as dictionaries
        cursor.execute("SELECT player_name, current_room, inventory, health FROM players WHERE player_name = %s", (player_name,))
        result = cursor.fetchone()

        if result:
            # Player exists, load their data
            # Convert inventory (JSON string) back to list of Item objects
            inventory_ids = json.loads(result['inventory']) if result['inventory'] else []
            inventory_objects = [get_item(item_id) for item_id in inventory_ids if get_item(item_id)]

            player_data = {
                'current_room': result['current_room'],
                'inventory': inventory_objects,
                'health': result['health']
            }
            print(f"Loaded player {player_name} from DB: {player_data['current_room']}")
            return player_data
        else:
            # New player, initialize state and save to DB
            initial_state = {
                'current_room': 'start_room', # Default starting room
                'inventory': [],
                'health': 100
            }
            # Save the new player to the DB immediately
            save_player_state(player_name, initial_state)
            print(f"Initialized new player {player_name} and saved to DB.")
            return initial_state
    except mysql.connector.Error as err:
        sys.stderr.write(f"Error loading player {player_name}: {err}\n")
        return None
    finally:
        if conn:
            conn.close()

def save_player_state(player_name: str, state: dict):
    """Saves player state to MySQL."""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()
        # Convert inventory (list of Item objects) to a list of item IDs (JSON string)
        inventory_ids = [item.item_id for item in state['inventory']]
        inventory_json = json.dumps(inventory_ids)

        # UPSERT: INSERT if player_name doesn't exist, UPDATE if it does
        # This requires MySQL 8.0+ or equivalent. For older versions, use INSERT IGNORE and then UPDATE.
        # Simpler for now: just always UPDATE. If player_name doesn't exist, it won't update anything.
        # We ensure player exists with INSERT ON DUPLICATE KEY UPDATE in a single query.
        query = """
            INSERT INTO players (player_name, current_room, inventory, health)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                current_room = VALUES(current_room),
                inventory = VALUES(inventory),
                health = VALUES(health)
        """
        cursor.execute(query, (player_name, state['current_room'], inventory_json, state['health']))
        conn.commit()
        print(f"Saved player {player_name} to DB: {state['current_room']}")
    except mysql.connector.Error as err:
        sys.stderr.write(f"Error saving player {player_name}: {err}\n")
    finally:
        if conn:
            conn.close()

def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result. """
    if err is not None:
        sys.stderr.write(f'Message delivery failed: {err}\n')

def send_game_event(player_name, message, event_type="game_message", room_id=None):
    """Sends a game event to the specified player (or all in room_id)."""
    event_payload = {
        "player": player_name,
        "message": message,
        "type": event_type,
        "room_id": room_id
    }
    producer.produce(GAME_EVENTS_TOPIC, key=player_name.encode('utf-8'),
                     value=json.dumps(event_payload).encode('utf-8'),
                     callback=delivery_report)
    producer.flush() # Ensure message is sent promptly

# log significan player events to the player_events topic
def send_player_event(player_id, event_type, event_data):
    """
    Function to encapsulate sending player events to Kafka.
    Call this function whenever a significant player action occurs.
    """
    if producer is None:
        print("Kafka Producer not available. Skipping event.")
        return

    event = {
        "timestamp": int(time.time()), # Unix timestamp
        "player_id": player_id,
        "event_type": event_type,
        "data": event_data
    }
    event_json = json.dumps(event).encode('utf-8') # Serialize to JSON bytes

    try:
        # Asynchronously send the message
        producer.produce(
            topic=config.PLAYER_EVENTS_TOPIC,
            value=event_json,
            callback=delivery_report # Optional: for delivery acknowledgements
        )
        print(f"Player event sent: {event_json}");
        # You might want to flush periodically or on shutdown
        # producer.flush(timeout=1) # Flush every now and then, or on server shutdown
    except BufferError:
        print("Local producer queue is full. Try again later.")
    except Exception as e:
        print(f"Failed to send message: {e}")


def process_command(player_name: str, command: str):
    """Processes a command from a player."""
    player_state = player_states.get(player_name)
    if not player_state:
        # This case should now be handled by the initial loading in run_game_engine
        send_game_event(player_name, "Error: Player state not found. Please reconnect.")
        return

    current_room_id = player_state['current_room']
    current_room = WORLD_MAP[current_room_id]

    command_parts = command.lower().split(maxsplit=1)
    parsed_command = command_parts[0]
    arg = command_parts[1] if len(command_parts) > 1 else ""

    print(f"Processing command from {player_name}: {command}")

    if parsed_command == 'look':
        send_game_event(player_name, current_room.get_full_description())

    elif parsed_command == 'move':
        target_room_id = current_room.get_exit(arg)

        if target_room_id:
            # Announce departure to current room (except self)
            for p_name, p_state in player_states.items():
                if p_state['current_room'] == current_room_id and p_name != player_name:
                    send_game_event(p_name, f"{player_name} leaves to the {arg}.", room_id=current_room_id)

            player_state['current_room'] = target_room_id
            send_game_event(player_name, f"You move {arg}.")
            send_game_event(player_name, WORLD_MAP[target_room_id].get_full_description())

            # Announce arrival to new room (except self)
            opposite_direction = {
                'north': 'south', 'south': 'north',
                'east': 'west', 'west': 'east',
                'up': 'down', 'down': 'up',
                'in': 'out', 'out': 'in'
            }.get(arg, arg)

            for p_name, p_state in player_states.items():
                if p_state['current_room'] == target_room_id and p_name != player_name:
                    send_game_event(p_name, f"{player_name} arrives from the {opposite_direction}.", room_id=target_room_id)

            # SAVE PLAYER LOCATION AFTER MOVEMENT
            save_player_state(player_name, player_state)
            #description = "Move from:"
            #send_player_event(player_name,"move",WORLD_MAP[target_room_id].get_full_description());


        else:
            send_game_event(player_name, f"You cannot move {arg} from here.")

    elif parsed_command == 'take':
        item_found = None
        for item in current_room.items:
            if item.name.lower() == arg.lower():
                item_found = item
                break
        if item_found:
            if item_found.can_take:
                player_state['inventory'].append(item_found)
                current_room.remove_item(item_found.item_id)
                send_game_event(player_name, f"You take the {item_found.name}.")
                # Announce to others in the room
                for p_name, p_state in player_states.items():
                    if p_state['current_room'] == current_room_id and p_name != player_name:
                        send_game_event(p_name, f"{player_name} takes the {item_found.name}.", room_id=current_room_id)
                # SAVE PLAYER INVENTORY AFTER TAKING ITEM
                save_player_state(player_name, player_state)
            else:
                send_game_event(player_name, f"You cannot take the {item_found.name}.")
        else:
            send_game_event(player_name, f"There is no '{arg}' here to take.")

    elif parsed_command == 'inventory' or parsed_command == 'inv':
        if player_state['inventory']:
            items_list = [item.name for item in player_state['inventory']]
            send_game_event(player_name, f"Your inventory: {', '.join(items_list)}.")
        else:
            send_game_event(player_name, "Your inventory is empty.")

    elif parsed_command == 'say':
        if arg:
            message_to_send = f"{player_name} says: \"{arg}\""
            # Send to all players in the same room, including self
            for p_name, p_state in player_states.items():
                if p_state['current_room'] == current_room_id:
                    send_game_event(p_name, message_to_send, room_id=current_room_id)
        else:
            send_game_event(player_name, "What do you want to say?")

    elif parsed_command == 'help':
        help_message = "Available commands:\r\n"
        for cmd, desc in HELP_COMMANDS.items():
            help_message += f"   - {cmd}: {desc}\r\n"
        send_game_event(player_name, help_message.strip())

    elif parsed_command == 'quit':
        send_game_event(player_name, "Goodbye! Thanks for playing.")
        # Player is quitting, save their state one last time before removing from active states
        save_player_state(player_name, player_state)
        if player_name in player_states:
            del player_states[player_name]
            print(f"Player {player_name} removed from active states.")
            # Announce player departure to others in the room
            for p_name, p_state in player_states.items():
                if p_state['current_room'] == current_room_id and p_name != player_name:
                    send_game_event(p_name, f"{player_name} has left the game.", room_id=current_room_id)

    else:
        send_game_event(player_name, "Unknown command. Type 'help' for a list of commands.")


def run_game_engine():
    """Main loop for the game engine."""
    consumer_conf = {
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'game_engine_group',
        'auto.offset.reset': 'earliest' # Process all commands from start for testing
    }
    consumer = Consumer(consumer_conf)
    consumer.subscribe([PLAYER_COMMANDS_TOPIC])

    print("Game Engine starting...")
    try:
        while True:
            msg = consumer.poll(timeout=1.0) # Poll for messages (1 second timeout)
            if msg is None:
                # No message yet, give producer a chance to flush any pending messages
                producer.poll(0)
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    sys.stderr.write(f'%% {msg.topic()} [{msg.partition()}] reached end offset {msg.offset()}\n')
                else: # Changed from elif msg.error() to else to simplify logic
                    raise KafkaException(msg.error())
            else:
                player_name = msg.key().decode('utf-8') if msg.key() else "unknown_player"
                command = msg.value().decode('utf-8')

                # --- MODIFICATION START: Load player state from DB ---
                if player_name not in player_states:
                    loaded_state = load_player_state(player_name)
                    if loaded_state:
                        player_states[player_name] = loaded_state
                        send_game_event(player_name, f"Welcome back, {player_name}! You are in the {WORLD_MAP[loaded_state['current_room']].name}.", event_type="welcome")
                        # Immediately send a 'look' command for the player's current location
                        process_command(player_name, "look")
                    else:
                        # Failed to load/initialize player. This player cannot proceed.
                        send_game_event(player_name, "Error: Could not load or initialize player data. Please try again.")
                        continue # Skip processing command for this player
                # --- MODIFICATION END ---

                process_command(player_name, command)
            # Periodically poll the producer to free up space/call delivery reports
            producer.poll(0)

    except KeyboardInterrupt:
        print("\nGame Engine: Shutting down via KeyboardInterrupt.")
    except Exception as e:
        sys.stderr.write(f"Game Engine Error: {e}\n")
    finally:
        sys.stderr.write("Game Engine: Finalizing shutdown.\n")
        producer.flush(10) # Flush any outstanding messages before closing
        consumer.close() # Close the Kafka consumer

if __name__ == "__main__":
    run_game_engine()
