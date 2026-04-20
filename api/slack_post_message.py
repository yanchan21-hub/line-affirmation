"""
Slackメッセージ送信プログラム
Bot Tokenを使用してSlackチャンネルにメッセージを送信します。

【設定方法】
1. Slack API (https://api.slack.com/apps) でアプリを作成
2. Bot Token Scopes に chat:write を追加
3. アプリをワークスペースにインストール
4. .env に以下を設定:
   SLACK_BOT_TOKEN=xoxb-xxxxx
   SLACK_CHANNEL_ID=C0xxxxx  （チャンネルID、例: #general のID）
"""
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    import requests
except ImportError:
    print("=" * 60)
    print("❌ エラー: requests がインストールされていません")
    print("=" * 60)
    print("\n  python -m pip install requests")
    print("=" * 60)
    sys.exit(1)

# .envファイルの読み込み
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    pass


def _show_popup(title: str, message: str, is_error: bool = False) -> None:
    """ポップアップ通知を表示（Windows）"""
    icon = 0x10 if is_error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, icon)
        except Exception:
            print(f"{title}: {message}")
    else:
        print(f"{title}: {message}")


def post_message(
    text: str,
    channel_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    thread_ts: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Slackチャンネルにメッセージを送信する

    Args:
        text: 送信するメッセージ本文
        channel_id: チャンネルID（省略時は .env の SLACK_CHANNEL_ID を使用）
        bot_token: Bot Token（省略時は .env の SLACK_BOT_TOKEN を使用）
        thread_ts: スレッドのタイムスタンプ（指定するとスレッドに返信）

    Returns:
        (成功, エラーメッセージ or None, chat.postMessage の ts or None)
    """
    token = bot_token or os.getenv("SLACK_BOT_TOKEN")
    channel = channel_id or os.getenv("SLACK_CHANNEL_ID")

    if not token:
        err = "SLACK_BOT_TOKEN が設定されていません（.env を確認してください）"
        print(f"❌ エラー: {err}")
        return False, err, None

    if not channel:
        err = "SLACK_CHANNEL_ID が設定されていません（.env を確認してください）"
        print(f"❌ エラー: {err}")
        return False, err, None

    if not text:
        err = "送信するメッセージ本文を指定してください"
        print(f"❌ エラー: {err}")
        return False, err, None

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "channel": channel,
        "text": text,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    response = requests.post(url, headers=headers, json=payload, timeout=10)

    if not response.ok:
        err = f"HTTP {response.status_code} - {response.text}"
        print(f"❌ エラー: {err}")
        return False, err, None

    data = response.json()
    if not data.get("ok"):
        err = data.get("error", "不明なエラー")
        print(f"❌ エラー: {err}")
        return False, err, None

    return True, None, data.get("ts")


def main():
    """コマンドラインから実行する場合のエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description="Slackにメッセージを送信")
    parser.add_argument("message", nargs="?", help="送信するメッセージ（省略時は入力モード）")
    parser.add_argument("-c", "--channel", help="チャンネルID（省略時は .env の SLACK_CHANNEL_ID）")
    parser.add_argument("-t", "--thread", help="スレッドのタイムスタンプ（スレッドに返信する場合）")
    parser.add_argument("-i", "--interactive", action="store_true", help="入力モードで起動（複数行可、空行で送信）")
    args = parser.parse_args()

    message = args.message
    if not message or args.interactive:
        print("--- Slackメッセージ送信 ---")
        print("送信するテキストを入力してください")
        print("  （複数行可・空行で送信・Windows: Ctrl+Z→Enter で終了）")
        print("-" * 40)
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line and lines:
                break
            if not line:
                continue
            lines.append(line)
        message = "\n".join(lines).strip() if lines else ""

    if not message:
        _show_popup("Slack エラー", "❌ メッセージが入力されていません", is_error=True)
        sys.exit(1)

    success, error_msg, _ts = post_message(message, channel_id=args.channel, thread_ts=args.thread)
    if success:
        _show_popup("Slack", "✅ メッセージを送信しました")
    else:
        _show_popup("Slack エラー", f"❌ {error_msg}", is_error=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
