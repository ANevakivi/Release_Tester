import paho.mqtt.client as mqtt
import simpleaudio as sa
import json
import os
import re
import threading
import time
import logging

timer_completion_event = threading.Event()
timer_cancellation_event = threading.Event()

active_timers = {}  # Dictionary to store active timers
expected_topics = []

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a console handler and set the level to DEBUG
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create a formatter and add it to the console handler
formatter = logging.Formatter('%(message)s')
console_handler.setFormatter(formatter)

# Add the console handler to the logger
logger.addHandler(console_handler)

# Set up logging for paho MQTT library
mqtt_logger = logging.getLogger("paho.mqtt")
mqtt_logger.setLevel(logging.DEBUG)
mqtt_logger.addHandler(console_handler)

# Set up logging for simpleaudio library
sa_logger = logging.getLogger("simpleaudio")
sa_logger.setLevel(logging.DEBUG)
sa_logger.addHandler(console_handler)

def handle_publish(action):
    logger.info(
        f"\nAction publish.\n"
        f"Topic: {action['topic']}\n"
        f"Payload: {action['payload']}\n"
    )
    payload = json.dumps(action['payload'])
    mqtt_client.publish(action['topic'], payload)
    if 'sleep' in action:
        sleep_duration = action['sleep'] / 1000.0  # Convert milliseconds to seconds
        time.sleep(sleep_duration)

def handle_subscribe(action):
    mqtt_client.subscribe(action['topic'])
    logger.info(
        f"\nAction subscribe.\n"
        f"Topic: {action['topic']}\n"
        f"Payload requirement: {action['payload']}"
    )
    if "timeout" in action:
        start_timer(action['topic'], action['timeout'])
        logger.info(f"timeout: {action['timeout']}\n")

def handle_play_file(action):
    file_path = action['filePath']
    print(f"Playing file:{file_path}")
    try:
        wave_obj = sa.WaveObject.from_wave_file(file_path)
        play_obj = wave_obj.play()
        play_obj.wait_done()
    except FileNotFoundError:
        logger.error(f"Error: File '{file_path}' not found.")
    except Exception as e:
        logger.error(f"Error: An unexpected error occurred: {str(e)}")

ACTION_HANDLERS = {
    "pub": handle_publish,
    "sub": handle_subscribe,
    "play": handle_play_file
}

def mqtt_thread():
    mqtt_client.client.loop_start()

class MQTTClient:
    def __init__(self, broker_url, broker_port):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.broker_url = broker_url
        self.broker_port = broker_port

        self.connected_event = threading.Event()

    def connect(self):
        self.client.connect(self.broker_url, self.broker_port)
        t1 = threading.Thread(target=mqtt_thread)
        t1.start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe(self, topic):
        self.client.subscribe(topic)

    def unsubscribe(self, topic):
        self.client.unsubscribe(topic)

    def publish(self, topic, payload):
        self.client.publish(topic, payload)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            self.connected_event.set()
        else:
            logger.error(f"Failed to connect, return code={rc}")

    def on_message(self, client, userdata, msg):
        logger.info(f"Received message on topic: {msg.topic}")
        logger.info(f"Message: {msg.payload.decode()}")

        if expected_topics:
            if msg.topic not in expected_topics:
                logger.warning(f"Received topic {msg.topic} not expected")
                test_result.set_fail(f"Received topic {msg.topic} not expected")
                return
            else:
                for action in data['Actions']:
                    for key, value in action.items():
                        if key == "pub":
                            continue
                        else:
                            if 'topic' in value.keys() and value['topic'] == msg.topic:

                                if 'failOnReceive' in value and value['failOnReceive']:
                                    logger.warning("Received message triggered a fail")
                                    test_result.set_fail("Received message triggered a fail")

                                elif 'payload' in value:
                                    expected_payload = value['payload']
                                    received_payload = json.loads(msg.payload.decode())

                                    if expected_payload == "any":
                                        test_result.set_pass()
                                    else:
                                        for key, value in expected_payload.items():
                                            if key not in received_payload or received_payload[key] != value:
                                                logger.warning(
                                                    f"Payload key {key} and value {value} not found in received payload or mismatched")
                                                test_result.set_fail(
                                                    f"Payload mismatch. Expected: {expected_payload}. Got: {received_payload}")
                                                break
                                        else:
                                            test_result.set_pass()

                                mqtt_client.unsubscribe(msg.topic)

        # Cancel the timer for the received topic
        if active_timers:
            if msg.topic in active_timers:
                cancel_timer(msg.topic)
                logger.info(f"Cancelled timer for topic: {msg.topic}")

class TimerThread(threading.Thread):
    def __init__(self, timer_id, duration_ms):
        super().__init__()
        self.timer_id = timer_id
        self.duration = duration_ms / 1000.0
        self.callback = timer_callback

    def run(self):
        event_triggered = threading.Event()
        start_time = time.time()

        while not event_triggered.is_set():

            if timer_cancellation_event.is_set():
                logger.info("The timer was cancelled")
                event_triggered.set()
            elif time.time() - start_time > self.duration:
                self.callback(self.timer_id)
                event_triggered.set()

        del active_timers[self.timer_id]

    def cancel(self):
        timer_cancellation_event.set()

class TestResult:
    def __init__(self, test_name):
        self.test_name = test_name
        self.result = None
        self.reason = None

    def set_pass(self):
        self.result = "Pass"

    def set_fail(self, reason):
        self.result = "Fail"
        self.reason = reason

    def get_result(self):
        return self.result

    def __str__(self):
        return f"Test Name: {self.test_name}\nResult: {self.result}\nReason: {self.reason or 'N/A'}\n"

class TestReport:
    def __init__(self):
        self.test_results = []

    def add_result(self, test_result):
        self.test_results.append(test_result)

    def generate_report(self):
        report = ""
        for test_result in self.test_results:
            report += str(test_result)
        return report

def start_timer(timer_id, duration):
    timer_thread = TimerThread(timer_id, duration)
    active_timers[timer_id] = timer_thread
    timer_thread.start()

def cancel_timer(timer_id):
    timer_thread = active_timers.get(timer_id)
    if timer_thread:
        # Set the cancellation event to cancel the timer
        timer_cancellation_event.set()
        timer_thread.join()  # Wait for the timer thread to complete
        # Reset the cancellation event
        timer_cancellation_event.clear()

def timer_callback(timer_id):
    logger.debug(f"Timer {timer_id} completed")
    test_result.set_fail(f"Topic: {timer_id} timeout")
    timer_completion_event.set()

def get_files_in_folder(folder_path):
    file_paths = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_paths.append(file_path)
    file_paths.sort(key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split('(\d+)', x)])  # Sort with custom key
    return file_paths

def read_json_file(file_path):
    try:
        with open(file_path, 'r') as file:
            json_data = json.load(file)
        return json_data
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except Exception as e:
        logger.error(f"An error occurred while reading JSON file: {file_path}")
        logger.error(f"Error message: {str(e)}")

if __name__ == '__main__':
    mqtt_client = MQTTClient("localhost", 1883)
    mqtt_client.connect()
    mqtt_client.connected_event.wait()

    test_report = TestReport()  # Create an instance of TestReport

    files = get_files_in_folder("Test_scenarios")
    for file in files:
        data = read_json_file(file)

        test_name = data.get("testName")  # Retrieve the test case name from the JSON data
        test_result = TestResult(test_name)  # Create a TestResult object for the current test case

        for item in data["Actions"]:
            if test_result.get_result() == "Fail":
                # Create a copy of the keys because list changed upon iteration.
                timers = list(active_timers.keys()) 
                for timer in timers:
                    logger.debug("Test marked as Fail cancelling remaining timers")
                    cancel_timer(timer)
                break
            
            action_type, action_data = next(iter(item.items()))
            if action_type == "sub":
                expected_topics.append(action_data["topic"])

            if action_type in ACTION_HANDLERS:
                ACTION_HANDLERS[action_type](action_data)

                if active_timers:
                    if timer_completion_event.is_set():
                        test_result.set_fail("Timeout")

            else:
                logger.warning(f"Unknown action type: {action_type}")

        while active_timers:
            timer_completion_event.wait(timeout=0)

        logger.info(test_result)
        test_report.add_result(test_result)
        timer_completion_event.clear()

    final_report = test_report.generate_report()
    #logger.info(final_report)
