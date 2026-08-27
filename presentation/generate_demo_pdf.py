"""生成 ConsensusSeam 与 etcd/raft 实验的 16:9 中文展示 PDF。"""

from __future__ import annotations

import math
import re
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


PAGE_W = 960
PAGE_H = 540
TOTAL_PAGES = 12

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "presentation" / "ConsensusSeam_etcd实验展示.pdf"

# ReportLab 3.6 无法嵌入本机 CFF 轮廓的 Noto CJK TTC。STSong-Light
# 是其内置 Unicode CID 字体，能够稳定承载本演示所需的中英文混排。
FONT_UI = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT_UI))


NAVY = "#0B1739"
NAVY_2 = "#13264F"
INK = "#17233D"
MUTED = "#5E6B85"
LIGHT = "#F4F7FB"
LINE = "#D9E1EE"
WHITE = "#FFFFFF"
TEAL = "#14B8A6"
TEAL_DARK = "#0F766E"
BLUE = "#3B82F6"
BLUE_DARK = "#1D4ED8"
GREEN = "#22C55E"
GREEN_DARK = "#15803D"
AMBER = "#F59E0B"
CORAL = "#F97360"
RED = "#EF4444"
PURPLE = "#8B5CF6"
CYAN = "#22D3EE"


def color(value: str):
    return tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))


def set_fill(c: canvas.Canvas, value: str) -> None:
    c.setFillColorRGB(*color(value))


def set_stroke(c: canvas.Canvas, value: str) -> None:
    c.setStrokeColorRGB(*color(value))


def rounded_box(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = WHITE,
    stroke: str | None = LINE,
    radius: float = 14,
    width: float = 1,
) -> None:
    c.saveState()
    set_fill(c, fill)
    if stroke:
        set_stroke(c, stroke)
        c.setLineWidth(width)
        c.roundRect(x, y, w, h, radius, fill=1, stroke=1)
    else:
        c.roundRect(x, y, w, h, radius, fill=1, stroke=0)
    c.restoreState()


def line(
    c: canvas.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = LINE,
    width: float = 1,
    dash: tuple[int, int] | None = None,
) -> None:
    c.saveState()
    set_stroke(c, stroke)
    c.setLineWidth(width)
    if dash:
        c.setDash(*dash)
    c.line(x1, y1, x2, y2)
    c.restoreState()


def arrow(
    c: canvas.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = BLUE,
    width: float = 2,
    dash: tuple[int, int] | None = None,
    head: float = 8,
) -> None:
    line(c, x1, y1, x2, y2, stroke=stroke, width=width, dash=dash)
    angle = math.atan2(y2 - y1, x2 - x1)
    c.saveState()
    set_fill(c, stroke)
    points = [
        (x2, y2),
        (
            x2 - head * math.cos(angle - math.pi / 6),
            y2 - head * math.sin(angle - math.pi / 6),
        ),
        (
            x2 - head * math.cos(angle + math.pi / 6),
            y2 - head * math.sin(angle + math.pi / 6),
        ),
    ]
    path = c.beginPath()
    path.moveTo(*points[0])
    path.lineTo(*points[1])
    path.lineTo(*points[2])
    path.close()
    c.drawPath(path, fill=1, stroke=0)
    c.restoreState()


def _tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./:+()<>-]+|[\u3400-\u9fff]|[^\s]", value)


def resolved_font(font: str) -> str:
    return FONT_UI if font in {"Noto", "NotoBold"} else font


def wrap_text(value: str, font: str, size: float, max_width: float) -> list[str]:
    font = resolved_font(font)
    lines: list[str] = []
    current = ""
    for token in _tokens(value):
        separator = "" if not current or re.match(r"[\u3400-\u9fff，。；：、（）]", token) else " "
        candidate = current + separator + token
        if current and pdfmetrics.stringWidth(candidate, font, size) > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def draw_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    value: str,
    *,
    size: float = 14,
    fill: str = INK,
    font: str = "Noto",
    max_width: float | None = None,
    leading: float | None = None,
    align: str = "left",
) -> float:
    leading = leading or size * 1.45
    lines = [value] if max_width is None else wrap_text(value, font, size, max_width)
    c.saveState()
    set_fill(c, fill)
    c.setFont(resolved_font(font), size)
    yy = y
    for item in lines:
        if align == "center":
            c.drawCentredString(x, yy, item)
        elif align == "right":
            c.drawRightString(x, yy, item)
        else:
            c.drawString(x, yy, item)
        yy -= leading
    c.restoreState()
    return y - yy


def badge(
    c: canvas.Canvas,
    x: float,
    y: float,
    label: str,
    *,
    fill: str = TEAL,
    text_fill: str = WHITE,
    width: float | None = None,
) -> float:
    w = width or max(68, pdfmetrics.stringWidth(label, FONT_UI, 10) + 24)
    rounded_box(c, x, y, w, 24, fill=fill, stroke=None, radius=12)
    draw_text(c, x + w / 2, y + 7, label, size=10, fill=text_fill, font="NotoBold", align="center")
    return w


def page_header(c: canvas.Canvas, title: str, kicker: str, page: int) -> None:
    set_fill(c, LIGHT)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    rounded_box(c, 34, 487, 6, 28, fill=TEAL, stroke=None, radius=3)
    draw_text(c, 52, 506, kicker, size=9, fill=TEAL_DARK, font="NotoBold")
    draw_text(c, 52, 478, title, size=25, fill=NAVY, font="NotoBold")
    draw_text(c, 926, 24, f"{page:02d} / {TOTAL_PAGES:02d}", size=9, fill=MUTED, align="right")
    line(c, 34, 42, 926, 42, stroke=LINE, width=0.8)


def card_title(c: canvas.Canvas, x: float, y: float, index: str, title: str, accent: str) -> None:
    set_fill(c, accent)
    c.circle(x + 15, y + 15, 15, fill=1, stroke=0)
    draw_text(c, x + 15, y + 10, index, size=10, fill=WHITE, font="NotoBold", align="center")
    draw_text(c, x + 40, y + 8, title, size=15, fill=NAVY, font="NotoBold")


def metric_card(c: canvas.Canvas, x: float, y: float, w: float, value: str, label: str, accent: str) -> None:
    rounded_box(c, x, y, w, 74, fill=WHITE, stroke="#DDE5F1", radius=15)
    rounded_box(c, x, y, 7, 74, fill=accent, stroke=None, radius=4)
    draw_text(c, x + 22, y + 39, value, size=25, fill=NAVY, font="NotoBold")
    draw_text(c, x + 22, y + 16, label, size=10, fill=MUTED)


def footer_source(c: canvas.Canvas, value: str) -> None:
    draw_text(c, 36, 24, value, size=7.5, fill=MUTED, max_width=790, leading=9)


def slide_cover(c: canvas.Canvas) -> None:
    set_fill(c, NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # 右侧抽象网络图。
    for x, y, r, col in (
        (720, 370, 76, BLUE),
        (820, 270, 52, TEAL),
        (675, 205, 40, PURPLE),
        (860, 410, 30, CORAL),
    ):
        c.saveState()
        set_fill(c, col)
        c.setFillAlpha(0.18)
        c.circle(x, y, r, fill=1, stroke=0)
        c.restoreState()
    for a, b in (((720, 370), (820, 270)), ((720, 370), (675, 205)), ((820, 270), (860, 410)), ((675, 205), (820, 270))):
        line(c, *a, *b, stroke="#5675B6", width=2)
    for x, y, label in ((720, 370, "A1"), (820, 270, "A2"), (675, 205, "A3"), (860, 410, "C")):
        set_fill(c, WHITE)
        c.circle(x, y, 23, fill=1, stroke=0)
        draw_text(c, x, y - 5, label, size=11, fill=NAVY, font="NotoBold", align="center")

    badge(c, 56, 458, "多 Agent 共识测试接口生成", fill=TEAL)
    draw_text(c, 56, 380, "ConsensusSeam", size=46, fill=WHITE, font="Helvetica-Bold")
    draw_text(c, 56, 337, "从共识源码到可测试接口", size=28, fill="#B9E7E2", font="NotoBold")
    draw_text(
        c,
        58,
        292,
        "流程架构｜Agent 输入输出｜etcd/raft 3.6 实验效果",
        size=15,
        fill="#C8D4ED",
    )

    metric_card(c, 56, 145, 154, "7", "基础测试控制能力", TEAL)
    metric_card(c, 226, 145, 154, "3", "etcd 新增接口能力", BLUE)
    metric_card(c, 396, 145, 154, "PASS", "构建、测试与审查", GREEN)
    draw_text(c, 58, 92, "目标提交 9118047｜Controller 1a28bd7｜2026-08-27", size=10, fill="#8FA4CF")
    draw_text(c, 904, 30, "01 / 12", size=9, fill="#8FA4CF", align="right")
    c.showPage()


def slide_problem(c: canvas.Canvas) -> None:
    page_header(c, "研究问题：功能存在，但测试控制面缺失", "01 研究动机", 2)
    # 左—中—右主叙事。
    rounded_box(c, 48, 250, 230, 170, fill=WHITE)
    card_title(c, 66, 376, "A", "共识实现", BLUE)
    for i, text in enumerate(("协议状态机", "Ready / Step / Tick", "存储与恢复", "已有功能测试")):
        badge(c, 74, 340 - i * 29, text, fill="#E8F0FF", text_fill=BLUE_DARK, width=170)

    rounded_box(c, 365, 250, 230, 170, fill="#FFF8ED", stroke="#F7D7A4")
    card_title(c, 383, 376, "?", "缺少测试接口", AMBER)
    draw_text(c, 389, 337, "消息无法暂停与编号", size=13, fill=INK)
    draw_text(c, 389, 306, "随机性难以复现", size=13, fill=INK)
    draw_text(c, 389, 275, "已有入口分散、难组合", size=13, fill=INK)

    rounded_box(c, 682, 250, 230, 170, fill=WHITE)
    card_title(c, 700, 376, "T", "分布式测试", TEAL)
    for i, text in enumerate(("选择并注入消息", "推进逻辑时间", "控制随机选择", "观察与恢复节点")):
        badge(c, 708, 340 - i * 29, text, fill="#E3F8F5", text_fill=TEAL_DARK, width=170)

    arrow(c, 280, 335, 357, 335, stroke=AMBER, width=3)
    arrow(c, 597, 335, 674, 335, stroke=TEAL, width=3)

    draw_text(c, 50, 206, "v0.1 统一研究对象：七项基础能力", size=15, fill=NAVY, font="NotoBold")
    abilities = [
        ("消息捕获", TEAL),
        ("消息注入", TEAL),
        ("时间控制", BLUE),
        ("随机性控制", PURPLE),
        ("生命周期", CORAL),
        ("状态观察", GREEN),
        ("外部输入", AMBER),
    ]
    for i, (label, accent) in enumerate(abilities):
        badge(c, 50 + i * 126, 148, label, fill=accent, width=112)
    rounded_box(c, 50, 76, 862, 48, fill=NAVY_2, stroke=None, radius=12)
    draw_text(c, 481, 91, "目标：Agent 发现已有能力，并以目标原生方式补齐缺失接口；不生成测试策略，不改协议语义。", size=12, fill=WHITE, align="center")
    footer_source(c, "研究边界：协议库内部测试控制；真实网络、业务状态机与完整部署在边界外")
    c.showPage()


def slide_architecture(c: canvas.Canvas) -> None:
    page_header(c, "整体流程架构：自动生成是主流程，repair 只是可选补救", "02 系统架构", 3)
    # 输入层。
    for i, (title, sub, accent) in enumerate(
        (
            ("目标 Git 仓库", "固定 revision", BLUE),
            ("系统边界", "包含 / 排除", PURPLE),
            ("构建测试命令", "目标原生工具链", TEAL),
            ("七项能力规范", "目标无关合同", AMBER),
        )
    ):
        x = 44 + i * 222
        rounded_box(c, x, 407, 196, 58, fill=WHITE)
        rounded_box(c, x, 407, 6, 58, fill=accent, stroke=None, radius=3)
        draw_text(c, x + 18, 439, title, size=12, fill=NAVY, font="NotoBold")
        draw_text(c, x + 18, 419, sub, size=9, fill=MUTED)

    draw_text(c, 46, 378, "Controller：固定状态机｜隔离 worktree｜强类型报告｜有界重试", size=11, fill=MUTED)
    # 主流程节点。
    nodes = [
        (52, 255, 134, "Agent 1", "分析与分类", BLUE),
        (228, 255, 134, "Agent 2", "按能力生成", TEAL),
        (404, 255, 134, "构建 / 自测", "目标工具链", AMBER),
        (580, 255, 134, "Agent 3", "独立审查", PURPLE),
        (756, 255, 152, "候选产物", "代码 + 报告", GREEN),
    ]
    for x, y, w, title, sub, accent in nodes:
        rounded_box(c, x, y, w, 82, fill=WHITE, stroke=accent, radius=14, width=1.5)
        badge(c, x + 12, y + 46, title, fill=accent, width=w - 24)
        draw_text(c, x + w / 2, y + 18, sub, size=11, fill=INK, font="NotoBold", align="center")
    for x1, x2 in ((186, 222), (362, 398), (538, 574), (714, 750)):
        arrow(c, x1, 296, x2, 296, stroke=BLUE, width=2.4)

    # 自动反馈回路。
    line(c, 647, 249, 647, 211, stroke=CORAL, width=2)
    line(c, 647, 211, 295, 211, stroke=CORAL, width=2)
    arrow(c, 295, 211, 295, 249, stroke=CORAL, width=2)
    badge(c, 424, 197, "REVISE_AGENT2：重放候选并继续修改", fill=CORAL, width=270)
    line(c, 614, 249, 614, 174, stroke=PURPLE, width=1.5, dash=(5, 4))
    line(c, 614, 174, 119, 174, stroke=PURPLE, width=1.5, dash=(5, 4))
    arrow(c, 119, 174, 119, 249, stroke=PURPLE, width=1.5, dash=(5, 4))
    badge(c, 281, 160, "REVISE_AGENT1：重新分析边界与分类", fill=PURPLE, width=270)

    # 可选分支。
    rounded_box(c, 54, 72, 388, 58, fill="#EEF6FF", stroke="#BED8FF")
    draw_text(c, 74, 106, "run｜固定评测 / 回归", size=12, fill=BLUE_DARK, font="NotoBold")
    draw_text(c, 74, 84, "适用于已经有稳定 capability checks 的成熟目标", size=9, fill=MUTED)
    rounded_box(c, 518, 72, 388, 58, fill="#F3EEFF", stroke="#D8C7FF")
    draw_text(c, 538, 106, "repair｜可选质量增强", size=12, fill="#6D28D9", font="NotoBold")
    draw_text(c, 538, 84, "基于生成后真实测试修复已有候选，不是必经步骤", size=9, fill=MUTED)
    footer_source(c, "核心结论：patch 自身必须产出可用候选；Agent 3 是首次生成的自动质量闭环")
    c.showPage()


def slide_roles(c: canvas.Canvas) -> None:
    page_header(c, "三个 Agent：职责隔离，信息逐步收敛", "03 Agent 协作", 4)
    columns = [
        (46, "Agent 1｜能力分析", BLUE, "只读源码", ["找出真实执行路径", "判断已有 / 可补 / 侵入", "给出代码证据与缺口"], "capability-report.json"),
        (354, "Agent 2｜低侵入生成", TEAL, "隔离 worktree", ["只处理 PATCHABLE 能力", "按能力独立工具循环", "生成目标原生接口与测试"], "interface-report.json\nchanges.patch"),
        (662, "Agent 3｜独立审查", PURPLE, "原始 + 候选只读", ["核对合同与路径覆盖", "区分阻塞 issue / 剩余 risk", "自动路由回 Agent 1 / 2"], "review-report.json"),
    ]
    for x, title, accent, mode, bullets, output in columns:
        rounded_box(c, x, 106, 252, 340, fill=WHITE, stroke=accent, radius=18, width=1.5)
        rounded_box(c, x, 378, 252, 68, fill=accent, stroke=None, radius=17)
        draw_text(c, x + 18, 413, title, size=16, fill=WHITE, font="NotoBold")
        draw_text(c, x + 18, 391, mode, size=9, fill="#EAF2FF")
        for i, item in enumerate(bullets):
            set_fill(c, accent)
            c.circle(x + 25, 338 - i * 50, 5, fill=1, stroke=0)
            draw_text(c, x + 40, 333 - i * 50, item, size=11, fill=INK, max_width=188)
        line(c, x + 18, 209, x + 234, 209, stroke=LINE)
        draw_text(c, x + 18, 187, "主要输出", size=9, fill=MUTED, font="NotoBold")
        for j, part in enumerate(output.split("\n")):
            badge(c, x + 18, 145 - j * 29, part, fill="#EDF2FA", text_fill=NAVY, width=216)
    footer_source(c, "隔离原则：Agent 1 不写代码；Agent 2 不修改原仓库；Agent 3 不修改候选")
    c.showPage()


def slide_agent1(c: canvas.Canvas) -> None:
    page_header(c, "Agent 1：从源码证据生成七项能力地图", "04 Agent 1 输入 / 输出", 5)
    rounded_box(c, 42, 100, 250, 344, fill=WHITE)
    draw_text(c, 62, 412, "输入", size=18, fill=BLUE_DARK, font="NotoBold")
    inputs = [
        ("源码与符号", "文件、方法、调用关系"),
        ("系统边界", "本次允许分析的代码层"),
        ("协议简介", "只提供概念，不给标准答案"),
        ("七项能力规范", "行为合同，不固定接口形状"),
    ]
    for i, (title, sub) in enumerate(inputs):
        y = 349 - i * 66
        rounded_box(c, 60, y, 214, 52, fill="#F5F8FE", stroke="#D9E6FA", radius=10)
        draw_text(c, 74, y + 29, title, size=11, fill=NAVY, font="NotoBold")
        draw_text(c, 74, y + 11, sub, size=8.5, fill=MUTED)

    arrow(c, 300, 272, 354, 272, stroke=BLUE, width=3)
    set_fill(c, BLUE)
    c.circle(386, 272, 31, fill=1, stroke=0)
    draw_text(c, 386, 266, "分析", size=13, fill=WHITE, font="NotoBold", align="center")
    arrow(c, 418, 272, 472, 272, stroke=BLUE, width=3)

    rounded_box(c, 480, 100, 432, 344, fill=WHITE)
    draw_text(c, 500, 412, "输出：能力矩阵 + 证据 + 路径", size=18, fill=BLUE_DARK, font="NotoBold")
    rows = [
        ("SUPPORTED", "接口已完整存在", GREEN),
        ("PATCHABLE", "可低侵入补齐", TEAL),
        ("PARTIAL", "部分存在", AMBER),
        ("INVASIVE", "需要改变核心语义", CORAL),
        ("UNKNOWN", "证据不足", PURPLE),
        ("NOT_APPLICABLE", "边界内不适用", MUTED),
    ]
    for i, (status, meaning, accent) in enumerate(rows):
        y = 355 - i * 36
        badge(c, 502, y, status, fill=accent, width=124)
        draw_text(c, 646, y + 7, meaning, size=10.5, fill=INK)
    rounded_box(c, 500, 116, 388, 42, fill=NAVY_2, stroke=None, radius=10)
    draw_text(c, 694, 130, "每个正向结论必须定位到文件或符号", size=10.5, fill=WHITE, align="center")
    footer_source(c, "Analyzer 发现 Node / RawNode / 同步 / 异步等实质路径；人工不预先指定内部实现路线")
    c.showPage()


def slide_agent2(c: canvas.Canvas) -> None:
    page_header(c, "Agent 2：按能力生成目标原生接口", "05 Agent 2 输入 / 输出", 6)
    # 三段流水线。
    rounded_box(c, 40, 104, 248, 340, fill=WHITE)
    draw_text(c, 60, 411, "输入", size=18, fill=TEAL_DARK, font="NotoBold")
    for i, text in enumerate(("PATCHABLE 能力子集", "Analyzer 证据与建议", "目标修改策略", "Reviewer / 构建反馈", "已有候选代码（修订时）")):
        badge(c, 60, 357 - i * 46, text, fill="#E3F8F5", text_fill=TEAL_DARK, width=208)

    arrow(c, 297, 274, 338, 274, stroke=TEAL, width=3)
    rounded_box(c, 346, 104, 254, 340, fill=NAVY_2, stroke=None, radius=18)
    draw_text(c, 366, 411, "隔离工具循环", size=18, fill=WHITE, font="NotoBold")
    tools = [
        ("读", "read / search / symbol"),
        ("写", "apply_patch / write_file"),
        ("验", "go test / compile / doc"),
    ]
    for i, (mark, text) in enumerate(tools):
        y = 337 - i * 70
        set_fill(c, (BLUE, TEAL, AMBER)[i])
        c.circle(382, y + 14, 18, fill=1, stroke=0)
        draw_text(c, 382, y + 8, mark, size=12, fill=WHITE, font="NotoBold", align="center")
        draw_text(c, 414, y + 8, text, size=11, fill=WHITE)
    rounded_box(c, 366, 126, 214, 56, fill="#203765", stroke=None, radius=10)
    draw_text(c, 473, 157, "每项能力独立预算", size=11, fill=CYAN, font="NotoBold", align="center")
    draw_text(c, 473, 137, "修改累积在同一候选中", size=9, fill="#C8D4ED", align="center")

    arrow(c, 609, 274, 650, 274, stroke=TEAL, width=3)
    rounded_box(c, 658, 104, 262, 340, fill=WHITE)
    draw_text(c, 678, 411, "输出", size=18, fill=TEAL_DARK, font="NotoBold")
    outputs = [
        ("目标原生代码", "wrapper / hook / config / accessor"),
        ("新增目标语言测试", "不修改既有测试"),
        ("接口报告", "入口、覆盖路径、剩余限制"),
        ("候选补丁", "原仓库保持不变"),
    ]
    for i, (title, sub) in enumerate(outputs):
        y = 343 - i * 62
        rounded_box(c, 678, y, 222, 49, fill="#F5F8FE", stroke="#D9E6FA", radius=10)
        draw_text(c, 692, y + 27, title, size=10.5, fill=NAVY, font="NotoBold")
        draw_text(c, 692, y + 10, sub, size=8, fill=MUTED)
    footer_source(c, "通用要求：可调用范围｜快照安全｜状态一致性｜成功/消费语义｜配置合法域")
    c.showPage()


def slide_agent3(c: canvas.Canvas) -> None:
    page_header(c, "Agent 3：把静态审查变成自动反馈回路", "06 Agent 3 输入 / 输出", 7)
    # 输入双视图。
    rounded_box(c, 42, 304, 196, 112, fill=WHITE, stroke=BLUE)
    draw_text(c, 140, 380, "原始源码", size=15, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 140, 350, "original scope", size=10, fill=MUTED, align="center")
    rounded_box(c, 264, 304, 196, 112, fill=WHITE, stroke=TEAL)
    draw_text(c, 362, 380, "候选源码", size=15, fill=TEAL_DARK, font="NotoBold", align="center")
    draw_text(c, 362, 350, "patched scope + diff", size=10, fill=MUTED, align="center")
    arrow(c, 238, 360, 258, 360, stroke=MUTED, width=1.5)

    rounded_box(c, 498, 276, 420, 168, fill=NAVY_2, stroke=None, radius=18)
    draw_text(c, 520, 412, "五类核心检查", size=17, fill=WHITE, font="NotoBold")
    checks = [
        "路径与入口是否真实可达",
        "消息目标和协议逻辑是否保持",
        "快照别名与控制状态是否安全",
        "成功、失败与消息消费是否一致",
        "配置值是否遵守目标合法域",
    ]
    for i, text in enumerate(checks):
        set_fill(c, (BLUE, TEAL, PURPLE, CORAL, AMBER)[i])
        c.circle(528, 376 - i * 23, 4, fill=1, stroke=0)
        draw_text(c, 542, 371 - i * 23, text, size=10.5, fill=WHITE)

    # 路由输出。
    draw_text(c, 42, 244, "审查输出与自动路由", size=15, fill=NAVY, font="NotoBold")
    routes = [
        (42, "REVISE_AGENT1", "分类 / 边界错误", BLUE, "回到分析"),
        (266, "REVISE_AGENT2", "实现 / 声明错误", CORAL, "续修候选"),
        (490, "NEEDS_HUMAN", "源码证据不足", PURPLE, "停止并说明"),
        (714, "PASS + risks", "仅非阻塞限制", GREEN, "产出候选"),
    ]
    for x, status, reason, accent, action in routes:
        rounded_box(c, x, 104, 204, 112, fill=WHITE, stroke=accent, radius=14, width=1.5)
        badge(c, x + 12, 174, status, fill=accent, width=180)
        draw_text(c, x + 102, 143, reason, size=10, fill=INK, font="NotoBold", align="center")
        draw_text(c, x + 102, 121, action, size=9, fill=MUTED, align="center")
    footer_source(c, "原则：不能把接口不可达、状态失同步或未确认投递藏在 PASS.risks 中")
    c.showPage()


def slide_artifacts(c: canvas.Canvas) -> None:
    page_header(c, "产物链：从修改前事实到修改后可用说明", "07 可审计产物", 8)
    stages = [
        (54, "① 修改前", "capability-report.json", BLUE, ["能力分类", "源码证据", "发现的路径", "原始缺口"]),
        (350, "② 修改后", "interface-report.json", TEAL, ["真实入口", "覆盖 / 未覆盖", "使用前提", "剩余限制"]),
        (646, "③ 独立审查", "review-report.json", PURPLE, ["阻塞 issues", "非阻塞 risks", "路由决定", "代码证据"]),
    ]
    for x, title, filename, accent, items in stages:
        rounded_box(c, x, 208, 252, 220, fill=WHITE, stroke=accent, radius=16, width=1.5)
        draw_text(c, x + 18, 394, title, size=16, fill=accent, font="NotoBold")
        badge(c, x + 18, 354, filename, fill="#EDF2FA", text_fill=NAVY, width=216)
        for i, item in enumerate(items):
            set_fill(c, accent)
            c.circle(x + 26, 317 - i * 31, 4, fill=1, stroke=0)
            draw_text(c, x + 40, 312 - i * 31, item, size=10.5, fill=INK)
    arrow(c, 310, 318, 342, 318, stroke=MUTED, width=2)
    arrow(c, 606, 318, 638, 318, stroke=MUTED, width=2)

    rounded_box(c, 54, 88, 844, 86, fill=NAVY_2, stroke=None, radius=16)
    draw_text(c, 80, 143, "USAGE.md｜面向使用者的最终视图", size=17, fill=WHITE, font="NotoBold")
    draw_text(c, 80, 115, "中文结构明确区分：修改前分析 → 本次生成接口 → 修改后剩余限制 → Reviewer 结论", size=11, fill="#C8D4ED")
    badge(c, 744, 118, "changes.patch", fill=TEAL, width=132)
    footer_source(c, "每次运行还记录模型成本、工具审计、补丁规模、构建日志与目标 revision")
    c.showPage()


def slide_etcd_setup(c: canvas.Canvas) -> None:
    page_header(c, "etcd/raft 3.6：不预设 API 形状的真实目标", "08 实验设置", 9)
    rounded_box(c, 42, 108, 610, 348, fill=WHITE, stroke=BLUE, radius=18, width=1.5)
    draw_text(c, 64, 421, "系统边界内｜go.etcd.io/raft/v3", size=17, fill=BLUE_DARK, font="NotoBold")
    paths = [
        ("RawNode 同步路径", "Tick / Step / Ready / Advance", BLUE),
        ("Node 异步路径", "channel + run goroutine", TEAL),
        ("AsyncStorageWrites", "Append / Apply 工作线程消息", PURPLE),
        ("rafttest 支持层", "InteractionEnv + 内部 node harness", AMBER),
    ]
    for i, (title, sub, accent) in enumerate(paths):
        y = 345 - i * 64
        rounded_box(c, 66, y, 562, 50, fill="#F7F9FD", stroke="#E0E7F2", radius=10)
        rounded_box(c, 66, y, 7, 50, fill=accent, stroke=None, radius=3)
        draw_text(c, 86, y + 27, title, size=11.5, fill=NAVY, font="NotoBold")
        draw_text(c, 282, y + 27, sub, size=9.5, fill=MUTED)

    rounded_box(c, 684, 280, 234, 176, fill="#FFF4F1", stroke="#FFD0C8", radius=16)
    draw_text(c, 704, 421, "边界外", size=16, fill=CORAL, font="NotoBold")
    for i, text in enumerate(("真实网络 / RPC", "外部 WAL 与磁盘", "应用状态机", "完整 etcd server")):
        set_fill(c, CORAL)
        c.circle(712, 382 - i * 31, 4, fill=1, stroke=0)
        draw_text(c, 726, 377 - i * 31, text, size=10.5, fill=INK)

    rounded_box(c, 684, 108, 234, 140, fill=NAVY_2, stroke=None, radius=16)
    draw_text(c, 704, 215, "实验约束", size=15, fill=WHITE, font="NotoBold")
    for i, text in enumerate(("无人工 ground truth", "无预设 etcd 专属 API", "无 capability checks", "固定提交 9118047")):
        badge(c, 704, 183 - i * 25, text, fill="#203765", text_fill="#D8E4FF", width=194)
    footer_source(c, "命令：consensus-seam patch｜Analyzer 自行发现 Node / RawNode / 异步存储路径")
    c.showPage()


def slide_etcd_results(c: canvas.Canvas) -> None:
    page_header(c, "etcd 实验结果：4 项复用，3 项自动补齐", "09 能力结果", 10)
    # 能力矩阵。
    rounded_box(c, 42, 106, 490, 350, fill=WHITE)
    draw_text(c, 62, 423, "七项能力矩阵", size=17, fill=NAVY, font="NotoBold")
    rows = [
        ("消息捕获", "PATCHABLE → 已生成", TEAL),
        ("消息注入", "PATCHABLE → 已生成", TEAL),
        ("时间控制", "SUPPORTED", GREEN),
        ("随机性控制", "PATCHABLE → 已生成", TEAL),
        ("生命周期控制", "SUPPORTED", GREEN),
        ("状态观察", "SUPPORTED", GREEN),
        ("外部输入", "SUPPORTED", GREEN),
    ]
    for i, (capability, status, accent) in enumerate(rows):
        y = 374 - i * 39
        draw_text(c, 66, y + 6, capability, size=10.5, fill=INK, font="NotoBold")
        badge(c, 240, y, status, fill=accent, width=260)

    # 右侧比例与接口卡。
    rounded_box(c, 558, 106, 360, 350, fill=WHITE)
    draw_text(c, 578, 423, "自动生成的目标原生接口", size=17, fill=NAVY, font="NotoBold")
    # 4/3 条形比例。
    draw_text(c, 578, 385, "能力构成", size=10, fill=MUTED)
    rounded_box(c, 578, 351, 318, 24, fill="#E7EEF8", stroke=None, radius=12)
    rounded_box(c, 578, 351, 182, 24, fill=GREEN, stroke=None, radius=12)
    rounded_box(c, 760, 351, 136, 24, fill=TEAL, stroke=None, radius=12)
    draw_text(c, 669, 357, "4 项已有", size=9, fill=WHITE, font="NotoBold", align="center")
    draw_text(c, 828, 357, "3 项生成", size=9, fill=WHITE, font="NotoBold", align="center")

    interface_cards = [
        ("ListPending / ClearPending", "稳定控制 ID + 捕获顺序", TEAL),
        ("InjectByID", "按 ID 进入 RawNode.Step", BLUE),
        ("RandomizedElectionTimeout", "Config 固定选举超时", PURPLE),
    ]
    for i, (name, sub, accent) in enumerate(interface_cards):
        y = 277 - i * 70
        rounded_box(c, 578, y, 318, 56, fill="#F7F9FD", stroke="#DFE6F1", radius=11)
        rounded_box(c, 578, y, 7, 56, fill=accent, stroke=None, radius=3)
        draw_text(c, 596, y + 31, name, size=11, fill=NAVY, font="NotoBold")
        draw_text(c, 596, y + 12, sub, size=8.5, fill=MUTED)
    footer_source(c, "结论：生成策略适配 etcd 的 rafttest 与 Config，没有复刻 Mini Raft 的 Transport Controller")
    c.showPage()


def slide_etcd_code(c: canvas.Canvas) -> None:
    page_header(c, "生成代码如何接入 etcd 原有路径", "10 接口结构", 11)
    # 消息控制主图。
    draw_text(c, 48, 430, "消息控制：复用 Ready / Step，不直接改协议状态", size=16, fill=NAVY, font="NotoBold")
    sources = [
        (50, "Ready.Messages", BLUE),
        (50, "Append / Apply 响应", PURPLE),
        (50, "SendSnapshot", AMBER),
    ]
    for i, (x, label, accent) in enumerate(sources):
        y = 354 - i * 54
        rounded_box(c, x, y, 170, 40, fill=WHITE, stroke=accent, radius=10)
        draw_text(c, x + 85, y + 13, label, size=9.5, fill=INK, font="NotoBold", align="center")
        arrow(c, x + 170, y + 20, 278, 327, stroke=accent, width=1.8)

    rounded_box(c, 286, 278, 180, 96, fill="#E3F8F5", stroke=TEAL, radius=14)
    draw_text(c, 376, 340, "capturePending", size=13, fill=TEAL_DARK, font="NotoBold", align="center")
    draw_text(c, 376, 314, "PendingMessage", size=10, fill=INK, align="center")
    draw_text(c, 376, 293, "{ ID, Msg }", size=10, fill=MUTED, align="center")

    arrow(c, 466, 326, 522, 326, stroke=TEAL, width=2.5)
    rounded_box(c, 530, 278, 174, 96, fill=WHITE, stroke=BLUE, radius=14)
    draw_text(c, 617, 340, "ListPending", size=11.5, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 617, 312, "ClearPending", size=11.5, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 617, 290, "测试侧选择 ID", size=8.5, fill=MUTED, align="center")

    arrow(c, 704, 326, 756, 326, stroke=BLUE, width=2.5)
    rounded_box(c, 764, 278, 150, 96, fill="#EEF6FF", stroke=BLUE, radius=14)
    draw_text(c, 839, 340, "InjectByID", size=12, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 839, 312, "目标绑定", size=9.5, fill=INK, align="center")
    draw_text(c, 839, 290, "RawNode.Step", size=9.5, fill=MUTED, align="center")

    # 随机性控制支线。
    draw_text(c, 48, 221, "随机性控制：默认路径不变，测试配置显式启用", size=16, fill=NAVY, font="NotoBold")
    boxes = [
        (50, "Config", "RandomizedElectionTimeout", PURPLE),
        (330, "newRaft", "保存固定标志与数值", BLUE),
        (610, "reset", "固定值 / 原 globalRand", TEAL),
    ]
    for i, (x, title, sub, accent) in enumerate(boxes):
        rounded_box(c, x, 110, 244, 72, fill=WHITE, stroke=accent, radius=13)
        draw_text(c, x + 122, 154, title, size=12, fill=accent, font="NotoBold", align="center")
        draw_text(c, x + 122, 127, sub, size=9, fill=MUTED, align="center")
        if i < len(boxes) - 1:
            arrow(c, x + 244, 146, x + 272, 146, stroke=accent, width=2)
    footer_source(c, "生成位置：rafttest/pending_msgs.go｜rafttest/inject.go｜raft.go Config")
    c.showPage()


def slide_validation(c: canvas.Canvas) -> None:
    page_header(c, "工程效果与当前边界：候选成立，但仍需诚实标注质量层级", "11 结果与启示", 12)
    # 左侧指标。
    rounded_box(c, 42, 108, 394, 346, fill=WHITE)
    draw_text(c, 62, 420, "代码与验证", size=17, fill=NAVY, font="NotoBold")
    metric_card(c, 62, 330, 164, "+290 / -12", "生产代码行", TEAL)
    metric_card(c, 246, 330, 164, "+481", "新增测试行", BLUE)
    metric_card(c, 62, 240, 164, "14", "候选变更文件", PURPLE)
    metric_card(c, 246, 240, 164, "20×", "异步测试重复通过", GREEN)
    rounded_box(c, 62, 142, 348, 70, fill="#ECFDF5", stroke="#B7E7C6", radius=12)
    draw_text(c, 82, 184, "完整 go test ./...：全部通过", size=12, fill=GREEN_DARK, font="NotoBold")
    draw_text(c, 82, 159, "Reviewer：PASS（同时报告 5 项 risk）", size=10, fill=INK)

    # 右侧从问题到通用改进。
    rounded_box(c, 462, 108, 456, 346, fill=WHITE)
    draw_text(c, 482, 420, "实验暴露的关键问题 → 通用规则", size=17, fill=NAVY, font="NotoBold")
    findings = [
        ("入口不可达", "声明 external / 同包 / 内部范围", BLUE),
        ("双存储失同步", "统一事实来源，覆盖所有修改入口", TEAL),
        ("异步发送即消费", "成功必须对应真实输入接受", CORAL),
        ("浅复制 / 越界值", "快照安全 + 合法值域", PURPLE),
    ]
    for i, (problem, rule, accent) in enumerate(findings):
        y = 360 - i * 54
        rounded_box(c, 482, y, 416, 48, fill="#F7F9FD", stroke="#E0E7F2", radius=10)
        badge(c, 492, y + 12, problem, fill=accent, width=116)
        arrow(c, 616, y + 24, 646, y + 24, stroke=MUTED, width=1.5)
        draw_text(c, 658, y + 18, rule, size=9.5, fill=INK, font="NotoBold")
    rounded_box(c, 482, 118, 416, 50, fill=NAVY_2, stroke=None, radius=11)
    draw_text(c, 690, 146, "Agent 3 阻塞问题自动反馈；repair 保持可选", size=11, fill=WHITE, font="NotoBold", align="center")
    draw_text(c, 690, 128, "当前定位：可运行、可审计、可继续自动迭代", size=8.5, fill="#C8D4ED", align="center")
    footer_source(c, "实验成本：198 次 API｜308 次工具调用｜约 37.4 分钟 Agent 墙钟时间（优化重点）")
    c.showPage()


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("ConsensusSeam：流程架构与 etcd/raft 实验展示")
    c.setAuthor("ConsensusSeam")
    slide_cover(c)
    slide_problem(c)
    slide_architecture(c)
    slide_roles(c)
    slide_agent1(c)
    slide_agent2(c)
    slide_agent3(c)
    slide_artifacts(c)
    slide_etcd_setup(c)
    slide_etcd_results(c)
    slide_etcd_code(c)
    slide_validation(c)
    c.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
