from confluent_kafka import Consumer, KafkaException, KafkaError
import sys
import json
import logging

# --- Configuration ---
# Set up basic logging to see script activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Kafka broker address (where your Dockerized Kafka is running)
KAFKA_BROKER = "localhost:9092"

# The Kafka topic where your MUD game sends events
# IMPORTANT: Replace 'player_events' with the actual topic name your game uses if different.
MUD_EVENTS_TOPIC = "player_events"

# A unique identifier for this consumer instance within its group
# Kafka uses consumer groups for message distribution and fault tolerance.
# All consumers with the same group.id will share the load of consuming partitions.
CONSUMER_GROUP_ID = "mud-event-monitor-group"

# --- Main Consumer Logic ---
def consume_events(broker_address, topic_name, group_id):
    """
    Configures and runs a Kafka Consumer to listen for and print messages
    from a specified topic.
    """
    conf = {
        'bootstrap.servers': broker_address,      # Kafka broker address
        'group.id': group_id,                     # Consumer group ID
        'auto.offset.reset': 'earliest',          # Start reading from the earliest available message
                                                  # if no committed offset is found for this group.
        'enable.auto.commit': True,               # Automatically commit offsets periodically
        'session.timeout.ms': 10000,              # Max time between heartbeats before consumer is considered dead
        'max.poll.interval.ms': 300000            # Max time between polls before consumer is considered dead
    }

    consumer = Consumer(conf)

    try:
        logging.info(f"Attempting to subscribe to topic: '{topic_name}' with consumer group: '{group_id}'...")
        consumer.subscribe([topic_name])
        logging.info("Subscription successful. Waiting for messages...")

        while True:
            # Poll for messages with a timeout of 1 second.
            # If no message arrives within 1 second, it returns None.
            msg = consumer.poll(1.0)

            if msg is None:
                # No message arrived within the timeout, continue polling
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # This is an end-of-partition indicator, not a critical error.
                    # It means the consumer has read all available messages up to this point.
                    logging.debug(f"Reached end of partition {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")
                elif msg.error():
                    # Handle other potential Kafka errors
                    logging.error(f"Kafka error: {msg.error()}")
                    raise KafkaException(msg.error())
            else:
                # Successfully received a message!
                try:
                    # Kafka messages are bytes; decode them to UTF-8 string first
                    # Then, parse the JSON string into a Python dictionary for easy access
                    event_data = json.loads(msg.value().decode('utf-8'))

                    logging.info(f"--- New Event ---")
                    logging.info(f"Topic: {msg.topic()} | Partition: {msg.partition()} | Offset: {msg.offset()}")
                    logging.info(f"Timestamp: {msg.timestamp()[1]}") # msg.timestamp() returns (type, timestamp_ms)
                    logging.info("Content:")
                    logging.info(json.dumps(event_data, indent=2)) # Pretty-print JSON for readability
                    logging.info(f"-----------------")

                except json.JSONDecodeError:
                    logging.warning(f"Received non-JSON message from topic {msg.topic()} at offset {msg.offset()}:")
                    logging.warning(f"Raw Message: {msg.value().decode('utf-8', errors='ignore')}")
                except Exception as e:
                    logging.error(f"Error processing message from topic {msg.topic()} at offset {msg.offset()}: {e}")

    except KeyboardInterrupt:
        logging.info("\nConsumer manually stopped (Ctrl+C).")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
    finally:
        # Ensure the consumer is closed to commit final offsets and release resources
        consumer.close()
        logging.info("Consumer client closed.")

# --- Script Execution ---
if __name__ == "__main__":
    # Allows overriding topic and group ID via command-line arguments for flexibility
    if len(sys.argv) > 1:
        MUD_EVENTS_TOPIC = sys.argv[1]
    if len(sys.argv) > 2:
        CONSUMER_GROUP_ID = sys.argv[2]

    consume_events(KAFKA_BROKER, MUD_EVENTS_TOPIC, CONSUMER_GROUP_ID)
