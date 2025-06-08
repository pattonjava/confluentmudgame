# player_client.py

from confluent_kafka import Producer, Consumer, KafkaException, KafkaError
import sys
import threading
import time
import json # To parse structured game events

import config # Import your config file

# Kafka configuration from config.py
KAFKA_BOOTSTRAP_SERVERS = config.KAFKA_BOOTSTRAP_SERVERS
PLAYER_COMMANDS_TOPIC = config.PLAYER_COMMANDS_TOPIC
GAME_EVENTS_TOPIC = config.GAME_EVENTS_TOPIC

player_name = input("Enter your player name: ")

# Producer for sending commands
producer_conf = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'client.id': f'{player_name}-producer'
}
producer = Producer(producer_conf)

# Consumer for receiving game events
consumer_conf = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'group.id': f'game_event_listener_{player_name}',
    'auto.offset.reset': 'latest'
}
consumer = Consumer(consumer_conf)
consumer.subscribe([GAME_EVENTS_TOPIC])

def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result. """
    if err is not None:
        sys.stderr.write(f'Message delivery failed: {err}\n')

def consume_game_events():
    """ Continuously consume messages from game_events topic. """
    print(f"Listening for game events...")
    try:
        while True:
            msg = consumer.poll(timeout=0.1)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    pass
                elif msg.error():
                    sys.stderr.write(f'Consumer error: {msg.error()}\n')
            else:
                try:
                    event_data_raw = msg.value().decode('utf-8')
                    event_data = json.loads(event_data_raw) # Parse JSON
                    
                    # Only print events directed to this player or general messages
                    if event_data.get('player') == player_name or event_data.get('player') is None:
                        # For now, we just print the 'message' part
                        print(f"\n[GAME]: {event_data['message']}")
                        sys.stdout.write(f"> ")
                        sys.stdout.flush()

                except json.JSONDecodeError:
                    sys.stderr.write(f"Warning: Could not decode JSON event: {event_data_raw}\n")
                except KeyError:
                    sys.stderr.write(f"Warning: Event missing 'message' key: {event_data_raw}\n")

    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        print("Game event listener stopped.")

# Start the event consuming thread
event_thread = threading.Thread(target=consume_game_events)
event_thread.daemon = True
event_thread.start()

# Main loop for sending commands
print("Type 'quit' to exit.")
print(f"You are {player_name}.")

# Give consumer thread a moment to start and for initial events to propagate
time.sleep(1)

# Send an initial "look" command to get the first room description
producer.produce(PLAYER_COMMANDS_TOPIC, key=player_name.encode('utf-8'), value=f"look".encode('utf-8'), callback=delivery_report)
producer.flush()

while True:
    try:
        command = input(f"> ").strip()
        if command.lower() == 'quit':
            break

        if not command:
            continue

        producer.produce(PLAYER_COMMANDS_TOPIC, key=player_name.encode('utf-8'), value=command.encode('utf-8'), callback=delivery_report)
        producer.flush()

    except KeyboardInterrupt:
        break
    except Exception as e:
        sys.stderr.write(f"Error sending command: {e}\n")

print("Exiting game client.")
