from flask import Flask, jsonify
import RPi.GPIO as GPIO
import adafruit_dht
import board
import time
import requests
import threading
import logging
from hx711 import HX711  # Ensure you are using a compatible HX711 library

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Initialize DHT11 (Temperature and Humidity sensor) on GPIO2
try:
    logging.info("Initializing DHT11 sensor on GPIO2")
    dht_device = adafruit_dht.DHT11(board.D2)
except Exception as e:
    logging.error(f"Error initializing DHT11: {e}")

# Pin configuration
SOUND = 3
TRIG = 17
ECHO = 27
LIGHT = 4

# GPIO setup
logging.info("Setting up GPIO pins")
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(SOUND, GPIO.IN)
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN)
GPIO.setup(LIGHT, GPIO.IN)

# Initialize HX711 for weight measurement
try:
    logging.info("Initializing HX711 on GPIO 9 and 10")
    hx = HX711(dout_pin=9, pd_sck_pin=10)
except Exception as e:
    logging.error(f"Error initializing HX711: {e}")

# Calibration factor for the load cell (adjust based on calibration)
calibration_factor = 102.372
zero_offset = 0

# Function to tare (zero) the scale manually
def tare_scale():
    global zero_offset
    try:
        logging.info("Taring the scale... Please ensure the scale is empty.")
        time.sleep(2)  # Allow some time for the scale to stabilize
        hx.reset()  # Reset the HX711
        raw_readings = []

        for i in range(10):
            raw_value = hx.read()
            if raw_value is not None:
                raw_readings.append(raw_value)
                logging.debug(f"Tare reading {i+1}: {raw_value}")
            else:
                logging.warning(f"Tare reading {i+1} failed: None")
            time.sleep(0.1)

        if raw_readings:
            zero_offset = sum(raw_readings) / len(raw_readings)
            logging.info(f"Scale tared successfully. Zero offset: {zero_offset}")
        else:
            raise ValueError("Failed to get valid readings during taring.")
    except Exception as e:
        logging.error(f"Error during tare: {e}")

# Function to get weight measurement from HX711
def get_weight():
    try:
        raw_value = hx.read()
        logging.debug(f"Raw HX711 reading: {raw_value}")
        if raw_value is None:
            raise ValueError("Failed to get data from HX711")

        weight = (raw_value - zero_offset) / calibration_factor
        return weight / 1000  # Convert to kg
    except Exception as e:
        logging.error(f"Error getting weight: {e}")
        return None

# Function to get distance from the ultrasonic sensor
def get_distance():
    try:
        logging.info("Measuring distance with ultrasonic sensor")
        GPIO.output(TRIG, False)
        time.sleep(0.000002)
        GPIO.output(TRIG, True)
        time.sleep(0.00001)
        GPIO.output(TRIG, False)

        while GPIO.input(ECHO) == 0:
            pass
        pulse_start = time.time()

        while GPIO.input(ECHO) == 1:
            pass
        pulse_end = time.time()

        pulse_duration = pulse_end - pulse_start
        distance = (pulse_duration * 34300) / 2  # cm
        logging.debug(f"Measured distance: {distance} cm")
        return round(distance, 1)
    except Exception as e:
        logging.error(f"Error getting distance: {e}")
        return None

# Function to read temperature and humidity from DHT11
def temperature_humidity():
    try:
        temperature = dht_device.temperature
        humidity = dht_device.humidity
        logging.debug(f"Temperature: {temperature}, Humidity: {humidity}")
        return {"temperature": temperature, "humidity": humidity}
    except RuntimeError as error:
        logging.error(f"Error reading DHT11: {error}")
        return {"error": str(error)}

# Function to check if bees are alive using the sound sensor
def is_bee_alive():
    try:
        state = GPIO.input(SOUND) == 0
        logging.debug(f"Bee sound sensor state: {state}")
        return state
    except Exception as e:
        logging.error(f"Error checking bee sound sensor: {e}")
        return None

# Function to check if hive is open using the light sensor
def is_hive_open():
    try:
        state = GPIO.input(LIGHT) == GPIO.HIGH
        logging.debug(f"Hive light sensor state: {state}")
        return state
    except Exception as e:
        logging.error(f"Error checking hive light sensor: {e}")
        return None

# Function to send data to remote API endpoint
def send_data():
    while True:
        data = {
            "temperature_humidity": temperature_humidity(),
            "distance": get_distance(),
            "bees_alive": is_bee_alive(),
            "hive_open": is_hive_open(),
            "weight": get_weight()
        }

        try:
            logging.info("Sending data to remote API endpoint")
            response = requests.post('http://bees.aiiot.center/', json=data)
            if response.status_code == 200:
                logging.info(f'Data sent successfully: {response.json()}')
            else:
                logging.warning(f'Failed to send data: {response.status_code} - {response.text}')
        except Exception as e:
            logging.error(f"Error sending data: {e}")
        
        time.sleep(5)  # Wait 5 seconds before sending the next set of data

# Flask route to fetch sensor data as JSON
@app.route('/data', methods=['GET'])
def get_data():
    data = {
        "temperature_humidity": temperature_humidity(),
        "distance": get_distance(),
        "bees_alive": is_bee_alive(),
        "hive_open": is_hive_open(),
        "weight": get_weight()
    }
    logging.info(f"Providing sensor data via API: {data}")
    return jsonify(data)

# Main function to run the Flask server and tare the scale
if __name__ == '__main__':
    try:
        tare_scale()  # Tare the scale on startup
        data_thread = threading.Thread(target=send_data)
        data_thread.daemon = True  # Set thread as daemon to close with main program
        data_thread.start()
        
        logging.info("Starting Flask server")
        app.run(host='0.0.0.0', port=5000)
    finally:
        logging.info("Cleaning up GPIO pins")
        GPIO.cleanup()
