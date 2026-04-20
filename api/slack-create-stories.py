from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

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

from api.slack_post_message import post_message


# ========= 環境変数 =========
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
GOOGLE_STORIES_SHEET_NAME = os.getenv("GOOGLE_STORIES_SHEET_NAME", "Instagram ストーリーズ管理シート").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()

READ_RANGE = "A:I"


def _stories_channel_id() -> str | None:
    return (os.getenv("SLACK_HIRAKUMO_CHANNEL_ID") or "").strip() or None


def _now_in_tz() -> datetime:
    tz_name = os.getenv("POST_QUEUE_TZ", "Asia/Tokyo")
    return datetime.now(ZoneInfo(tz_name))


def _next_month_dt(now_dt: datetime) -> datetime:
    if now_dt.month == 12:
        return now_dt.replace(year=now_dt.year + 1, month=1, day=1)
    return now_dt.replace(month=now_dt.month + 1, day=1)


def _format_mmdd(dt: datetime) -> str:
    return dt.strftime("%m/%d")


def _calc_deadlines(target_dt: datetime):
    """
    あなたの今の運用例に合わせて、翌月の納期を自動作成
    前半テキスト納期: 前月25日
    前半予約投稿納期: 前月28日
    後半テキスト納期: 当月10日
    後半予約投稿納期: 当月13日
    """
    year = target_dt.year
    month = target_dt.month

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    first_text = datetime(prev_year, prev_month, 25)
    first_reserve = datetime(prev_year, prev_month, 28)
    second_text = datetime(year, month, 10)
    second_reserve = datetime(year, month, 13)

    return (
        _format_mmdd(first_text),
        _format_mmdd(first_reserve),
        _format_mmdd(second_text),
        _format_mmdd(second_reserve),
    )


def _monthly_message(
    target_dt: datetime,
    first_text_deadline: str = "",
    first_reserve_deadline: str = "",
    second_text_deadline: str = "",
    second_reserve_deadline: str = "",
    note: str = "",
    override: str | None = None,
) -> str:
    if override and override.strip():
        return override.strip()

    default_template = (
        "【{year}年{month}月 ストーリーズ制作用】\n\n"
        "■前半テキスト納期：{first_text_deadline}\n"
        "■前半予約投稿納期：{first_reserve_deadline}\n"
        "■後半テキスト納期：{second_text_deadline}\n"
        "■後半予約投稿納期：{second_reserve_deadline}\n\n"
        "火曜日以外を配信対象として、前半・後半に分けて作成してください。\n"
        "{note_block}"
        "このスレッドで進行してください。"
    )

    template = os.getenv("STORIES_PARENT_MESSAGE_TEMPLATE", default_template)
    note_block = f"備考：{note}\n" if note.strip() else ""

    text = template.format(
        year=target_dt.year,
        month=target_dt.month,
        first_text_deadline=first_text_deadline or "未設定",
        first_reserve_deadline=first_reserve_deadline or "未設定",
        second_text_deadline=second_text_deadline or "未設定",
        second_reserve_deadline=second_reserve_deadline or "未設定",
        note_block=note_block,
    )
    return text.replace("\\n", "\n")


def _build_sheets_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON が未設定です。")
    if not GOOGLE_SHEETS_ID:
        raise ValueError("GOOGLE_SHEETS_ID が未設定です。")

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials)


def _read_story_rows():
    service = _build_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=GOOGLE_SHEETS_ID,
            range=f"{GOOGLE_STORIES_SHEET_NAME}!{READ_RANGE}",
        )
        .execute()
    )
    return result.get("values", [])


def _safe_cell(row: list[str], index: int) -> str:
    return row[index].strip() if len(row) > index and row[index] else ""


def _find_target_row(rows: list[list[str]], target_dt: datetime):
    for idx, row in enumerate(rows, start=1):
        if not row:
            continue

        year_text = _safe_cell(row, 0)
        month_text = _safe_cell(row, 1)

        try:
            year_value = int(float(year_text)) if year_text else None
            month_value = int(float(month_text)) if month_text else None
        except ValueError:
            continue

        if year_value == target_dt.year and month_value == target_dt.month:
            return idx, row

    return None, None


def _is_already_posted(row: list[str]) -> bool:
    slack_ts = _safe_cell(row, 7)       # H列
    posted_date = _safe_cell(row, 8)    # I列
    return bool(slack_ts or posted_date)


def _append_new_month_row(target_dt: datetime):
    service = _build_sheets_service()

    first_text, first_reserve, second_text, second_reserve = _calc_deadlines(target_dt)

    body = {
        "values": [[
            str(target_dt.year),   # A 年
            str(target_dt.month),  # B 月
            first_text,            # C 前半テキスト納期
            first_reserve,         # D 前半予約投稿納期
            second_text,           # E 後半テキスト納期
            second_reserve,        # F 後半予約投稿納期
            "",                    # G 備考
            "",                    # H Slack親TS
            "",                    # I Slack投稿済み
        ]]
    }

    (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=GOOGLE_SHEETS_ID,
            range=f"{GOOGLE_STORIES_SHEET_NAME}!A:I",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )


def _update_post_result(sheet_row_number: int, ts: str, posted_date_str: str):
    service = _build_sheets_service()
    body = {"values": [[ts, posted_date_str]]}

    (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=GOOGLE_SHEETS_ID,
            range=f"{GOOGLE_STORIES_SHEET_NAME}!H{sheet_row_number}:I{sheet_row_number}",
            valueInputOption="RAW",
            body=body,
        )
        .execute()
    )


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def _handle_request(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8"))

            now_dt = _now_in_tz()
            target_dt = _next_month_dt(now_dt)

            rows = _read_story_rows()
            sheet_row_number, target_row = _find_target_row(rows, target_dt)

            # なければ自動で作る
            if not sheet_row_number or not target_row:
                _append_new_month_row(target_dt)
                rows = _read_story_rows()
                sheet_row_number, target_row = _find_target_row(rows, target_dt)

            if not sheet_row_number or not target_row:
                raise ValueError(f"{target_dt.year}年{target_dt.month}月 の行を自動作成できませんでした。")

            if _is_already_posted(target_row):
                payload = {
                    "ok": True,
                    "posted": False,
                    "reason": "already_posted",
                    "year": target_dt.year,
                    "month": target_dt.month,
                    "sheet_row": sheet_row_number,
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return

            first_text_deadline = _safe_cell(target_row, 2)
            first_reserve_deadline = _safe_cell(target_row, 3)
            second_text_deadline = _safe_cell(target_row, 4)
            second_reserve_deadline = _safe_cell(target_row, 5)
            note = _safe_cell(target_row, 6)

            message = _monthly_message(
                target_dt=target_dt,
                first_text_deadline=first_text_deadline,
                first_reserve_deadline=first_reserve_deadline,
                second_text_deadline=second_text_deadline,
                second_reserve_deadline=second_reserve_deadline,
                note=note,
                override=data.get("message"),
            )

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

            posted_date_str = now_dt.strftime("%Y/%m/%d")
            _update_post_result(sheet_row_number, ts, posted_date_str)

            payload = {
                "ok": True,
                "posted": True,
                "ts": ts,
                "year": target_dt.year,
                "month": target_dt.month,
                "sheet_row": sheet_row_number,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "invalid json"}).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8")
            )


if __name__ == "__main__":
    print("This endpoint is intended for scheduler / Vercel Cron calls.")
