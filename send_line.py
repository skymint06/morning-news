#!/usr/bin/env python3
"""LINE公式アカウントから、自分あてにメッセージを送る。

必要な設定(環境変数、または同じフォルダの .env ファイル):
    LINE_CHANNEL_ACCESS_TOKEN  チャネルアクセストークン(長期)
    LINE_USER_ID               あなたのユーザーID(Uで始まる)

使い方:
    python send_line.py --text "テストです"
    python send_line.py --image-url https://.../2026-10-12.png \
        --preview-url https://.../2026-10-12_preview.jpg \
        --text "10月12日のまとめです\nPDF: https://.../2026-10-12.pdf"

画像と文章を同時に指定しても、1回の送信(1通)として数えられる。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.line.me/v2/bot/message/push"
ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text")
    parser.add_argument("--image-url")
    parser.add_argument("--preview-url")
    args = parser.parse_args()

    load_env_file()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        sys.exit("エラー: LINE_CHANNEL_ACCESS_TOKEN と LINE_USER_ID が設定されていません。")

    messages = []
    if args.image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": args.image_url,
            "previewImageUrl": args.preview_url or args.image_url,
        })
    if args.text:
        messages.append({"type": "text", "text": args.text.replace("\\n", "\n")})
    if not messages:
        sys.exit("エラー: --text か --image-url のどちらかを指定してください。")

    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"to": user_id, "messages": messages}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"送信しました(HTTP {response.status})")
    except urllib.error.HTTPError as e:
        sys.exit(f"エラー: 送信に失敗しました(HTTP {e.code}) {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"エラー: LINEのサーバーに接続できませんでした: {e.reason}")


if __name__ == "__main__":
    main()
