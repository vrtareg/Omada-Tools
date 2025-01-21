import datetime
import json
import os
import platform
import sys
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request

if platform.system() != "Windows":
    from daemon import DaemonContext  # Only available on Unix-like systems

# Define global script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

def load_config(config_file):
    """Load configuration from the specified JSON file."""
    with open(config_file, "r") as f:
        return json.load(f)

# Load configuration
config = load_config(f"{script_dir}/config.json")

# Telegram and Webhook Configuration
TELEGRAM_API_URL = config.get("telegram_api_url")
TELEGRAM_API_KEY = config.get("telegram_api_key")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id")
WEBHOOK_SECRET = config.get("webhook_secret")

# Network Configuration
FOREGROUND_IP = config.get("foreground_ip", "127.0.0.1")
FOREGROUND_PORT = config.get("foreground_port", 8000)
BACKGROUND_IP = config.get("background_ip", "0.0.0.0")
BACKGROUND_PORT = config.get("background_port", 8080)

# Log Files
LOG_DIR = config.get("log_dir", f"{script_dir}/logs")
STDOUT_LOG_FILE = os.path.join(LOG_DIR, "stdout.log")
STDERR_LOG_FILE = os.path.join(LOG_DIR, "stderr.log")

# Debug options
DEBUG_PRINT = config.get("debug_print", False)

# Ensure the log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

app = FastAPI()

def validate_access_token(headers):
    """Validate the access token from headers."""
    access_token = headers.get("access_token")
    if access_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid access token")

@app.post("/webhook")
async def receive_webhook(request: Request):
    """Debug endpoint to print headers and body of incoming requests."""
    validate_access_token(request.headers)
    headers = dict(request.headers)
    body = await request.json()

    # Log headers and body for debugging
    print("Headers:", headers)
    print("Body:", body)

    return {"status": "received"}

@app.post("/tg_msg")
async def send_to_telegram(request: Request):
    """Endpoint to process Omada messages and send them to Telegram."""
    validate_access_token(request.headers)
    body = await request.json()

    # Log the body for debugging if DEBUG_PRINT is enabled
    if DEBUG_PRINT:
        print("Body:", json.dumps(body, indent=4))

    # Remove the 'shardSecret' field if it exists
    body.pop("shardSecret", None)

    # Decode the timestamp to a human-readable format
    raw_timestamp = body.get("timestamp")
    formatted_timestamp = (
        datetime.datetime.fromtimestamp(raw_timestamp / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if raw_timestamp
        else "N/A"
    )

    # Prepare the message text
    text_parts = [
        f"*Site*: {body.get('Site')}",
        f"*Description*: {body.get('description')}",
        f"*Controller*: {body.get('Controller')}",
        f"*Timestamp*: {formatted_timestamp}",
    ]

    # Add multiline "text" entries to the message
    if "text" in body and isinstance(body["text"], list):
        text_parts.append("*Events:*")
        text_parts.extend(f"- {line}" for line in body["text"])

    # Join all parts with newlines
    message_text = "\n".join(text_parts)

    # Log the message text for debugging if DEBUG_PRINT is enabled
    if DEBUG_PRINT:
        print("Message:", message_text)

    # Construct the Telegram API endpoint
    tg_url = f"{TELEGRAM_API_URL}bot{TELEGRAM_API_KEY}/sendMessage"

    # Prepare payload and headers
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "disable_web_page_preview": True,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Send the message to Telegram
    response = requests.post(tg_url, json=payload, headers=headers)

    # Log Telegram API response if DEBUG_PRINT is enabled
    if DEBUG_PRINT:
        print("Telegram API Response:", response.status_code, response.text)

    return {"status": "sent", "telegram_response": response.json()}

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Webhook server is running"}

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
