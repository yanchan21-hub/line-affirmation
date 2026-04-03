"""
朝用・夜用アファメーションをそれぞれの txt から 1 通ランダムに選び、LINE Push で送信します。

- data/line_morning_affirmations.txt … 朝用（1 行 1 通、空行は無視）
- data/line_evening_affirmations.txt … 夜用（同上）

既定では PC のローカル時刻でリストを選びます。
  ・朝用: 4:00 ～ 11:59（この時間帯は「私は今日…」の朝リスト）
  ・夜用: 上記以外（正午～深夜～早朝まで「私は今日も一歩…」の夜リスト）

【前提】.env に LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID（既存の line_send_message と同じ）

実行:
    python -m src.line_send_fixed_message                # 時刻で自動
    python -m src.line_send_fixed_message --morning      # 朝用を強制
    python -m src.line_send_fixed_message --evening      # 夜用を強制
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.line_send_message import send_text_message

MORNING_AFFIRMATIONS_FILE = project_root / "data" / "line_morning_affirmations.txt"
EVENING_AFFIRMATIONS_FILE = project_root / "data" / "line_evening_affirmations.txt"

# 朝枠の開始・終了（時）。終了は「未満」なので 12 なら 11:59 までが朝。
MORNING_HOUR_START = 4
MORNING_HOUR_END = 12


def affirmations_path_for_local_time(now: datetime | None = None) -> tuple[Path, str]:
    """ローカル時刻に応じて (読むパス, 表示ラベル) を返す。"""
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
        description="朝用・夜用アファメーションをランダム 1 通、LINE に送信（既定は時刻で自動選択）",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--morning",
        "-m",
        action="store_true",
        help="朝用リストを送る（時刻に関係なく強制）",
    )
    g.add_argument(
        "--evening",
        "-e",
        action="store_true",
        help="夜用リストを送る（時刻に関係なく強制）",
    )
    args = parser.parse_args()

    if args.morning:
        path, label = MORNING_AFFIRMATIONS_FILE, "朝用"
    elif args.evening:
        path, label = EVENING_AFFIRMATIONS_FILE, "夜用"
    else:
        path, label = affirmations_path_for_local_time()

    messages = load_messages(path)
    if not messages:
        print(f"❌ エラー: {label}アファメーションがありません（1 行以上、txt に入力してください）")
        sys.exit(1)
    text = random.choice(messages)
    ok, _err = send_text_message(text)
    if ok:
        print(f"{label}アファメーションを送信しました: {text!r}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
