"""
Build the free-distribution PMP study PDF — English edition.
150 questions, answers + full English explanations.
Cover + how-to page + question pages + back cover CTA.
"""
import json, os, html

from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether,
    Frame, PageTemplate, BaseDocTemplate, NextPageTemplate
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

OUT = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(OUT, 'fonts')
SITE_NAME = 'pmp.wayexam.com'
SITE_URL = 'https://pmp.wayexam.com'
TOTAL_Q = 2250
EDITION_YR = 2026

BRAND = HexColor('#3D5AFE')
BRAND_DARK = HexColor('#2541E8')
WARM = HexColor('#FF6B35')
INK = HexColor('#1A2230')
INK_SOFT = HexColor('#4A5468')
INK_MUTED = HexColor('#7C8696')
PAPER = HexColor('#FFFFFF')
MIST = HexColor('#F4F6FC')
SOFT_LINE = HexColor('#E3E7EF')
CORRECT_BG = HexColor('#E7F8F0')

pdfmetrics.registerFont(TTFont('Pretend', f'{FONTS}/Pretendard-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Pretend-B', f'{FONTS}/Pretendard-Bold.ttf'))
pdfmetrics.registerFont(TTFont('Pretend-SB', f'{FONTS}/Pretendard-SemiBold.ttf'))
registerFontFamily('Pretend', normal='Pretend', bold='Pretend-B',
                   italic='Pretend', boldItalic='Pretend-B')


def S(name, **kw):
    base = dict(fontName='Pretend', fontSize=10, leading=14, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name=name, **base)


style_h2 = S('h2', fontName='Pretend-B', fontSize=15, leading=20, textColor=INK)
style_h3 = S('h3', fontName='Pretend-B', fontSize=11.5, leading=16, textColor=BRAND_DARK)
style_body = S('body', fontSize=10.5, leading=15.5, textColor=INK_SOFT)
style_body_l = S('body_l', fontSize=10, leading=14, textColor=INK)
style_caption = S('caption', fontSize=8.5, leading=12, textColor=INK_MUTED)
style_q_meta = S('qmeta', fontSize=8.5, leading=12, textColor=INK_MUTED)
style_q_en = S('qen', fontName='Pretend-SB', fontSize=9.8, leading=13.4, textColor=INK)
style_opt = S('opt', fontSize=9.1, leading=12.4, textColor=INK_SOFT)
style_expl = S('exp', fontSize=8.2, leading=11.4, textColor=INK_SOFT, alignment=TA_JUSTIFY)

PAGE_W, PAGE_H = A4
MARGIN_L = MARGIN_R = 16 * mm
MARGIN_T = 18 * mm
MARGIN_B = 18 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


def esc(s):
    return html.escape(str(s or ''), quote=False)


def chip(text, fg):
    return f'<font color="{fg}" size="8"><b>{esc(text)}</b></font>'


def draw_content_chrome(c, doc):
    c.saveState()
    c.setFillColor(BRAND)
    c.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
    c.setStrokeColor(SOFT_LINE)
    c.setLineWidth(0.4)
    c.line(MARGIN_L, MARGIN_B - 4 * mm, PAGE_W - MARGIN_R, MARGIN_B - 4 * mm)
    c.setFont('Pretend', 8)
    c.setFillColor(INK_MUTED)
    c.drawString(MARGIN_L, MARGIN_B - 8 * mm,
                 f'PMP Free Practice Pack  ·  150 Questions  ·  {SITE_NAME}')
    c.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 8 * mm, str(doc.page))
    c.restoreState()


def draw_cover(c, doc):
    c.saveState()
    c.setFillColor(HexColor('#0E1F4D')); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(BRAND_DARK); c.rect(0, 0, PAGE_W * 0.7, PAGE_H, fill=1, stroke=0)
    c.setFillColor(HexColor('#5B7BFF')); c.rect(0, 0, PAGE_W * 0.45, PAGE_H, fill=1, stroke=0)
    c.setFillColor(HexColor('#FFFFFF'))
    c.setFillAlpha(0.06)
    c.circle(PAGE_W * 0.85, PAGE_H * 0.78, 110, stroke=0, fill=1)
    c.circle(PAGE_W * 0.92, PAGE_H * 0.20, 70, stroke=0, fill=1)
    c.setFillAlpha(0.10)
    c.circle(PAGE_W * 0.08, PAGE_H * 0.30, 50, stroke=0, fill=1)
    c.setFillAlpha(1)

    c.setFillColor(HexColor('#A8B6FF')); c.setFont('Pretend-SB', 10)
    c.drawString(MARGIN_L, PAGE_H - 16 * mm, 'PMP.WAYEXAM.COM   ·   PMP STUDY PACK')

    c.setFillColor(WARM)
    chip_w = 70 * mm
    c.roundRect(PAGE_W - chip_w - MARGIN_R, PAGE_H - 26 * mm, chip_w, 11 * mm, 2.5 * mm,
                stroke=0, fill=1)
    c.setFillColor(PAPER); c.setFont('Pretend-B', 11)
    c.drawCentredString(PAGE_W - chip_w / 2 - MARGIN_R, PAGE_H - 22.4 * mm,
                        'FREE EDITION  ·  ENGLISH ONLY')

    c.setFillColor(PAPER); c.setFont('Pretend-B', 44)
    c.drawString(MARGIN_L, PAGE_H * 0.55, 'PMP Exam')
    c.drawString(MARGIN_L, PAGE_H * 0.55 - 18 * mm, 'Practice Pack')
    c.setFont('Pretend-B', 78); c.setFillColor(WARM)
    c.drawString(MARGIN_L, PAGE_H * 0.55 - 60 * mm, '150')
    c.setFillColor(PAPER); c.setFont('Pretend-SB', 17)
    c.drawString(MARGIN_L + 78 * mm, PAGE_H * 0.55 - 50 * mm,
                 'Selected Questions  ·  English')
    c.setFont('Pretend', 11.5); c.setFillColor(HexColor('#D7E0FF'))
    c.drawString(MARGIN_L + 78 * mm, PAGE_H * 0.55 - 58 * mm,
                 'Answers  ·  Full English explanations included')

    c.setFont('Pretend-SB', 13.5); c.setFillColor(HexColor('#A8B6FF'))
    c.drawString(MARGIN_L, PAGE_H * 0.30,
                 '2026 ECO  ·  PMBOK 7 & 8  ·  Agile/Hybrid 25%+ fully covered')

    c.setFillColor(HexColor('#0A1838')); c.rect(0, 0, PAGE_W, 36 * mm, stroke=0, fill=1)
    c.setFillColor(PAPER); c.setFont('Pretend-B', 18)
    c.drawString(MARGIN_L, 21 * mm, SITE_URL)
    c.setFillColor(HexColor('#A8B6E4')); c.setFont('Pretend', 10)
    c.drawString(MARGIN_L, 14 * mm,
                 'Free 7-day Premium on signup  ·  Analytics dashboard  ·  '
                 'Weak-area drill mode')
    c.drawString(MARGIN_L, 8 * mm,
                 f'{TOTAL_Q:,} questions total  ·  PMBOK 7 & 8  ·  Agile/Hybrid 25%+  '
                 f'·  {EDITION_YR} Edition')
    c.restoreState()


def draw_back(c, doc):
    c.saveState()
    c.setFillColor(PAPER); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(BRAND_DARK); c.rect(0, PAGE_H - 80 * mm, PAGE_W, 80 * mm, fill=1, stroke=0)
    c.setFillColor(BRAND); c.rect(0, PAGE_H - 80 * mm, PAGE_W * 0.55, 80 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor('#FFFFFF')); c.setFillAlpha(0.10)
    c.circle(PAGE_W * 0.88, PAGE_H - 24 * mm, 60, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(PAPER); c.setFont('Pretend-B', 27)
    c.drawString(MARGIN_L, PAGE_H - 30 * mm, 'Finished all 150?')
    c.setFont('Pretend-B', 21)
    c.drawString(MARGIN_L, PAGE_H - 45 * mm, f'Unlock all {TOTAL_Q:,} questions')
    c.setFont('Pretend', 11); c.setFillColor(HexColor('#D7E0FF'))
    c.drawString(MARGIN_L, PAGE_H - 55 * mm,
                 'Sign up and get 7 days of Premium automatically — no card required.')
    c.setFont('Pretend-B', 18); c.setFillColor(PAPER)
    c.drawString(MARGIN_L, PAGE_H - 70 * mm, SITE_URL)

    sx = MARGIN_L
    sy = PAGE_H - 110 * mm
    col_w = (CONTENT_W - 12 * mm) / 3
    cards = [
        ('Full domain coverage',
         f'{TOTAL_Q:,} questions matching the PMI blend of People, Process and Business '
         f'Environment across PMBOK 7 and 8, with Agile and Hybrid above 25%.'),
        ('Automatic weak-area analysis',
         'Accuracy tracked per domain and per principle, with wrong-answer notes, bookmarks '
         'and keyword search so you see exactly where you lose marks.'),
        ('Exam-style mock runs',
         'Full 180 and 185 question mock exams with batch scoring, plus drill modes that '
         'target only the areas you keep missing.'),
    ]
    for i, (t, b) in enumerate(cards):
        x = sx + i * (col_w + 6 * mm)
        c.setFillColor(MIST)
        c.roundRect(x, sy - 50 * mm, col_w, 50 * mm, 3 * mm, stroke=0, fill=1)
        c.setFillColor(BRAND_DARK); c.setFont('Pretend-B', 12)
        c.drawString(x + 6 * mm, sy - 12 * mm, t)
        c.setFillColor(INK_SOFT); c.setFont('Pretend', 8.6)
        line = ''
        line_y = sy - 20 * mm
        for w in b.split(' '):
            test = (line + ' ' + w).strip()
            if len(test) > 34:
                c.drawString(x + 6 * mm, line_y, line)
                line = w
                line_y -= 4.2 * mm
            else:
                line = test
        if line:
            c.drawString(x + 6 * mm, line_y, line)

    btn_y = sy - 66 * mm
    c.setFillColor(WARM)
    c.roundRect(MARGIN_L, btn_y, 86 * mm, 14 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(PAPER); c.setFont('Pretend-B', 13)
    c.drawCentredString(MARGIN_L + 43 * mm, btn_y + 4.8 * mm, 'Start practising free')

    c.setFillColor(INK_MUTED); c.setFont('Pretend', 8)
    c.drawString(MARGIN_L, 14 * mm,
                 'Distributed free of charge for personal study only. Redistribution, resale or '
                 'commercial use of any part is prohibited.')
    c.drawString(MARGIN_L, 9 * mm,
                 f'(c) PMP Quiz / The Songdo. All rights reserved.  ·  {SITE_URL}')
    c.restoreState()


def build_intro(story):
    story.append(Paragraph('How to use this pack', style_h2))
    story.append(Spacer(1, 4 * mm))
    items = [
        ('150 real-style PMP questions',
         'Each question is followed by four options, the correct answer, and a full English '
         'explanation. Questions are drawn at random from our 2,250-question bank.'),
        ('Two questions per page',
         'Work through one page at a time. Cover the answer line with your hand, decide first, '
         'then check.'),
        ('Domain coverage',
         'ECO domains (People / Process / Business Environment) and PMBOK 7 & 8 performance '
         'domains are tagged above every question.'),
        ('Agile, Hybrid and Predictive',
         'The mix mirrors the real exam, where Agile and Hybrid approaches make up more than '
         'half the content.'),
        ('Practice online for free',
         f'Sign up at {SITE_NAME} to unlock all {TOTAL_Q:,} questions, wrong-answer notes, and '
         f'performance analytics — 7 days of Premium included.'),
    ]
    for t, b in items:
        story.append(Paragraph(t, style_h3))
        story.append(Paragraph(b, style_body))
        story.append(Spacer(1, 3.5 * mm))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph('Copyright', style_h3))
    story.append(Paragraph(
        'This document is distributed free of charge for personal study only. Redistribution, '
        'resale, or commercial use of any part of this material is prohibited. '
        '(c) PMP Quiz / The Songdo. All rights reserved.', style_caption))


def build_question(story, q):
    n = q['display_num']
    chips = []
    if q.get('eco_domain_2026'):
        chips.append(chip(f"ECO {q['eco_domain_2026']}", '#3D5AFE'))
    if q.get('perf_p7'):
        chips.append(chip(f"PMBOK7 {q['perf_p7']}", '#C24914'))
    if q.get('methodology'):
        chips.append(chip(q['methodology'], '#0F8A5A'))

    block = []
    if chips:
        block.append(Paragraph('   ·   '.join(chips), style_q_meta))
        block.append(Spacer(1, 0.8 * mm))
    block.append(Paragraph(f'<font color="#3D5AFE" size="12"><b>Q{n}.</b></font>', style_q_meta))
    block.append(Spacer(1, 0.6 * mm))
    block.append(Paragraph(esc(q['question_en']), style_q_en))
    block.append(Spacer(1, 1.4 * mm))

    for letter in ['A', 'B', 'C', 'D', 'E']:
        en = q['options_en'].get(letter)
        if not en:
            continue
        block.append(Paragraph(f'<b>{letter}.</b>&nbsp;&nbsp;' + esc(en), style_opt))
        block.append(Spacer(1, 0.4 * mm))
    block.append(Spacer(1, 1.5 * mm))

    ans_tbl = Table([[Paragraph(
        f'<b>Answer:&nbsp; <font color="#0F8A5A" size="13">{esc(q["answer"])}</font></b>',
        style_body_l)]], colWidths=[CONTENT_W])
    ans_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CORRECT_BG),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    block.append(ans_tbl)
    block.append(Spacer(1, 1.4 * mm))

    if q.get('explanation_en'):
        block.append(Paragraph('<b>Explanation</b>', style_q_meta))
        block.append(Paragraph(esc(q['explanation_en']), style_expl))
    block.append(Spacer(1, 2.4 * mm))

    div = Table([['']], colWidths=[CONTENT_W], rowHeights=[0.4])
    div.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.4, SOFT_LINE)]))
    block.append(div)
    block.append(Spacer(1, 2.4 * mm))
    story.append(KeepTogether(block))


def main():
    with open(f'{OUT}/selected_150_en.json', encoding='utf-8') as f:
        questions = json.load(f)
    print(f'Loaded {len(questions)} questions')
    out_pdf = f'{OUT}/PMP_Free_Practice_Pack_150_EN.pdf'

    doc = BaseDocTemplate(
        out_pdf, pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title='PMP Exam Practice Pack - 150 Free Questions',
        author='PMP Quiz / The Songdo', subject='PMP practice questions (English)',
    )
    frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B, id='body')
    doc.addPageTemplates([
        PageTemplate(id='Cover', frames=[frame], onPage=draw_cover),
        PageTemplate(id='Content', frames=[frame], onPage=draw_content_chrome),
        PageTemplate(id='Back', frames=[frame], onPage=draw_back),
    ])

    story = [NextPageTemplate('Content'), Spacer(1, 1), PageBreak()]
    build_intro(story)
    story.append(PageBreak())
    for q in questions:
        build_question(story, q)
    story.append(NextPageTemplate('Back'))
    story.append(PageBreak())
    story.append(Spacer(1, 1))

    doc.build(story)
    print(f'Built: {out_pdf} ({os.path.getsize(out_pdf)/1024:.1f} KB)')


if __name__ == '__main__':
    main()
