import datetime
import json
import os
import platform
import re
import smtplib
import sys
import threading
import time
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request

if platform.system() != "Windows":
    from daemon import DaemonContext  # Only available on Unix-like systems

# Define global script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

def load_config(config_file):
    """Load configuration from JSON file."""
    with open(config_file, "r") as f:
        return json.load(f)

# Load configuration
config = load_config(f"{script_dir}/config.json")

# Extract Config Sections
TELEGRAM_CONFIG = config.get("telegram", {})
DISCORD_CONFIG = config.get("discord", {})
WEBHOOK_SECRET = config.get("webhook_secret")
NETWORK_CONFIG = config.get("network", {})
RETRY_CONFIG = config.get("retry", {})
EMAIL_CONFIG = config.get("email", {})

# Network Configuration
FOREGROUND_IP   = NETWORK_CONFIG.get("foreground_ip", "127.0.0.1")
FOREGROUND_PORT = NETWORK_CONFIG.get("foreground_port", 8000)
BACKGROUND_IP   = NETWORK_CONFIG.get("background_ip", "0.0.0.0")
BACKGROUND_PORT = NETWORK_CONFIG.get("background_port", 8080)

# Logging Configuration
LOG_DIR = config.get("log_dir", f"{script_dir}/logs")
STDOUT_LOG_FILE = os.path.join(LOG_DIR, "stdout.log")
STDERR_LOG_FILE = os.path.join(LOG_DIR, "stderr.log")

# Debug options
DEBUG_PRINT = config.get("debug_print", False)

# Ensure Log Directory Exists
os.makedirs(LOG_DIR, exist_ok=True)

# Message Queue and Sent Messages Files
QUEUE_FILE = os.path.join(script_dir, "message_queue.json")
SENT_FILE  = os.path.join(script_dir, "message_sent.json")

# Ensure queue and sent message files exist
for file in [QUEUE_FILE, SENT_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump([], f, indent=4)

# Lock for thread-safe file access
queue_lock = threading.Lock()

app = FastAPI()

def validate_access_token(headers):
    """Validate the access token from headers."""
    access_token = headers.get("access_token")
    if access_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid access token")

def save_to_file(file, data):
    """Thread-safe write to JSON file."""
    with queue_lock:
        with open(file, "r+") as f:
            content = json.load(f)
            content.append(data)
            f.seek(0)
            json.dump(content, f, indent=4)

def remove_from_queue(message):
    """Thread-safe removal from queue."""
    with queue_lock:
        with open(QUEUE_FILE, "r+") as f:
            queue = json.load(f)
            queue = [msg for msg in queue if msg != message]
            f.seek(0)
            f.truncate()
            json.dump(queue, f, indent=4)

def send_email_alert(subject, body):
    """Send an email notification on repeated failures."""
    if EMAIL_CONFIG["enable"]:
        try:
            server = smtplib.SMTP(EMAIL_CONFIG["server"], EMAIL_CONFIG["port"])
            server.starttls()
            email_body = f"Subject: {subject}\n\n{body}"
            server.sendmail(EMAIL_CONFIG["sender"], EMAIL_CONFIG["recipient"], email_body)
            server.quit()
        except Exception as e:
            if DEBUG_PRINT:
                print("Failed to send email alert:", str(e))

def send_message(message):
    """Send message to the appropriate platform."""
    platform = message["platform"]
    if platform == "telegram":
        return send_to_telegram_api(message["body"])
    elif platform == "discord":
        return send_to_discord_api(message["body"])
    return False

def process_queue():
    """Background queue processor with retry logic."""
    while True:
        with queue_lock:
            with open(QUEUE_FILE, "r") as f:
                queue = json.load(f)

        for message in queue:
            retries = 0
            while retries < RETRY_CONFIG["send_retry_num"]:
                success = send_message(message)
                if success:
                    remove_from_queue(message)
                    save_to_file(SENT_FILE, message)
                    break
                retries += 1
                time.sleep(RETRY_CONFIG["send_retry_sleep"])

            if retries >= RETRY_CONFIG["send_retry_num"]:
                send_email_alert("Message Delivery Failed", f"Failed to send: {message}")
                time.sleep(RETRY_CONFIG["send_retry_wait"])

        time.sleep(5)  # Wait before checking the queue again

def print_debug_response(response):
    """Helper function to print the response content in the proper format."""
    if DEBUG_PRINT:
        try:
            # Try to parse response text as JSON
            json_response = response.json()
            print("Response (JSON):", json.dumps(json_response, indent=4))
        except ValueError:
            # If it's not JSON, print the raw text response
            print("Response (Text):", response.text)


def send_to_telegram_api(body):
    """Send formatted message to Telegram."""
    payload = {
        "chat_id": TELEGRAM_CONFIG["chat_id"],
        "disable_web_page_preview": True,
        "text": body,
        "parse_mode": "Markdown"
    }
    headers = {"Content-Type": "application/json"}
    tg_url = f"{TELEGRAM_CONFIG['api_url']}bot{TELEGRAM_CONFIG['api_key']}/sendMessage"

    response = requests.post(tg_url, json=payload, headers=headers)

    if DEBUG_PRINT:
        print("---------- Telegram Response: ----------")
        print("Status: ", response.status_code)
        print_debug_response(response)
        print("---------- Telegram Response: ----------")

    return response.status_code == 200

def send_to_discord_api(body):
    """Send formatted message to Discord."""
    payload = {"content": body}
    headers = {
        "Authorization": f"Bot {DISCORD_CONFIG['bot_token']}",
        "Content-Type": "application/json"
    }
    discord_url = f"{DISCORD_CONFIG['api_url']}/channels/{DISCORD_CONFIG['channel_id']}/messages"

    response = requests.post(discord_url, json=payload, headers=headers)

    if DEBUG_PRINT:
        print("---------- Discord Response: ----------")
        print("Status: ", response.status_code)
        print_debug_response(response)
        print("---------- Discord Response: ----------")

    return response.status_code == 200

def escape_text(text, platform=None):
    """
    Escape special characters in text based on the platform.

    - Telegram: Escapes Markdown characters that interfere with formatting.
    - Discord: No escaping needed (handles Markdown differently).
    - Default: Returns text unchanged if no platform is specified.
    """
    if not isinstance(text, str):
        return str(text)  # Ensure it's a string

    if platform == "telegram":
        escape_chars = r"_"
        return re.sub(r"([" + re.escape(escape_chars) + r"])", r"\\\1", text)

    return text  # No escaping for Discord or other platforms

def format_message(body, platform):
    """Format the message for the given platform."""
    raw_timestamp = body.get("timestamp")
    formatted_timestamp = (
        datetime.datetime.fromtimestamp(raw_timestamp / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if raw_timestamp
        else "N/A"
    )

    text_parts = [
        f"""{"**Site**"        if platform == "discord" else '*Site*'}:        {escape_text(body.get("Site",        "N/A"), platform)}""",
        f"""{"**Description**" if platform == "discord" else '*Description*'}: {escape_text(body.get("description", "N/A"), platform)}""",
        f"""{"**Controller**"  if platform == "discord" else '*Controller*'}:  {escape_text(body.get("Controller",  "N/A"), platform)}""",
        f"""{"**Timestamp**"   if platform == "discord" else '*Timestamp*'}:   {escape_text(formatted_timestamp, platform)}""",
    ]

    if "text" in body and isinstance(body["text"], list):
        text_parts.append("**Events:**" if platform == "discord" else "*Events:*")
        text_parts.extend(f"- {escape_text(line, platform)}" for line in body["text"])

    return "\n".join(text_parts)

@app.post("/webhook")
async def receive_webhook(request: Request):
    """Debug endpoint to print headers and body of incoming requests."""
    validate_access_token(request.headers)
    headers = dict(request.headers)
    body = await request.json()

    # Removing secret
    body.pop("shardSecret", None)

    # Log headers and body for debugging
    if DEBUG_PRINT:
        print("---------- Headers: ----------")
        print(json.dumps(headers, indent=4))
        print("---------- Headers: ----------")
        print("---------- Body: ----------")
        print(json.dumps(body,    indent=4))
        print("---------- Body: ----------")

    return {"status": "received"}

@app.post("/tg_msg")
async def queue_telegram(request: Request):
    """Receive and queue message for Telegram."""
    validate_access_token(request.headers)
    body = await request.json()

    # Removing secret
    body.pop("shardSecret", None)

    # Log the body for debugging if DEBUG_PRINT is enabled
    if DEBUG_PRINT:
        print("---------- Received Telegram Message: ----------")
        print(json.dumps(body, indent=4))
        print("---------- Received Telegram Message: ----------")

    message_text = format_message(body, "telegram")

    save_to_file(QUEUE_FILE, {"platform": "telegram", "body": message_text})
    return {"status": "queued"}

@app.post("/discord_msg")
async def queue_discord(request: Request):
    """Receive and queue message for Discord."""
    validate_access_token(request.headers)
    body = await request.json()

    # Removing secret
    body.pop("shardSecret", None)

    # Log the body for debugging if DEBUG_PRINT is enabled
    if DEBUG_PRINT:
        print("---------- Received Discord Message: ----------")
        print(json.dumps(body, indent=4))
        print("---------- Received Discord Message: ----------")

    message_text = format_message(body, "discord")

    save_to_file(QUEUE_FILE, {"platform": "discord", "body": message_text})

    return {"status": "queued"}

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Webhook server is running"}

# Start the background queue processor
queue_thread = threading.Thread(target=process_queue, daemon=True)
queue_thread.start()

def run_server(ip, port):
    """Run the server on the specified IP and port."""
    uvicorn.run(app, host=ip, port=port)

if __name__ == "__main__":
    if platform.system() == "Windows":
        print(f"Running in foreground on {FOREGROUND_IP}:{FOREGROUND_PORT} (Windows mode)")
        run_server(FOREGROUND_IP, FOREGROUND_PORT)
    else:
        if "--fg" in sys.argv:
            print(f"Running in foreground on {FOREGROUND_IP}:{FOREGROUND_PORT}")
            run_server(FOREGROUND_IP, FOREGROUND_PORT)
        else:
            # print(f"Running in background on {BACKGROUND_IP}:{BACKGROUND_PORT}")
            with DaemonContext(
                stdout=open(STDOUT_LOG_FILE, "a"),
                stderr=open(STDERR_LOG_FILE, "a")
            ):
                run_server(BACKGROUND_IP, BACKGROUND_PORT)
