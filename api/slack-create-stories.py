"""
スケジューラ（cron / Vercel Cron 等）から呼び出し、
ストーリーズ用の「親メッセージ」を Slack に投稿する。

主な仕様:
  - ヘッダ X-Scheduler-Secret が .env の SCHEDULER_SECRET と一致しない場合は 401
  - 実行（POST）されたら都度投稿（時刻条件なし）
  - 投稿文は STORIES_PARENT_MESSAGE_TEMPLATE（未設定なら既定文）
  - POST ボディの "message" があればその文面で上書き可能

POST ボディ例:
  {}
  {"message": "今月のストーリーズ施策を進めます。"}

ローカルで `python api/slack-create-stories.py` を実行した場合:
  年月入力ポップアップを表示し、ストーリーズ管理シートの4行目以降の空白行へ
  納期項目（前半/後半のテキスト納期・予約投稿納期）を書き込む。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

# api/ から src を参照
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from dotenv import load_dotenv

    _env = _ROOT / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
except ImportError:
    pass

from slack_post_message import post_message

SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET")


def _stories_channel_id() -> str | None:
    """stories 投稿先: 専用チャンネルのみ使用。"""
    return (os.getenv("SLACK_HIRAKUMO_CHANNEL_ID") or "").strip() or None


def _apply_stories_env_overrides() -> None:
    """stories 用シート名を優先（未設定時は GOOGLE_SHEET_NAME のまま）。"""
    stories_sheet = os.getenv("GOOGLE_STORIES_SHEET_NAME")
    if stories_sheet:
        os.environ["GOOGLE_SHEET_NAME"] = stories_sheet


def _now_in_tz() -> datetime:
    tz_name = os.getenv("POST_QUEUE_TZ", "Asia/Tokyo")
    return datetime.now(ZoneInfo(tz_name))

def _next_month_dt(now_dt: datetime) -> datetime:
    if now_dt.month == 12:
        return now_dt.replace(year=now_dt.year + 1, month=1, day=1)
    return now_dt.replace(month=now_dt.month + 1, day=1)
    
def _monthly_message(target_dt: datetime, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()

    default_template = (
        "【{year}年{month}月 ストーリーズ】\n"
        "今月分の親スレッドです。各投稿案をこのスレッドに返信してください。"
    )
    template = os.getenv("STORIES_PARENT_MESSAGE_TEMPLATE", default_template)
    text = template.format(year=target_dt.year, month=target_dt.month)
    return text.replace("\\n", "\n")


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.do_POST()
        
    def do_POST(self):
        try:
            secret = self.headers.get("X-Scheduler-Secret")
            if not SCHEDULER_SECRET or secret != SCHEDULER_SECRET:
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"ok": False, "error": "unauthorized"}).encode("utf-8")
                )
                return

            if os.getenv("STORIES_ALREADY_POSTED") == "TRUE":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"ok": True, "posted": False, "reason": "already_posted"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8"))

            now_dt = _now_in_tz()
            target_dt = _next_month_dt(now_dt)
            message = _monthly_message(target_dt, override=data.get("message"))

            channel_id = _stories_channel_id()
            if not channel_id:
                raise ValueError("SLACK_HIRAKUMO_CHANNEL_ID が未設定です。")
            ok, err, ts = post_message(message, channel_id=channel_id)
            if not ok:
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"ok": False, "error": err or "slack_post_failed"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            payload = {
                "ok": True,
                "posted": True,
                "ts": ts,
                 "year": target_dt.year,
                 "month": target_dt.month,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"ok": False, "error": "invalid json"}).encode("utf-8")
            )
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode(
                    "utf-8"
                )
            )


if __name__ == "__main__":
    print("This endpoint is intended for scheduler / Vercel Cron POST calls.")

