from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import requests

ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

project_root = Path(__file__).resolve().parent
data_dir = project_root / "data"

MORNING_AFFIRMATIONS_FILE = data_dir / "line_morning_affirmations.txt"
EVENING_AFFIRMATIONS_FILE = data_dir / "line_evening_affirmations.txt"

MORNING_HOUR_START = 4
MORNING_HOUR_END = 12


def send_text_message(text: str) -> tuple[bool, str | None]:
    if not ACCESS_TOKEN:
        err = "LINE_CHANNEL_ACCESS_TOKEN が未設定です"
        print(f"❌ エラー: {err}")
        return False, err

    if not USER_ID:
        err = "LINE_USER_ID が未設定です"
        print(f"❌ エラー: {err}")
        return False, err

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    data = {
        "to": USER_ID,
        "messages": [
            {
                "type": "text",
                "text": text,
            }
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
    except requests.RequestException as e:
        err = f"通信エラー: {e}"
        print(f"❌ エラー: {err}")
        return False, err

    print(response.status_code)
    print(response.text)

    if response.ok:
        return True, None

    err = f"HTTP {response.status_code}: {response.text}"
    print(f"❌ エラー: {err}")
    return False, err


def affirmations_path_for_local_time(now: datetime | None = None) -> tuple[Path, str]:
    now = now or datetime.now()
    h = now.hour
    if MORNING_HOUR_START <= h < MORNING_HOUR_END:
        return MORNING_AFFIRMATIONS_FILE, "朝用"
    return EVENING_AFFIRMATIONS_FILE, "夜用"


def load_messages(path: Path) -> list[str]:
    if not path.is_file():
        print(f"❌ エラー: メッセージファイルがありません: {path}")
        return []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"❌ エラー: ファイルを読めません: {e}")
        return []

    lines = [ln.strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="朝用・夜用アファメーションをランダム1通、LINEに送信"
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--morning", "-m", action="store_true", help="朝用を送る")
    g.add_argument("--evening", "-e", action="store_true", help="夜用を送る")
    args = parser.parse_args()

    if args.morning:
        path, label = MORNING_AFFIRMATIONS_FILE, "朝用"
    elif args.evening:
        path, label = EVENING_AFFIRMATIONS_FILE, "夜用"
    else:
        path, label = affirmations_path_for_local_time()

    messages = load_messages(path)
    if not messages:
        print(f"❌ エラー: {label}アファメーションがありません")
        sys.exit(1)

    text = random.choice(messages)
    ok, _err = send_text_message(text)

    if ok:
        print(f"✅ {label}アファメーションを送信しました: {text!r}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
