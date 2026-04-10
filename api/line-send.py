import os
import json
import random
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_TO_USER_ID = os.getenv("LINE_TO_USER_ID")
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET")

def load_messages(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

MORNING_MESSAGES = load_messages("data/line_evening_affirmations.txt")
NIGHT_MESSAGES = load_messages("data/line_morning_affirmations.txt")

recent_morning_messages = []
recent_night_messages = []

RECENT_LIMIT = 3


def pick_message_from_pool(messages, recent_list):
    candidates = [m for m in messages if m not in recent_list]

    if not candidates:
        recent_list.clear()
        candidates = messages[:]

    message = random.choice(candidates)
    recent_list.append(message)

    if len(recent_list) > RECENT_LIMIT:
        recent_list.pop(0)

    return message


def pick_message(job_type: str) -> str:
    if job_type == "morning":
        return pick_message_from_pool(MORNING_MESSAGES, recent_morning_messages)
    if job_type == "night":
        return pick_message_from_pool(NIGHT_MESSAGES, recent_night_messages)
    raise ValueError("invalid jobType")


def push_line_message(text: str):
    url = "https://api.line.me/v2/bot/message/push"
    payload = {
        "to": LINE_TO_USER_ID,
        "messages": [{"type": "text", "text": text}],
    }
    body = json.dumps(payload).encode("utf-8")

    req = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            secret = self.headers.get("X-Scheduler-Secret")
            if secret != SCHEDULER_SECRET:
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "unauthorized"}).encode("utf-8"))
                return

            if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_TO_USER_ID or not SCHEDULER_SECRET:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "missing env vars"}).encode("utf-8"))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            data = json.loads(raw_body.decode("utf-8"))

            job_type = data.get("jobType")
            message = pick_message(job_type)

            push_line_message(message)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"ok": True, "jobType": job_type, "message": message},
                    ensure_ascii=False
                ).encode("utf-8")
            )

        except ValueError as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))

        except HTTPError as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"ok": False, "error": "LINE API error", "status": e.code}
                ).encode("utf-8")
            )

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
