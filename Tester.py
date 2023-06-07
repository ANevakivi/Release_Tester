import paho.mqtt.client as mqtt
import simpleaudio as sa
import json, os, re, threading

timer_completion_event = threading.Event()
timer_cancellation_event = threading.Event()

def handle_publish(action):
    print(
        f"\nAction publish.\n"
        f"Topic: {action['topic']}\n"
        f"Payload: {action['payload']}"
    )
    mqtt_client.publish(action['topic'], action['payload')

def handle_subscribe(action):

    mqtt_client.subscribe(action['topic'])
    if "timeout" in action:
        start_timer(action['topic'], action['timeout'])
        print(f"timeout: {action['timeout']}")

    print(
        f"\nAction subscribe.\n"
        f"Topic: {action['topic']}\n"
        f"Payload requirement: {action['payload']}"
        )

def handle_play_file(action):
    try:
        wave_obj = sa.WaveObject.from_wave_file(file_path)
        play_obj = wave_obj.play()
        play_obj.wait_done()
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except Exception as e:
        print(f"Error: An unexpected error occurred: {str(e)}")

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
            print("Connected to MQTT broker")
        else:
            print(f"Failed to connect, return code={rc}")

    def on_message(self, client, userdata, msg):
        print(f"Received message on topic: {msg.topic}")
        print(f"Message: {msg.payload.decode()}")

class TimerThread(threading.Thread):
    def __init__(self, timer_id, duration_ms):
        super().__init__()
        self.timer_id = timer_id
        self.duration = duration_ms / 1000.0
        self.callback = timer_callback

    def run(self):
        event_triggered = threading.Event()
        while not event_triggered.is_set():
            event_triggered.wait(self.duration)

            if timer_cancellation_event.is_set():
                print("The timer was cancelled")
                event_triggered.set()
            elif not event_triggered.is_set():
                print("The timer completed")
                self.callback(self.timer_id)
                event_triggered.set()
        del active_timers[self.timer_id]

    def cancel(self):
        self.cancelled.set()

def start_timer(timer_id, duration, callback):
    timer_thread = TimerThread(timer_id, duration, callback)
    active_timers[timer_id] = timer_thread
    timer_thread.start()
    return timer_thread

def cancel_timer(timer_id):
    timer_thread = active_timers.get(timer_id)
    if timer_thread:
        # Set the cancellation event to cancel the timer
        timer_cancellation_event.set()
        timer_thread.join()  # Wait for the timer thread to complete
        # Reset the cancellation event
        timer_cancellation_event.clear()

def timer_callback(timer_id):
    print(f"Timer {timer_id} completed")
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
        print(f"File not found: {file_path}")
    except Exception as e:
        print(f"An error occurred while reading JSON file: {file_path}")
        print(f"Error message: {str(e)}")


if __name__ == '__main__':
    mqtt_client = MQTTClient("localhost", 1883)
    mqtt_client.connect()

    files = get_files_in_folder("Test_scenarios")
    for file in files:
        data = read_json_file(file)

        for item in data["Actions"]:
            action_type, action_data = next(iter(item.items()))

            if action_type in ACTION_HANDLERS:
                ACTION_HANDLERS[action_type](action_data)

                if active_timers:
                    if timer_completion_event.is_set():

            else:
                print(f"Unknown action type: {action_type}")
