#!/usr/bin/env python3
"""LINE公式アカウントから、自分あてにメッセージを送る。

必要な設定(環境変数、または同じフォルダの .env ファイル):
    LINE_USER_ID               あなたのユーザーID(Uで始まる)
    LINE_CHANNEL_ACCESS_TOKEN  チャネルアクセストークン(長期)

クラウドで動かすときは、トークンを環境変数に入れない。クラウド環境の
「ネットワークシークレット」に登録しておくと、api.line.me への通信にだけ
自動で付与される。その場合このプログラムはトークンなしで送信する。

使い方:
    python send_line.py --text "テストです"
    python send_line.py --text "10月12日のトピックスです" \
        --image-url https://.../2026-10-12_1.png --preview-url https://.../2026-10-12_1_preview.jpg \
        --image-url https://.../2026-10-12_2.png --preview-url https://.../2026-10-12_2_preview.jpg

--image-url と --preview-url は、画像の枚数ぶん同じ順番で並べる。
文章と画像を合わせて5つまで同時に送れ、まとめて1回の送信(1通)として数えられる。
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
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--preview-url", action="append", default=[])
    args = parser.parse_args()

    load_env_file()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not user_id:
        sys.exit("エラー: LINE_USER_ID が設定されていません。")

    if args.preview_url and len(args.preview_url) != len(args.image_url):
        sys.exit("エラー: --preview-url は --image-url と同じ数だけ指定してください。")

    # トークでは上から順に表示されるので、文章を先、画像をページ順に並べる
    messages = []
    if args.text:
        messages.append({"type": "text", "text": args.text.replace("\\n", "\n")})
    previews = args.preview_url or args.image_url
    for image_url, preview_url in zip(args.image_url, previews):
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": preview_url,
        })
    if not messages:
        sys.exit("エラー: --text か --image-url のどちらかを指定してください。")
    if len(messages) > 5:
        sys.exit("エラー: 一度に送れるのは、文章と画像を合わせて5つまでです。")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("トークンは未設定のため付けずに送ります(クラウド側で付与される想定)。")
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"to": user_id, "messages": messages}).encode("utf-8"),
        headers=headers,
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
