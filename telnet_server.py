# telnet_server.py

import socket
import threading
import json
import time
import sys

from confluent_kafka import Producer, Consumer, KafkaException, KafkaError

import config # Import your config file

# --- Server Configuration ---
TELNET_HOST = '0.0.0.0' # Listen on all available network interfaces
TELNET_PORT = 2323      # Choose a port > 1024 (23 is standard Telnet, often needs root)

# Kafka configuration from config.py
KAFKA_BOOTSTRAP_SERVERS = config.KAFKA_BOOTSTRAP_SERVERS
PLAYER_COMMANDS_TOPIC = config.PLAYER_COMMANDS_TOPIC
GAME_EVENTS_TOPIC = config.GAME_EVENTS_TOPIC

# Shared Kafka Producer (can be reused across threads for efficiency)
_kafka_producer = None
_producer_lock = threading.Lock() # To ensure thread-safe access if needed (less critical for produce)

def get_kafka_producer():
    """Returns a shared Kafka Producer instance."""
    global _kafka_producer
    with _producer_lock:
        if _kafka_producer is None:
            producer_conf = {
                'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
                'client.id': 'telnet-server-producer'
            }
            _kafka_producer = Producer(producer_conf)
        return _kafka_producer

def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result. """
    if err is not None:
        sys.stderr.write(f'Message delivery failed: {err}\n')
    #else:
    #    print(f'Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}')

def send_to_client(conn, message):
    """Sends a message to the Telnet client, ensuring it ends with newline and prompt."""
    try:
        # For simplicity, just send message + newline + prompt
        conn.sendall(f"\r\n[GAME]: {message}\r\n> ".encode('utf-8'))
    except BrokenPipeError:
        # Client disconnected, will be handled by the main client loop's exception
        print(f"Client disconnected while trying to send message.")
    except Exception as e:
        print(f"Error sending to client: {e}")

def consume_player_events(player_name, consumer, conn, client_active_event):
    """
    Thread function to continuously consume game events for a specific player
    and send them back to the Telnet client.
    """
    print(f"[{player_name}] Listening for game events...")
    try:
        # Loop while client is active AND Kafka consumer is not closing
        while client_active_event.is_set():
            msg = consumer.poll(timeout=0.1) # Short timeout to allow frequent event checks
            if msg is None:
                continue

            if msg.error():
                # End of partition event, not an error - just internal Kafka status
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    pass
                elif msg.error():
                    sys.stderr.write(f'[{player_name}] Consumer error: {msg.error()}\n')
            else:
                try:
                    event_data_raw = msg.value().decode('utf-8')
                    event_data = json.loads(event_data_raw) # Parse JSON

                    # Only process events directed to this player or general messages (player == None)
                    if event_data.get('player') == player_name or event_data.get('player') is None:
                        send_to_client(conn, event_data['message'])

                except json.JSONDecodeError:
                    sys.stderr.write(f"[{player_name}] Warning: Could not decode JSON event: {event_data_raw}\n")
                except KeyError:
                    sys.stderr.write(f"[{player_name}] Warning: Event missing 'message' key: {event_data_raw}\n")
                except Exception as e:
                    sys.stderr.write(f"[{player_name}] Error processing event: {e}\n")

    except Exception as e:
        sys.stderr.write(f"[{player_name}] Game event listener thread error: {e}\n")
    finally:
        # Crucial: Close the consumer ONLY when this thread is truly exiting
        consumer.close()
        print(f"[{player_name}] Game event listener stopped.")


def handle_client(conn, addr):
    """
    Handles a single Telnet client connection. Runs in its own thread.
    """
    player_name = None
    consumer = None
    kafka_consumer_thread = None
    client_active_event = threading.Event() # Event to signal consumer thread to stop
    client_active_event.set() # Set initially to active (client is active)
    input_buffer = b"" # NEW: Buffer for incoming bytes until a newline is found

    print(f"[{addr[0]}:{addr[1]}] Client connected.")
    try:
        conn.sendall(b"Welcome to the Kafka MUD!\r\n")
        conn.sendall(b"Please enter your player name: ")

        # Get player name - use the same buffering logic for the first input
        while b"\n" not in input_buffer:
            try:
                data = conn.recv(1024)
                if not data: # Client disconnected
                    raise ConnectionResetError("Client disconnected during name input.")
                input_buffer += data
            except ConnectionResetError:
                raise
            except Exception as e:
                sys.stderr.write(f"Error reading name from client: {e}\n")
                raise

        line_end_index = input_buffer.find(b"\n")
        name_input_bytes = input_buffer[:line_end_index]
        input_buffer = input_buffer[line_end_index + 1:] # Clear processed part of buffer
        
        name_input = name_input_bytes.decode('utf-8', errors='ignore').strip().replace('\r', '')


        if not name_input:
            send_to_client(conn, "No name entered. Disconnecting.")
            return
        player_name = name_input

        print(f"[{addr[0]}:{addr[1]}] Player '{player_name}' joined.")
        send_to_client(conn, f"Hello, {player_name}!")
        send_to_client(conn, "Type 'quit' to exit.")
        send_to_client(conn, "For a list of commands, type 'help'.") # Hint for new users

        # Initialize Kafka consumer for this player
        consumer_conf = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': f'game_event_listener_{player_name}_{time.time_ns()}',
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000
        }
        consumer = Consumer(consumer_conf)
        consumer.subscribe([GAME_EVENTS_TOPIC])

        # Start a separate thread to consume Kafka events for this player
        kafka_consumer_thread = threading.Thread(
            target=consume_player_events,
            args=(player_name, consumer, conn, client_active_event)
        )
        kafka_consumer_thread.start()

        # Get the shared Kafka producer
        producer = get_kafka_producer()

        # Send an initial "look" command to get the first room description.
        time.sleep(0.5)
        producer.produce(PLAYER_COMMANDS_TOPIC, key=player_name.encode('utf-8'), value=f"look".encode('utf-8'), callback=delivery_report)
        producer.flush()

        # Main loop for receiving Telnet commands
        while True:
            conn.sendall(b"> ") # Send prompt before waiting for input

            # NEW: Loop to receive and process full lines from the buffer
            while b"\n" not in input_buffer: # Keep receiving until a newline is in the buffer
                try:
                    data = conn.recv(1024) # Read up to 1024 bytes at a time
                    if not data:
                        # Client disconnected
                        raise ConnectionResetError("Client disconnected during command input.")
                    input_buffer += data
                except ConnectionResetError:
                    raise # Propagate disconnect to outer try-except
                except Exception as e:
                    sys.stderr.write(f"Error reading command from client: {e}\n")
                    raise # Propagate other errors to outer try-except

            # Extract the first complete line from the buffer
            line_end_index = input_buffer.find(b"\n")
            raw_command_bytes = input_buffer[:line_end_index]
            input_buffer = input_buffer[line_end_index + 1:] # Keep remaining buffer content for next command

            # Clean up the command: decode, strip carriage returns and whitespace
            # Telnet clients often send \r\n, so strip both.
            command = raw_command_bytes.decode('utf-8', errors='ignore').strip().replace('\r', '')

            if not command: # Handle empty input (e.g., just pressing enter)
                continue

            if command.lower() == 'quit':
                send_to_client(conn, "Goodbye!")
                break

            print(f"[{player_name}] Command: {command}")
            # Send command to Kafka
            producer.produce(PLAYER_COMMANDS_TOPIC, key=player_name.encode('utf-8'), value=command.encode('utf-8'), callback=delivery_report)
            producer.flush()

    except ConnectionResetError:
        print(f"[{player_name or addr[0]}:{addr[1]}] Client disconnected abruptly (ConnectionResetError).")
    except BrokenPipeError:
        print(f"[{player_name or addr[0]}:{addr[1]}] Client pipe broken (BrokenPipeError).")
    except Exception as e:
        sys.stderr.write(f"[{player_name or addr[0]}:{addr[1]}] Error handling client: {e}\n")
    finally:
        # --- Crucial Cleanup Sequence ---
        print(f"[{player_name or addr[0]}:{addr[1]}] Initiating client cleanup.")
        client_active_event.clear() # Signal consumer thread to stop

        if kafka_consumer_thread and kafka_consumer_thread.is_alive():
            print(f"[{player_name or addr[0]}:{addr[1]}] Waiting for consumer thread to join...")
            kafka_consumer_thread.join(timeout=5) # Give it 5 seconds to shut down
            if kafka_consumer_thread.is_alive():
                print(f"[{player_name or addr[0]}:{addr[1]}] Consumer thread did not terminate gracefully within timeout.")
            else:
                print(f"[{player_name or addr[0]}:{addr[1]}] Consumer thread joined successfully.")
        
        conn.close() # Close the socket connection
        print(f"[{player_name or addr[0]}:{addr[1]}] Connection closed and resources released.")


def start_telnet_server():
    """Starts the main Telnet server."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Allow reusing the address quickly
    server_socket.bind((TELNET_HOST, TELNET_PORT))
    server_socket.listen(5) # Listen for up to 5 pending connections

    print(f"Telnet Server listening on {TELNET_HOST}:{TELNET_PORT}...")
    print("Use a Telnet client to connect.")

    try:
        while True:
            conn, addr = server_socket.accept() # Accept new connection
            client_thread = threading.Thread(target=handle_client, args=(conn, addr))
            client_thread.daemon = True # Allows main server to exit gracefully if Ctrl+C is pressed
            client_thread.start()
    except KeyboardInterrupt:
        print("\nTelnet Server shutting down via KeyboardInterrupt.")
    except Exception as e:
        print(f"Server error: {e}")
    finally:
        server_socket.close()
        print("Telnet Server: Socket closed.")

if __name__ == "__main__":
    start_telnet_server()