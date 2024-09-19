import requests
import json
import os
import time
import subprocess
from systemd import journal
from systemd.daemon import notify

# Load the bot token and admin IDs from files
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_files", "ids.txt")) as f:
    lines = f.read().splitlines()
    BASE_URL = f"https://api.telegram.org/bot{lines[0]}/"
    ADMIN_IDS = lines[1:]

WHITELIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_files", "whitelist.txt")

try:
    with open(WHITELIST_FILE, "x") as file:
        admin_list = [{"id": admin_id, "name": "Admin", "username": "Admin"} for admin_id in ADMIN_IDS]
        json.dump(admin_list, file, indent=4)
        WHITE_LIST = admin_list.copy()
except FileExistsError:
    with open(WHITELIST_FILE, "r") as file:
        WHITE_LIST = json.load(file)

# Dictionary to store message IDs for each admin and user combination
admin_message_ids = {}

# Dictionary to store user info (id, first name, username) when access is requested
user_info_dict = {}

### HELPERS ##################################################################################################################

def is_user_in_whitelist(user_id):
    return any(str(user["id"]) == str(user_id) for user in WHITE_LIST)

### API ##################################################################################################################

def get_updates(offset=None):
    url = BASE_URL + "getUpdates"
    params = {"timeout": 60, "offset": offset}
    response = requests.get(url, params=params)
    return response.json()

def send_message(chat_id, text, reply_markup=None):
    url = BASE_URL + "sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": json.dumps(reply_markup) if reply_markup else None
    }
    response = requests.post(url, data=payload)
    return response.json()

def edit_message_reply_markup(chat_id, message_id, reply_markup=None):
    url = BASE_URL + "editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": json.dumps(reply_markup) if reply_markup else None
    }
    response = requests.post(url, data=payload)
    return response.json()

def reply_to_message(chat_id, text, message_id, reply_markup=None):
    url = BASE_URL + "sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_to_message_id": message_id,
        "reply_markup": json.dumps(reply_markup) if reply_markup else None
    }
    response = requests.post(url, data=payload)
    return response.json()

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    url = BASE_URL + "answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": show_alert
    }
    response = requests.post(url, data=payload)
    return response.json()

### HANDLER MESSAGE ##################################################################################################################

# Process messages from the bot
def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message["text"]
    message_id = message["message_id"]  # The ID of the message to reply to

    if text == "/start":
        if is_user_in_whitelist(chat_id):
            send_message(chat_id, "sup", {"keyboard": [["open"]]})
        else:
            journal.send(f"start cmd by {chat_id} {message['from']['first_name']}")
            send_message(chat_id, "Click register to submit request", {"keyboard": [["register"]]})

    elif text == "register":
        if is_user_in_whitelist(chat_id):
            send_message(chat_id, "already", {"keyboard": [["open"]]})
        else:
            user_first_name = message["from"]["first_name"]
            user_username = message["from"]["username"]

            request_message = (
                f"New Request from \n"
                f"Name: {user_first_name}\n"
                f"Username: {user_username}\n"
                f"ID: {chat_id}"
            )

            user_info_dict[str(chat_id)] = {"first_name": user_first_name, "username": user_username}

            # Send inline keyboard to admins and store the message ID for each admin and user combination
            buttons = [
                [{"text": "Allow", "callback_data": f"allow {chat_id}"}],
                [{"text": "Deny", "callback_data": f"deny {chat_id}"}]
            ]
            for admin_id in ADMIN_IDS:
                response = send_message(admin_id, request_message, {"inline_keyboard": buttons})
    
                # Store the message ID with a key format of admin_id_user_id
                admin_message_ids[f"{admin_id}_{chat_id}"] = response["result"]["message_id"]

    elif text == "open":
        if is_user_in_whitelist(chat_id):
            reply_to_message(chat_id, "👋️. Door is open!", message_id, {"keyboard": [["open"]]})
            subprocess.run(["raspi-gpio", "set", "15", "dh"])
            
            # Notify admins if the user is not one of the admins
            if str(chat_id) not in ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    send_message(admin_id, f"You have a guest {message['from']['first_name']}", {"keyboard": [["open"]]})

            time.sleep(7)
            subprocess.run(["raspi-gpio", "set", "15", "dl"])
            journal.send(f"Opened by {message['from']['first_name']}")
        else:
            reply_to_message(chat_id, "✋️ not registered", message_id, {"keyboard": [["register"]]})
            journal.send(f"TRIED TO OPEN by {message['from']['first_name']}")

    else:
        if is_user_in_whitelist(chat_id):
            send_message(chat_id, "?", {"keyboard": [["open"]]})
        else:
            send_message(chat_id, "Click register to submit request", {"keyboard": [["register"]]})

### CALLBACK ##################################################################################################################

# Handle callback queries from inline keyboards
def handle_callback_query(callback_query):
    data = callback_query["data"].split()
    action = data[0]
    user_id = data[1]

    if action == "allow":
        if str(user_id) in user_info_dict:
            user = {
                "id": user_id,
                "name": user_info_dict[user_id]["first_name"],
                "username": user_info_dict[user_id]["username"]
            }
            WHITE_LIST.append(user)
            
            with open(WHITELIST_FILE, "w") as file:
                json.dump(WHITE_LIST, file, indent=4)

            for admin_id in ADMIN_IDS:
                send_message(admin_id, f"Allowed {user_id}", {"keyboard": [["open"]]})

            send_message(user_id, "welcome", {"keyboard": [["open"]]})
            journal.send(f"Added {user_id} to whitelist")
        else:
            journal.send(f"User {user_id} not found in user_info_dict")

    # Handle the "Deny" action
    elif action == "deny":
        for admin_id in ADMIN_IDS:
            send_message(admin_id, f"Denied {user_id}", {"keyboard": [["open"]]})
        send_message(user_id, "denied", {"keyboard": [["register"]]})
        journal.send(f"Denied {user_id}")

    # Remove inline keyboard for all admin messages related to this specific user
    for admin_id in ADMIN_IDS:
        key = f"{admin_id}_{user_id}"
        if key in admin_message_ids:
            message_id = admin_message_ids[key]  # Use the stored message ID for this admin and user
            edit_message_reply_markup(admin_id, message_id, reply_markup=None)
            del admin_message_ids[key]

    # Clear the user info for this user
    if user_id in user_info_dict:
        del user_info_dict[user_id]

    # Acknowledge the callback query
    answer_callback_query(callback_query["id"])

### MAIN ##################################################################################################################

def main():
    journal.send("Bot starting...")

    subprocess.run(["raspi-gpio", "set", "15", "op"])
    subprocess.run(["raspi-gpio", "set", "15", "dl"])

    send_message(ADMIN_IDS[0], "Bot has restarted")

    watchdog_interval = 600
    notify("WATCHDOG=1")
    last_watchdog_time = time.time()

    offset = None
    journal.send("!!bot ready!!")
    while True:

        #pulling
        updates = get_updates(offset)
        if updates["result"]:
            for update in updates["result"]:
                offset = update["update_id"] + 1
                if "message" in update:
                    try:
                        handle_message(update["message"])
                    except Exception as e:
                        journal.send(f"ERROR IN MESSAGE HANGLER: {e}")
                elif "callback_query" in update:
                    handle_callback_query(update["callback_query"])

        #watchdog
        if time.time() - last_watchdog_time >= watchdog_interval:
            journal.send("pik")
            notify("WATCHDOG=1")
            last_watchdog_time = time.time()

        time.sleep(1)

if __name__ == "__main__":
    main()
