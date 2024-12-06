import requests
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
import boto3
import os
from deepface import DeepFaceCheckKeyPadCode
from scipy.spatial.distance import cosine
import numpy as np
import cv2
from picamera2 import Picamera2
import time
import threading
import RPi.GPIO as GPIO

# Configuration
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SENDER_EMAIL = 'edenandavishag@gmail.com'
SENDER_PASSWORD = 'yupaimyhuvwghxue'
RECIPIENT_EMAIL = 'avishags65@gmail.com'
S3_BUCKET = "avishageden"
IMAGES_FOLDER = "ServerImages"
CAPTURED_IMAGE = 'CapturedImage.JPG'
camera = None
url = "https://1q4ovkdgy0.execute-api.us-east-1.amazonaws.com/CheckCode/CheckKeyPadCode"

COL_PINS = [16, 20, 21]  # GPIO27, GPIO22, GPIO10
ROW_PINS = [8, 7, 1, 12]

# Keypad layout
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#']
]


# Email Sending Function
def send_notification_email(subject_line, message_content, file_attachment=None, embedded_image=None):
    try:
        email = MIMEMultipart()
        email['From'] = SENDER_EMAIL
        email['To'] = RECIPIENT_EMAIL
        email['Subject'] = subject_line

        # Attach message content
        email.attach(MIMEText(message_content, 'plain'))

        # Add a file as an attachment
        if file_attachment:
            with open(file_attachment, 'rb') as attachment_file:
                attached_file = MIMEBase('application', 'octet-stream')
                attached_file.set_payload(attachment_file.read())
            encoders.encode_base64(attached_file)
            attached_file.add_header(
                'Content-Disposition',
                f'attachment; filename="{os.path.basename(file_attachment)}"'
            )
            email.attach(attached_file)

        # Embed an image within the email
        if embedded_image:
            with open(embedded_image, 'rb') as image_file:
                inline_image = MIMEImage(image_file.read())
                inline_image.add_header('Content-ID', '<image>')
                inline_image.add_header(
                    'Content-Disposition',
                    f'inline; filename="{os.path.basename(embedded_image)}"'
                )
                email.attach(inline_image)

        # Establish connection and send the email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            smtp.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, email.as_string())

        print("Email sent successfully.")

    except Exception as e:
        print(f"Email failed to send: {e}")


def setup_keypad():
    GPIO.setmode(GPIO.BCM)
    for row in ROW_PINS:
        GPIO.setup(row, GPIO.OUT)
        GPIO.output(row, GPIO.LOW)
    for col in COL_PINS:
        GPIO.setup(col, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def read_key():
    for row_index, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)  # Activate the current row
        for col_index, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)  # Reset the row
                return KEYPAD[row_index][col_index]
        GPIO.output(row_pin, GPIO.LOW)  # Reset the row
    return None


def send_code_to_aws(code):
    try:
        result = False
        print(f"Sending code {code} to AWS API...")
        data = {
            "code": code
        }

        headers = {
            "Content-Type": "application/json"  # Make sure to set the header to application/json
        }
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            result = response.json()
            if result.get("match"):
                result = True
        else:
            print(f"Error: Received status code {response.status_code}")
    except Exception as e:
        print(f"Error sending code to AWS: {e}")
    finally:
        return result


def keypad_thread():
    global camera
    setup_keypad()
    code = ""
    print("Keypad thread started. Waiting for 4-digit code...")
    while True:
        key = read_key()
        if key:
            print(f"Key pressed: {key}")
            if key.isdigit():
                code += key
                print(f"Current code: {code}")
                if len(code) == 4:
                    print(f"4-digit code entered: {code}")
                    result = send_code_to_aws(code)  # Send the code to AWS
                    if result == False:
                        image_path ="keyPadMistake.jpg"
                        camera.start_and_capture_file(image_path)
                        subject = "Incorect code entarance"
                        message = f"Dear customer. we announce you that trying entarance to your safe with wrong password has been done. The code that was pressed was {code}. We attach you a photo that was shot once it was done."
                        send_notification_email(
                        subject_line=subject,
                        message_content=message,
                        embedded_image=image_path
                        )
                    else:
                        print("Code matched! Access granted.")
                    code=""
            time.sleep(0.3)  # Debounce
       
def initialize_nfc(uart):
    """
    Initialize the PN532 by sending the SAMConfiguration command.
    """
    # SAMConfiguration command: 0xD4 0x14 0x01
    uart.write(bytearray([0x00, 0x00, 0xFF, 0x03, 0xFD, 0xD4, 0x14, 0x01, 0x17, 0x00]))
    response = uart.read(64)
    if response and len(response) > 0:
        print("NFC initialized successfully.")
    else:
        print("Failed to initialize NFC. Exiting...")
        exit()

def poll_for_tags(uart):

    try:
        print("Waiting for NFC tags...")
        while True:
            # InListPassiveTarget command: 0xD4 0x4A 0x01 0x00
            uart.write(bytearray([0x00, 0x00, 0xFF, 0x04, 0xFC, 0xD4, 0x4A, 0x01, 0x00, 0xE1, 0x00]))
            response = uart.read(64)
            if response and len(response) > 10:
                print("NFC tag detected!")
            time.sleep(0.5)  # Adjust polling frequency as needed
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        uart.close()
        
def init_and_start_nfc_detection():
 try:
     uart = serial.Serial('/dev/serial0', baudrate=115200, timeout=1)
     print("Serial connection established.")
     initialize_nfc(uart)
     poll_for_tags(uart)
 except Exception as e:
     print(f"Error: {e}")

def main():
    global camera
    try:
        camera = Picamera2()
        camera.configure(camera.create_video_configuration())
        camera.start()
        threads = [
            threading.Thread(target=keypad_thread, daemon=True),
            threading.Thread(target=init_and_start_nfc_detection, daemon=True),
        ]
        for thread in threads:
            thread.start()

    except KeyboardInterrupt:
        print("\nProgram interrupted. Cleaning up...")
    finally:
        GPIO.cleanup()
        camera.close()
        print("Program terminated.")

if __name__ == "__main__":
    main()
