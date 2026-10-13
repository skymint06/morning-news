#!/usr/bin/env python3
"""トピックスのJSONから、スマホの画面に収まる縦長の画像を1枚作る。

使い方: python make_image.py data/2026-10-12.json
出力:   output/2026-10-12.png          (LINEのトークに表示する画像)
        output/2026-10-12_preview.jpg  (LINEのプレビュー用の小さい画像)

文字の大きさは、1枚に収まる範囲でいちばん大きくなるよう自動調整する。
いちばん小さくしても収まらない場合はエラーで止まる(文章を短くして再実行する)。
"""
import io
import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import fitz
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Frame, Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
OUT_DIR = ROOT / "output"

# スマホの画面とほぼ同じ縦横比(9:19)。単位はポイント。
PAGE_W, PAGE_H = 360, 760
MARGIN = 16
HEADER_H = 62
FOOTER_H = 30
IMAGE_DPI = 216    # 横1080ピクセルになる
PREVIEW_DPI = 72

NAVY = colors.HexColor("#1f3a5f")
TEXT = colors.HexColor("#222222")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d9dee5")

CATEGORY_COLORS = {
    "政治": "#1f3a5f",
    "経済": "#2e7d5b",
    "社会": "#c2681c",
    "国際": "#6b4fa0",
    "スポーツ": "#c0392b",
    "科学": "#1b8a8f",
    "文化": "#b0447a",
    "気象": "#2f6fb5",
    "くらし": "#7a7a2e",
}
DEFAULT_CATEGORY_COLOR = "#5f6b7a"

# 大きい順に試し、最初に1枚へ収まった倍率を使う
SCALES = [s / 100 for s in range(130, 66, -3)]

WEEKDAYS = "月火水木金土日"
DISCLAIMER = [
    "AIがウェブ検索をもとに要約しています。",
    "正確な内容は各報道機関の記事でご確認ください。",
]


class Chip(Flowable):
    """ジャンル名を入れる角丸のラベル。"""

    def __init__(self, label, width, height, font_size):
        super().__init__()
        self.label = label
        self.width = width
        self.height = height
        self.font_size = font_size

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(colors.HexColor(CATEGORY_COLORS.get(self.label, DEFAULT_CATEGORY_COLOR)))
        c.roundRect(0, 0, self.width, self.height, self.height * 0.28, stroke=0, fill=1)
        size = self.font_size
        max_w = self.width - 5
        while pdfmetrics.stringWidth(self.label, "JP-Bold", size) > max_w and size > 4:
            size -= 0.25
        c.setFillColor(colors.white)
        c.setFont("JP-Bold", size)
        c.drawCentredString(self.width / 2, (self.height - size * 0.74) / 2, self.label)


def register_fonts():
    pdfmetrics.registerFont(TTFont("JP", str(FONT_DIR / "BIZUDPGothic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("JP-Bold", str(FONT_DIR / "BIZUDPGothic-Bold.ttf")))


def build_story(topics, scale, width):
    title_size = 12 * scale
    body_size = 10 * scale
    title_style = ParagraphStyle(
        "title", fontName="JP-Bold", fontSize=title_size, leading=title_size * 1.3,
        textColor=TEXT, wordWrap="CJK",
    )
    body_style = ParagraphStyle(
        "body", fontName="JP", fontSize=body_size, leading=body_size * 1.5,
        textColor=TEXT, wordWrap="CJK",
    )
    chip_w = 44 * scale
    chip_h = title_size * 1.3
    gap = 7 * scale
    pad = 6.5 * scale

    story = []
    for i, t in enumerate(topics):
        summary = escape(t["summary"])
        if t.get("source"):
            summary += f' <font color="#6b7280" size="{body_size * 0.85:.2f}">({escape(t["source"])})</font>'
        chip = Chip(t.get("category", "その他"), chip_w, chip_h, title_size * 0.78)
        # 1行目: ジャンル + 見出し / 2行目: 要約(横幅いっぱい)
        table = Table(
            [[chip, Paragraph(escape(t["title"]), title_style)],
             [Paragraph(summary, body_style), ""]],
            colWidths=[chip_w + gap, width - chip_w - gap],
        )
        style = [
            ("SPAN", (0, 1), (1, 1)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, 0), pad),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3 * scale),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), pad),
        ]
        if i < len(topics) - 1:
            style.append(("LINEBELOW", (0, 1), (-1, 1), 0.6, RULE))
        table.setStyle(TableStyle(style))
        story.append(table)
    return story


def fits(story, width, height):
    """story が1つの枠(=1枚)に全部入るかを、捨てキャンバスで試す。"""
    c = canvas.Canvas(io.BytesIO(), pagesize=(PAGE_W, PAGE_H))
    frame = Frame(0, 0, width, height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame.addFromList(story, c)
    return not story


def draw_header(c, day):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("JP-Bold", 21)
    c.drawString(MARGIN, PAGE_H - 30, "きのうの日本")
    c.setFont("JP", 11)
    label = f"{day.year}年{day.month}月{day.day}日({WEEKDAYS[day.weekday()]})の主なトピックス"
    c.drawString(MARGIN, PAGE_H - 49, label)


def draw_footer(c):
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(MARGIN, FOOTER_H, PAGE_W - MARGIN, FOOTER_H)
    c.setFillColor(MUTED)
    c.setFont("JP", 7.5)
    for i, line in enumerate(DISCLAIMER):
        c.drawString(MARGIN, FOOTER_H - 11 - i * 10, line)


def render_page(data):
    """1ページのPDFをメモリ上に作って返す(画像にするための中間データ)。"""
    day = date.fromisoformat(data["date"])
    topics = data["topics"]
    if not topics:
        sys.exit("エラー: topics が空です。")

    width = PAGE_W - 2 * MARGIN
    height = PAGE_H - HEADER_H - FOOTER_H - 4

    for scale in SCALES:
        if fits(build_story(topics, scale, width), width, height):
            break
    else:
        sys.exit("エラー: 1枚に収まりません。トピックの数を減らすか、要約を短くしてください。")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    # 画像にしたとき背景が透明にならないよう、白で塗っておく
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    draw_header(c, day)
    draw_footer(c)
    frame = Frame(MARGIN, FOOTER_H + 2, width, height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame.addFromList(build_story(topics, scale, width), c)
    c.save()
    return buffer.getvalue(), scale


def save_images(pdf_bytes, png_path, preview_path):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count != 1:
        sys.exit(f"エラー: {doc.page_count}ページに分かれてしまいました。")
    page = doc[0]
    page.get_pixmap(dpi=IMAGE_DPI).save(png_path)
    page.get_pixmap(dpi=PREVIEW_DPI).save(preview_path, jpg_quality=82)


def main():
    if len(sys.argv) != 2:
        sys.exit("使い方: python make_image.py data/YYYY-MM-DD.json")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    register_fonts()
    OUT_DIR.mkdir(exist_ok=True)
    png_path = OUT_DIR / f"{data['date']}.png"
    preview_path = OUT_DIR / f"{data['date']}_preview.jpg"
    pdf_bytes, scale = render_page(data)
    save_images(pdf_bytes, png_path, preview_path)
    print(f"作成しました(文字の倍率 {scale:.2f}、トピック {len(data['topics'])} 件)")
    for p in (png_path, preview_path):
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
