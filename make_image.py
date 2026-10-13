#!/usr/bin/env python3
"""トピックスのJSONから、スマホの画面に収まる縦長の画像を作る。

ニュースのトピックス、ものづくり業界の市況まとめ、企業ウォッチの3種類(それぞれ最大2枚)。

使い方: python make_image.py data/2026-10-12.json
出力:   output/2026-10-12_1.png, ..._2.png                    (ニュース)
        output/2026-10-12_industry_1.png, ..._industry_2.png  (業界の市況。JSONに industry があるとき)
        output/2026-10-12_company_1.png, ..._company_2.png    (企業ウォッチ。JSONに companies があるとき)
        それぞれに ..._preview.jpg                             (LINEのプレビュー用の小さい画像)

JSONの topics の各トピックに書けるもの(ニュース):
    category  ジャンル名(政治・経済・社会・国際・スポーツ・科学・文化・気象・くらし)
    title     見出し
    summary   何が起きたか
    explain   どういうことかの、やさしい解説(省略可)
    icon      イラストにする絵文字1つ(省略可。例: "⚾")
    source    情報源の名前(省略可)

JSONの industry に書けるもの(業界の市況まとめ):
    overview  全体のポイント(省略可)
    sectors   業界ごとの欄のリスト。1件に書けるもの:
        name      業界名(例: "半導体")
        icon      イラストにする絵文字1つ(省略可)
        trend     "up"(上向き) / "flat"(横ばい) / "down"(下向き)
        headline  ひとことで言うとどういう状況か
        now       現状: 生産・受注・価格などの数字の箇条書き
        focus     注目: 会社名・製品名・鋼種など、具体的な動きの箇条書き
        outlook   今後: 予測や計画など、これからの見通しの箇条書き
        source    情報源の名前(省略可)
      箇条書きの1つ1つは、文字列か {"text": "...", "new": true}
      (new を付けると、新しく出た情報として NEW の印が付く)

JSONの companies に書けるもの(企業ウォッチ)。企業ごとの欄のリストで、1件に書けるもの:
    name     会社名
    about    何の会社か(事業内容、所在地、主な取引先など)を1行で
    trend    "up" / "flat" / "down"(省略可。業績などから判断できるときだけ付ける)
    news     近況: 決算、受注、新工場、値上げなど、その会社の最近の動き
    market   関連: その会社に関係する市場や取引先の動き
    outlook  今後: 業績予想、計画、次の決算発表日など
    source   情報源の名前(省略可)
  新しい情報が見つからなかった会社は、news にその旨を1行書く。

どれも、1枚に読みやすい大きさで収まれば1枚、収まらなければ2枚に分ける。
文字の大きさは、収まる範囲でいちばん大きくなるよう自動調整する。
2枚にしても収まらない場合はエラーで止まる(文章を短くして再実行する)。
"""
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Frame, Image, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
ICON_DIR = ROOT / "icons"
OUT_DIR = ROOT / "output"

# スマホの画面とほぼ同じ縦横比(9:19)。単位はポイント。
PAGE_W, PAGE_H = 360, 760
MARGIN = 16
HEADER_H = 62
FOOTER_H = 30
CONTENT_W = PAGE_W - 2 * MARGIN
CONTENT_H = PAGE_H - HEADER_H - FOOTER_H - 14
IMAGE_DPI = 216    # 横1080ピクセルになる
PREVIEW_DPI = 72

NAVY = colors.HexColor("#1f3a5f")
INDUSTRY_COLOR = colors.HexColor("#1d4f53")
COMPANY_COLOR = colors.HexColor("#3b3a6b")
TEXT = colors.HexColor("#222222")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d9dee5")
EXPLAIN_BG = colors.HexColor("#f2f5f9")

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

# 文字の倍率の候補。大きい順に試し、最初に収まったものを使う
NEWS_SCALES = [s / 100 for s in range(130, 82, -3)]
# 業界の市況は情報量が多いので、もう少し小さい字まで許す
INDUSTRY_SCALES = [s / 100 for s in range(120, 80, -2)]
# 2枚に分けたとき、余裕のあるページは文字を大きくする。ただし差はこの比率まで
MAX_SCALE_RATIO = 1.15
# 1枚にまとめるのは、この倍率以上で収まるときだけ(小さい字で詰め込まない)
NEWS_ONE_PAGE_MIN = 1.0
INDUSTRY_ONE_PAGE_MIN = 0.96

WEEKDAYS = "月火水木金土日"
NEWS_DISCLAIMER = [
    "AIがウェブ検索をもとに要約・解説しています。",
    "正確な内容は各報道機関の記事でご確認ください。",
]
INDUSTRY_DISCLAIMER = [
    "数字は各団体・企業・報道の公表値。見通しは発表元の予測で、変わることがあります。",
    "AIがウェブ検索をもとにまとめています。正確な内容は公表元でご確認ください。",
]

COMPANY_DISCLAIMER = [
    "各社の発表や報道を、AIがウェブ検索をもとにまとめています。",
    "正確な内容は各社の発表でご確認ください。",
]

# 業界の勢いを表す印: (表示する言葉, 色, 矢印の角度)
TRENDS = {
    "up": ("上向き", "#2e7d5b", 45),
    "flat": ("横ばい", "#6b7280", 0),
    "down": ("下向き", "#c0392b", -45),
}
# 業界の欄の3段: (JSONの名前, 見出し, 見出しの色, 本文の背景色)
SECTOR_ROWS = [
    ("now", "現状", "#5f6b7a", "#f4f6f8"),
    ("focus", "注目", "#c2681c", "#fbf5ee"),
    ("outlook", "今後", "#1d4f53", "#e7f2f0"),
]

# 企業の欄の3段
COMPANY_ROWS = [
    ("news", "近況", "#5f6b7a", "#f4f6f8"),
    ("market", "関連", "#c2681c", "#fbf5ee"),
    ("outlook", "今後", "#3b3a6b", "#ecebf5"),
]

# イラストは Noto Emoji(Google、Apache License 2.0)の画像を使う
ICON_URL = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/2D/png/512/{name}"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

NO_PADDING = [
    ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ("TOPPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
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
        c.setFillColor(colors.HexColor(category_color(self.label)))
        c.roundRect(0, 0, self.width, self.height, self.height * 0.28, stroke=0, fill=1)
        size = self.font_size
        max_w = self.width - 5
        while pdfmetrics.stringWidth(self.label, "JP-Bold", size) > max_w and size > 4:
            size -= 0.25
        c.setFillColor(colors.white)
        c.setFont("JP-Bold", size)
        c.drawCentredString(self.width / 2, (self.height - size * 0.74) / 2, self.label)


class Rule(Flowable):
    """トピックの間に引く区切り線。"""

    def __init__(self, width):
        super().__init__()
        self.width = width
        self.height = 0.6

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(RULE)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 0, self.width, 0)


class TrendBadge(Flowable):
    """業界の勢いを、矢印と言葉で示す角丸のマーク。"""

    def __init__(self, trend, scale):
        super().__init__()
        self.label, color, self.angle = TRENDS.get(trend, TRENDS["flat"])
        self.color = colors.HexColor(color)
        self.scale = scale
        self.width = 60 * scale
        self.height = 17 * scale

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        c = self.canv
        k = self.scale
        c.setFillColor(self.color)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        # 矢印(軸と矢じり)を、マークの左寄りに回転させて描く
        c.saveState()
        c.translate(13 * k, self.height / 2)
        c.rotate(self.angle)
        c.setStrokeColor(colors.white)
        c.setFillColor(colors.white)
        c.setLineWidth(1.7 * k)
        c.setLineCap(1)
        c.line(-5 * k, 0, 2 * k, 0)
        head = c.beginPath()
        head.moveTo(5.5 * k, 0)
        head.lineTo(1 * k, 3.4 * k)
        head.lineTo(1 * k, -3.4 * k)
        head.close()
        c.drawPath(head, stroke=0, fill=1)
        c.restoreState()
        size = 9.6 * k
        c.setFillColor(colors.white)
        c.setFont("JP-Bold", size)
        c.drawString(22 * k, (self.height - size * 0.74) / 2, self.label)


def category_color(label):
    return CATEGORY_COLORS.get(label, DEFAULT_CATEGORY_COLOR)


def register_fonts():
    pdfmetrics.registerFont(TTFont("JP", str(FONT_DIR / "BIZUDPGothic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("JP-Bold", str(FONT_DIR / "BIZUDPGothic-Bold.ttf")))


def icon_path(emoji):
    """絵文字に対応するイラスト画像のパスを返す。手元になければ取りに行く。

    取得できなかった場合は None を返し、イラストなしで続ける。
    """
    if not emoji:
        return None
    codepoints = [f"{ord(ch):x}" for ch in emoji if ord(ch) != 0xFE0F]
    name = "emoji_u" + "_".join(codepoints) + ".png"
    path = ICON_DIR / name
    if path.exists():
        return path
    try:
        with urllib.request.urlopen(ICON_URL.format(name=name), timeout=20) as response:
            content = response.read()
    except OSError as e:
        print(f"注意: イラスト {emoji} を取得できませんでした({e})。イラストなしで続けます。")
        return None
    if not content.startswith(PNG_SIGNATURE):
        print(f"注意: イラスト {emoji} が画像ではありませんでした。イラストなしで続けます。")
        return None
    ICON_DIR.mkdir(exist_ok=True)
    path.write_bytes(content)
    return path


def tinted_box(label, text, color, scale, size):
    """色つきの縦線と薄い背景のついた、解説用の囲み。"""
    pad = 6.5 * scale
    label_style = ParagraphStyle(
        "boxlabel", fontName="JP-Bold", fontSize=size, leading=size * 1.45, textColor=color,
    )
    text_style = ParagraphStyle(
        "boxtext", fontName="JP", fontSize=size, leading=size * 1.5, textColor=TEXT, wordWrap="CJK",
    )
    box = Table([[[Paragraph(label, label_style), Paragraph(escape(text), text_style)]]],
                colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), EXPLAIN_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 2.6 * scale, color),
        ("LEFTPADDING", (0, 0), (-1, -1), pad + 2 * scale),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]))
    return box


# ---------- ニュース ----------

def build_topic(topic, scale):
    """トピック1件ぶんの部品を、上から順に並べたリストで返す。"""
    title_size = 12.5 * scale
    body_size = 10 * scale
    color = category_color(topic.get("category", ""))

    title_style = ParagraphStyle(
        "title", fontName="JP-Bold", fontSize=title_size, leading=title_size * 1.3,
        textColor=TEXT, wordWrap="CJK",
    )
    body_style = ParagraphStyle(
        "body", fontName="JP", fontSize=body_size, leading=body_size * 1.5,
        textColor=TEXT, wordWrap="CJK",
    )

    # 見出しの行: イラスト | ジャンル + 見出し
    chip = Chip(topic.get("category", "その他"), 44 * scale, 14 * scale, 9.4 * scale)
    heading = [chip, Spacer(1, 3.5 * scale), Paragraph(escape(topic["title"]), title_style)]
    icon_file = icon_path(topic.get("icon"))
    if icon_file:
        icon_size = 34 * scale
        icon_col = icon_size + 9 * scale
        head = Table(
            [[Image(str(icon_file), width=icon_size, height=icon_size, mask="auto"), heading]],
            colWidths=[icon_col, CONTENT_W - icon_col],
        )
    else:
        head = Table([[heading]], colWidths=[CONTENT_W])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")] + NO_PADDING))

    summary = escape(topic["summary"])
    if topic.get("source"):
        summary += f' <font color="#6b7280" size="{body_size * 0.85:.2f}">({escape(topic["source"])})</font>'

    parts = [head, Spacer(1, 5 * scale), Paragraph(summary, body_style)]
    if topic.get("explain"):
        parts += [Spacer(1, 6 * scale),
                  tinted_box("どういうこと?", topic["explain"], colors.HexColor(color), scale, 9.6 * scale)]
    return parts


def build_news_page(topics, scale, first_page=True, extra_gap=0.0):
    """ニュース1枚ぶんの部品のリスト。extra_gap はトピックの間に足す余白。"""
    gap = 10 * scale + extra_gap / 2
    story = []
    for i, topic in enumerate(topics):
        if i > 0:
            story += [Spacer(1, gap), Rule(CONTENT_W), Spacer(1, gap)]
        story += build_topic(topic, scale)
    return story


# ---------- 業界の市況 ----------

def build_block(sector, scale, row_defs, name_color):
    """業界または企業1つぶんの部品を、上から順に並べたリストで返す。

    row_defs は SECTOR_ROWS か COMPANY_ROWS。
    """
    name_size = 13 * scale
    headline_size = 10.8 * scale
    point_size = 9.3 * scale
    name_style = ParagraphStyle(
        "name", fontName="JP-Bold", fontSize=name_size, leading=name_size * 1.25,
        textColor=name_color, wordWrap="CJK",
    )
    about_style = ParagraphStyle(
        "about", fontName="JP", fontSize=8.6 * scale, leading=8.6 * scale * 1.4,
        textColor=MUTED, wordWrap="CJK",
    )
    headline_style = ParagraphStyle(
        "headline", fontName="JP-Bold", fontSize=headline_size, leading=headline_size * 1.35,
        textColor=TEXT, wordWrap="CJK",
    )
    # 2行目以降を「・」のぶんだけ字下げして、箇条書きの頭をそろえる
    point_style = ParagraphStyle(
        "point", fontName="JP", fontSize=point_size, leading=point_size * 1.48,
        textColor=TEXT, wordWrap="CJK", leftIndent=point_size, firstLineIndent=-point_size,
    )
    row_label_style = ParagraphStyle(
        "rowlabel", fontName="JP-Bold", fontSize=8.8 * scale, leading=8.8 * scale * 1.2,
        textColor=colors.white, alignment=1,
    )
    source_style = ParagraphStyle(
        "source", fontName="JP", fontSize=7.4 * scale, leading=7.4 * scale * 1.4,
        textColor=MUTED, wordWrap="CJK", alignment=2,
    )

    # 見出しの行: イラスト | 名前 | 勢いのマーク(イラストとマークは、あるときだけ)
    cells = [Paragraph(escape(sector["name"]), name_style)]
    widths = [CONTENT_W]
    icon_file = icon_path(sector.get("icon"))
    if icon_file:
        icon_size = 23 * scale
        icon_col = icon_size + 7 * scale
        cells.insert(0, Image(str(icon_file), width=icon_size, height=icon_size, mask="auto"))
        widths = [icon_col, widths[-1] - icon_col]
    if sector.get("trend") in TRENDS:
        badge = TrendBadge(sector["trend"], scale)
        cells.append(badge)
        widths = widths[:-1] + [widths[-1] - badge.width, badge.width]
    head = Table([cells], colWidths=widths)
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")] + NO_PADDING))

    parts = [head]
    if sector.get("about"):
        parts += [Spacer(1, 2 * scale), Paragraph(escape(sector["about"]), about_style)]
    if sector.get("headline"):
        parts += [Spacer(1, 3.5 * scale), Paragraph(escape(sector["headline"]), headline_style)]

    # 3段(現状・注目・今後など)。中身のない段は出さない
    rows, style = [], [
        ("VALIGN", (0, 0), (0, -1), "MIDDLE"),
        ("VALIGN", (1, 0), (1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), 6 * scale),
        ("RIGHTPADDING", (1, 0), (1, -1), 4 * scale),
        ("TOPPADDING", (0, 0), (-1, -1), 3.6 * scale),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6 * scale),
    ]
    for key, label, label_color, background in row_defs:
        points = sector.get(key) or []
        if not points:
            continue
        cell = []
        for point in points:
            if isinstance(point, str):
                point = {"text": point}
            text = "・"
            if point.get("new"):
                text += f'<font name="JP-Bold" color="#c0392b" size="{point_size * 0.82:.2f}">NEW</font> '
            cell.append(Paragraph(text + escape(point["text"]), point_style))
        row = len(rows)
        rows.append([Paragraph(label, row_label_style), cell])
        style += [
            ("BACKGROUND", (0, row), (0, row), colors.HexColor(label_color)),
            ("BACKGROUND", (1, row), (1, row), colors.HexColor(background)),
            # 段と段の間に白い線を入れて、すき間に見せる
            ("LINEBELOW", (0, row), (-1, row), 1.6 * scale, colors.white),
        ]
    if rows:
        label_col = 27 * scale
        table = Table(rows, colWidths=[label_col, CONTENT_W - label_col])
        table.setStyle(TableStyle(style))
        parts += [Spacer(1, 4 * scale), table]

    if sector.get("source"):
        parts += [Spacer(1, 1 * scale), Paragraph("出典: " + escape(sector["source"]), source_style)]
    return parts


def build_industry_page(sectors, scale, first_page=True, extra_gap=0.0, overview=""):
    """業界の市況1枚ぶんの部品のリスト。全体のポイントは1枚目の先頭に置く。"""
    story = []
    if first_page and overview:
        story += [tinted_box("全体のポイント", overview, INDUSTRY_COLOR, scale, 9.6 * scale),
                  Spacer(1, 8 * scale + extra_gap / 2)]
    gap = 6 * scale + extra_gap / 2
    for i, sector in enumerate(sectors):
        if i > 0:
            story += [Spacer(1, gap), Rule(CONTENT_W), Spacer(1, gap)]
        story += build_block(sector, scale, SECTOR_ROWS, INDUSTRY_COLOR)
    return story


def build_company_page(companies, scale, first_page=True, extra_gap=0.0):
    """企業ウォッチ1枚ぶんの部品のリスト。"""
    gap = 5.5 * scale + extra_gap / 2
    story = []
    for i, company in enumerate(companies):
        if i > 0:
            story += [Spacer(1, gap), Rule(CONTENT_W), Spacer(1, gap)]
        story += build_block(company, scale, COMPANY_ROWS, COMPANY_COLOR)
    return story


# ---------- 割り付けと描画(ニュース・業界で共通) ----------

def story_height(story):
    return sum(f.wrap(CONTENT_W, 100000)[1] for f in story)


def best_scale(build, items, first_page, scales):
    """この組み合わせが1枚に収まる最大の倍率。収まらなければ None。"""
    for scale in scales:
        if story_height(build(items, scale, first_page)) <= CONTENT_H:
            return scale
    return None


def plan_pages(build, items, scales, one_page_min, what):
    """項目をページに割り振り、(ページごとの項目, ページごとの倍率) を返す。"""
    one = best_scale(build, items, True, scales)
    if one is not None and one >= one_page_min:
        return [items], [one]

    # 2枚に分ける位置を全部試し、文字がいちばん大きくなる分け方を選ぶ
    best = None
    for k in range(1, len(items)):
        found = [best_scale(build, items[:k], True, scales), best_scale(build, items[k:], False, scales)]
        if None in found:
            continue
        if best is None or min(found) > min(best[1]):
            best = ([items[:k], items[k:]], found)
    if best is None:
        if one is not None:
            return [items], [one]
        sys.exit(f"エラー: {what}が2枚に収まりません。項目を減らすか、文章を短くしてください。")
    pages, found = best
    limit = min(found) * MAX_SCALE_RATIO
    return pages, [min(scale, limit) for scale in found]


def day_label(day):
    return f"{day.year}年{day.month}月{day.day}日({WEEKDAYS[day.weekday()]})"


def render(build, items, scale, first_page, gap_count, title, subtitle, color, disclaimer, corner, what):
    """1枚ぶんをPDFとしてメモリ上に作って返す(画像にするための中間データ)。"""
    # 下に余白が残るときは、項目の間に均等に配って間延びを防ぐ
    slack = CONTENT_H - story_height(build(items, scale, first_page))
    extra_gap = min(slack / gap_count, 26 * scale) if gap_count else 0
    story = build(items, scale, first_page, extra_gap)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    # 画像にしたとき背景が透明にならないよう、白で塗っておく
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    c.setFillColor(color)
    c.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("JP-Bold", 21)
    c.drawString(MARGIN, PAGE_H - 30, title)
    c.setFont("JP", 11)
    c.drawString(MARGIN, PAGE_H - 49, subtitle)
    if corner:
        c.setFont("JP-Bold", 13)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 30, corner)

    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(MARGIN, FOOTER_H, PAGE_W - MARGIN, FOOTER_H)
    c.setFillColor(MUTED)
    c.setFont("JP", 7.2)
    for i, line in enumerate(disclaimer):
        c.drawString(MARGIN, FOOTER_H - 11 - i * 10, line)

    # 計算のわずかな誤差で最後の部品がこぼれないよう、枠は下に少し余裕を持たせる
    frame = Frame(MARGIN, FOOTER_H + 2, CONTENT_W, CONTENT_H + 4,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame.addFromList(story, c)
    if story:
        sys.exit(f"エラー: {what}に入りきらない部分が出ました。文章を短くしてください。")
    c.save()
    return buffer.getvalue()


def save_images(pdf_bytes, png_path, preview_path):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count != 1:
        sys.exit(f"エラー: {doc.page_count}ページに分かれてしまいました。")
    page = doc[0]
    page.get_pixmap(dpi=IMAGE_DPI).save(png_path)
    page.get_pixmap(dpi=PREVIEW_DPI).save(preview_path, jpg_quality=82)


def make_set(build, items, scales, one_page_min, stem, title, subtitle, color, disclaimer,
             what, has_lead=False):
    """1種類ぶん(ニュース、または業界の市況)の画像を作って保存する。

    has_lead は、1枚目の先頭に「全体のポイント」のような囲みがあるかどうか。
    """
    pages, page_scales = plan_pages(build, items, scales, one_page_min, what)
    shown = " / ".join(f"{scale:.2f}" for scale in page_scales)
    print(f"{what}: {len(pages)}枚(文字の倍率 {shown}、{len(items)} 件)")
    for no, (page_items, scale) in enumerate(zip(pages, page_scales), start=1):
        first_page = no == 1
        gap_count = len(page_items) - 1 + (1 if first_page and has_lead else 0)
        corner = f"{no} / {len(pages)}" if len(pages) > 1 else ""
        pdf_bytes = render(build, page_items, scale, first_page, gap_count, title, subtitle,
                           color, disclaimer, corner, f"{what}の{no}枚目")
        png_path = OUT_DIR / f"{stem}_{no}.png"
        save_images(pdf_bytes, png_path, OUT_DIR / f"{stem}_{no}_preview.jpg")
        print(f"  {png_path.relative_to(ROOT)}  {png_path.stat().st_size // 1024} KB({len(page_items)} 件)")


def main():
    if len(sys.argv) != 2:
        sys.exit("使い方: python make_image.py data/YYYY-MM-DD.json")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    topics = data["topics"]
    if not topics:
        sys.exit("エラー: topics が空です。")
    day = date.fromisoformat(data["date"])

    register_fonts()
    OUT_DIR.mkdir(exist_ok=True)
    make_set(build_news_page, topics, NEWS_SCALES, NEWS_ONE_PAGE_MIN, data["date"],
             "きのうの日本", f"{day_label(day)}の主なトピックス", NAVY, NEWS_DISCLAIMER, "ニュース")

    industry = data.get("industry") or {}
    if industry.get("sectors"):
        overview = industry.get("overview", "")

        def build(sectors, scale, first_page=True, extra_gap=0.0):
            return build_industry_page(sectors, scale, first_page, extra_gap, overview)

        make_set(build, industry["sectors"], INDUSTRY_SCALES, INDUSTRY_ONE_PAGE_MIN,
                 f"{data['date']}_industry", "ものづくり市況", f"{day_label(day)}時点の現状と見通し",
                 INDUSTRY_COLOR, INDUSTRY_DISCLAIMER, "業界の市況", has_lead=bool(overview))

    companies = data.get("companies") or []
    if companies:
        make_set(build_company_page, companies, INDUSTRY_SCALES, INDUSTRY_ONE_PAGE_MIN,
                 f"{data['date']}_company", "企業ウォッチ", f"{day_label(day)}時点の近況と見通し",
                 COMPANY_COLOR, COMPANY_DISCLAIMER, "企業ウォッチ")


if __name__ == "__main__":
    main()
