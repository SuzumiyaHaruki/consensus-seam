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
TOTAL_PAGES = 19

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

    badge(c, 56, 458, "多 Agent 共识测试控制面生成", fill=TEAL)
    draw_text(c, 56, 380, "ConsensusSeam", size=46, fill=WHITE, font="Helvetica-Bold")
    draw_text(c, 56, 337, "从源码能力分析到测试控制面", size=26, fill="#B9E7E2", font="NotoBold")
    draw_text(
        c,
        58,
        292,
        "当前研究目标｜七项能力合同｜Agent 输入输出｜最新 etcd/raft 3.6 实验",
        size=13.5,
        fill="#C8D4ED",
    )

    metric_card(c, 56, 145, 154, "7", "固定分析维度", TEAL)
    metric_card(c, 226, 145, 154, "4", "本轮判为 PATCHABLE", BLUE)
    metric_card(c, 396, 145, 154, "未完成", "最新实验结论", CORAL)
    draw_text(c, 58, 92, "目标 9118047｜实验 Controller 858eff8｜当前框架 96ca621｜2026-08-28", size=9.5, fill="#8FA4CF")
    draw_text(c, 904, 30, f"01 / {TOTAL_PAGES:02d}", size=9, fill="#8FA4CF", align="right")
    c.showPage()


def slide_problem(c: canvas.Canvas) -> None:
    page_header(c, "研究目标转变：七项是分析维度，不是生成清单", "01 当前思路", 2)
    rounded_box(c, 48, 250, 354, 178, fill="#FFF4F1", stroke="#FFD0C8")
    card_title(c, 66, 384, "旧", "容易走偏的理解", CORAL)
    for i, text in enumerate(("七项能力都要新增代码", "人工先指定目标内部路径", "接口承担选择与调度策略", "为统一形式重复包装")):
        badge(c, 76, 345 - i * 31, text, fill="#FFE5DF", text_fill="#B6382B", width=296)

    arrow(c, 414, 337, 538, 337, stroke=TEAL, width=3)
    badge(c, 425, 350, "研究收敛", fill=TEAL, width=102)

    rounded_box(c, 550, 250, 362, 178, fill="#ECFDF8", stroke="#A8E5D9")
    card_title(c, 568, 384, "新", "当前职责边界", TEAL)
    for i, text in enumerate(("已有功能 → 易用包装 + 清晰清单", "功能缺失 → 最小侵入实现", "Agent 自行发现真实路径", "选择 / 调度 / 判定交给测试方")):
        badge(c, 578, 345 - i * 31, text, fill="#D8F7EF", text_fill=TEAL_DARK, width=304)

    draw_text(c, 50, 206, "v0.1 固定分析对象：七项基础能力", size=15, fill=NAVY, font="NotoBold")
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
    draw_text(c, 481, 91, "统一测试接口名称与语义；节点 ID、消息和状态仍采用目标原生类型，内部实现由源码决定。", size=11.5, fill=WHITE, align="center")
    footer_source(c, "研究边界：为测试提供规范控制能力；测试策略、故障计划和正确性 oracle 仍由测试方负责")
    c.showPage()


CAPABILITY_DETAILS = (
    {
        "title": "消息捕获：先进入测试可控缓存，再决定是否继续",
        "slug": "message_capture",
        "goal": "协议输出在自动沿原路径继续之前被拦截，并作为具体消息实例保留在测试可见的权威缓存中。",
        "flow": (
            ("发现输出路径", "从源码识别所有实质不同的消息出口", BLUE),
            ("拦截", "默认不再自动发送或处理受控消息", CORAL),
            ("持续缓存", "实例保留到显式消费、删除或清空", TEAL),
            ("枚举与引用", "返回消息快照、顺序和实例引用", PURPLE),
        ),
        "operations": (
            "启用或暴露捕获，并说明需要的构造器、hook 或测试环境",
            "枚举缓存：看到目标原生消息内容、当前顺序与消费者范围",
            "获得实例引用：仍命中原实例，或明确报告引用过期",
            "使用 Pending 查看、Drop 精确删除、Clear 清空",
        ),
        "complete": "所有声明支持的路径都有同一套可控缓存语义；返回快照不会反向修改内部状态。",
        "boundary": "测试方按消息内容选择并制定调度策略；系统不替测试方决定丢弃、延迟或重排哪条消息。",
    },
    {
        "title": "消息注入：指定同一缓存实例，进入真实协议入口",
        "slug": "message_injection",
        "goal": "测试方指定一个已经捕获的合法消息实例，并将它交给记录目标的正常协议输入边界。",
        "flow": (
            ("查看并选择", "测试按目标原生内容选择消息", BLUE),
            ("定位实例", "使用枚举返回的 handle、record 或 token", PURPLE),
            ("绑定目标", "解析真实对象，或校验调用方目标匹配", AMBER),
            ("正常输入", "通过 Step、receive 或目标原生入口投递", TEAL),
        ),
        "operations": (
            "统一 Inject(handle)，由 Controller 绑定目标并调用正常输入",
            "明确注入成功时消息是否已从权威缓存移除",
            "明确同步错误、异步未确认、重试与重新入队的责任边界",
            "报告外部调用、同包测试或内部 harness 各自可用的入口",
        ),
        "complete": "捕获与注入属于同一声明路径；普通输入函数只有与该路径的缓存实例建立明确关系后才算完整。",
        "boundary": "分离式可由测试方持有目标关系；组合式负责目标绑定。选择、时机和重试仍由测试方决定。",
    },
    {
        "title": "时间控制：确定性推进协议时间，不直接制造结果",
        "slug": "time_control",
        "goal": "测试代码能够确定性推进协议观察到的时间，并知道推进作用于哪个对象以及何时完成。",
        "flow": (
            ("发现时间源", "识别 Tick、Clock、timer 与异步推进路径", BLUE),
            ("复用或注入", "直接复用 Tick，或注入可控 Clock", TEAL),
            ("确定性推进", "按合法步数推进节点或声明的范围", PURPLE),
            ("观察完成", "说明同步返回或异步协调边界", GREEN),
        ),
        "operations": (
            "通过统一 Advance(steps) 逐步推进所有运行节点",
            "多节点或多时间源存在时，可提供薄协调包装",
            "说明控制范围：单节点、节点集合或特定时钟实例",
            "拒绝非法控制值，不创建目标原本不允许的状态",
        ),
        "complete": "已有 Tick 或 Clock 可以被测试直接、重复、确定性调用时即可复用，不因缺少统一包装而重复生成。",
        "boundary": "不提供 ForceElection、ForceTimeout 等直接制造协议结果的捷径；测试方决定推进节奏和断言。",
    },
    {
        "title": "随机性控制：固定协议随机选择，同时保持生产默认行为",
        "slug": "randomness_control",
        "goal": "相同初始状态和相同控制参数能够重复协议相关随机选择，且不替换目标已有随机算法。",
        "flow": (
            ("发现随机点", "定位选举超时等协议相关选择", BLUE),
            ("选择控制形态", "固定值、seed、随机源或测试构造器", PURPLE),
            ("校验值域", "沿用目标合法范围或显式定义测试域", AMBER),
            ("验证可重复", "声明作用范围、初始化时机与复现条件", GREEN),
        ),
        "operations": (
            "在构造或配置阶段设置固定值、种子或注入随机源",
            "说明控制是每节点、每实例还是整个系统共享",
            "未启用控制时保持原生产随机路径和默认值",
            "所有协议相关随机入口都应被发现；未覆盖路径必须列出",
        ),
        "complete": "接口真正影响目标使用的随机选择，并在同等前提下可复现；已有可测试配置足够时直接列入清单。",
        "boundary": "系统提供可重复性，不替测试方挑选“更容易通过”的随机结果，也不新增第二套随机算法。",
    },
    {
        "title": "生命周期控制：让节点不可用并恢复，但如实命名语义",
        "slug": "lifecycle_control",
        "goal": "测试可以通过目标已有边界使节点暂时不可用，并在之后恢复可用；第一版只要求可用性控制。",
        "flow": (
            ("识别停止边界", "pause、graceful stop、停止调度或外部进程", BLUE),
            ("进入不可用", "说明是否仍保留同一对象与内存状态", CORAL),
            ("识别恢复边界", "resume、restart、重建或重新调度", PURPLE),
            ("恢复可用", "说明同实例恢复还是由持有状态重建", GREEN),
        ),
        "operations": (
            "暴露或清晰列出 make-unavailable 与 restore 两个可调用动作",
            "说明实际机制：暂停、优雅停止、重建或进程级控制",
            "记录恢复后对象身份，以及目标定义的状态所有权",
            "只有目标明确时才声明持久状态、易失状态和 crash fidelity",
        ),
        "complete": "已有入口可以由测试直接组合完成不可用与恢复时即已满足；缺少 convenience wrapper 本身不是缺口。",
        "boundary": "stop、pause 和生产 crash 不是同义词；系统不发明目标未定义的磁盘、内存或恢复语义。",
    },
    {
        "title": "状态观察：提供安全快照，不替测试方定义正确性",
        "slug": "observation",
        "goal": "向测试暴露验证控制效果所需的最小节点或全局状态，同时保持字段和语义目标原生。",
        "flow": (
            ("发现状态来源", "Status、BasicStatus、日志或进度入口", BLUE),
            ("直接复用", "单一现有接口足够时不增加代码", GREEN),
            ("必要时聚合", "只读 accessor 汇总分散的已有状态", TEAL),
            ("返回安全快照", "复制可变切片、指针与嵌套对象", PURPLE),
        ),
        "operations": (
            "查询一个节点或声明范围的当前状态",
            "保留目标字段，例如角色、任期、commit、applied 或日志范围",
            "说明入口的调用范围和返回对象的快照语义",
            "调用方不能通过返回值意外修改协议或控制器内部状态",
        ),
        "complete": "现有 Status 已经满足测试观察时直接报告其用法；只有状态分散或不可安全访问时才增加薄包装。",
        "boundary": "v0.1 不规定统一状态 Schema，也不生成共识正确性 oracle；测试方选择观察字段并编写断言。",
    },
    {
        "title": "外部输入：发现工作负载入口，不创建新的业务 API",
        "slug": "external_input",
        "goal": "定位应用从协议外部提交工作的现有入口，为测试方给出清晰可调用清单。",
        "flow": (
            ("寻找工作来源", "proposal、read request、transaction 或成员变更", BLUE),
            ("核对真实入口", "定位公开函数、通道、请求对象与调用范围", TEAL),
            ("排除内部事件", "排除 peer 消息、Tick、timer 与内部 callback", CORAL),
            ("生成使用清单", "记录参数、前提、返回或异步完成方式", AMBER),
        ),
        "operations": (
            "列出目标已有 workload entrypoint 及其源码证据",
            "说明调用者需要的节点对象、上下文、载荷与初始化前提",
            "区分应用输入和点对点协议 ingress，避免把 Step 当业务入口",
            "报告多条应用路径和使用范围；不能只列最容易发现的一条",
        ),
        "complete": "边界内工作负载入口已经被发现、分类并形成可操作说明；该能力在 v0.1 中只分析、不进入 Agent 2。",
        "boundary": "不生成新的 proposal 或 transaction 语义，不负责构造业务负载、调度请求或判断应用结果。",
    },
)


def slide_capability_detail(c: canvas.Canvas, detail: dict[str, object], index: int, page: int) -> None:
    title = str(detail["title"])
    slug = str(detail["slug"])
    page_header(c, title, f"02 能力合同 · {index}/7  {slug}", page)

    rounded_box(c, 42, 410, 876, 46, fill=NAVY_2, stroke=None, radius=12)
    badge(c, 56, 421, "能力目标", fill=TEAL, width=78)
    draw_text(c, 150, 426, str(detail["goal"]), size=9.6, fill=WHITE, max_width=742, leading=12)

    draw_text(c, 44, 384, "从源码到测试接口的功能链", size=13, fill=NAVY, font="NotoBold")
    flow = detail["flow"]
    assert isinstance(flow, tuple)
    for i, (label, sub, accent) in enumerate(flow):
        x = 42 + i * 223
        rounded_box(c, x, 288, 204, 76, fill=WHITE, stroke=str(accent), radius=12, width=1.3)
        badge(c, x + 12, 329, str(label), fill=str(accent), width=180)
        draw_text(c, x + 18, 310, str(sub), size=8.2, fill=MUTED, max_width=168, leading=10)
        if i < 3:
            arrow(c, x + 205, 326, x + 219, 326, stroke=MUTED, width=1.4, head=5)

    rounded_box(c, 42, 82, 520, 168, fill=WHITE, stroke="#D9E6FA", radius=14)
    draw_text(c, 62, 222, "测试方应获得的操作能力", size=14, fill=BLUE_DARK, font="NotoBold")
    operations = detail["operations"]
    assert isinstance(operations, tuple)
    for i, item in enumerate(operations):
        set_fill(c, (BLUE, TEAL, PURPLE, AMBER)[i])
        c.circle(68, 191 - i * 32, 4, fill=1, stroke=0)
        draw_text(c, 82, 186 - i * 32, str(item), size=9.1, fill=INK, max_width=456, leading=11)

    rounded_box(c, 582, 168, 336, 82, fill="#ECFDF8", stroke="#A8E5D9", radius=13)
    draw_text(c, 600, 224, "什么时候才算完整", size=12.5, fill=TEAL_DARK, font="NotoBold")
    draw_text(c, 600, 202, str(detail["complete"]), size=8.6, fill=INK, max_width=298, leading=10.5)
    rounded_box(c, 582, 82, 336, 76, fill="#FFF4F1", stroke="#FFD0C8", radius=13)
    draw_text(c, 600, 132, "职责边界", size=12.5, fill=CORAL, font="NotoBold")
    draw_text(c, 600, 110, str(detail["boundary"]), size=8.6, fill=INK, max_width=298, leading=10.5)
    footer_source(c, "能力合同规定可测试行为，不规定统一类型、函数名、节点结构或实现路径数量；具体入口由 Agent 从目标源码发现")
    c.showPage()


def slide_architecture(c: canvas.Canvas) -> None:
    page_header(c, "整体流程：分析已有能力，只为真实缺口生成代码", "03 系统架构", 10)
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
        (228, 255, 134, "Agent 2", "按真实缺口生成", TEAL),
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
    badge(c, 424, 197, "REVISE_AGENT2：只重跑受影响能力", fill=CORAL, width=270)
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
    footer_source(c, "消息捕获与注入共享一次 Transformer 调用；其余能力逐项处理；repair 仍是可选后置流程")
    c.showPage()


def slide_roles(c: canvas.Canvas) -> None:
    page_header(c, "三个 Agent：职责隔离，信息逐步收敛", "04 Agent 协作", 11)
    columns = [
        (46, "Agent 1｜能力分析", BLUE, "只读源码", ["发现目标真实执行路径", "区分原语 / 完整测试接口", "用证据给出六种状态"], "capability-report.json"),
        (354, "Agent 2｜低侵入生成", TEAL, "隔离 worktree", ["只处理 PATCHABLE 能力", "消息两项联合设计", "生成目标原生接口与测试"], "interface-report.json\nchanges.patch"),
        (662, "Agent 3｜独立审查", PURPLE, "原始 + 候选只读", ["核对路径、引用与目标绑定", "区分阻塞 issue / 剩余 risk", "只反馈受影响能力"], "review-report.json"),
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
    footer_source(c, "隔离原则不变：Agent 1 不写代码；Agent 2 不修改原仓库；Agent 3 不修改候选")
    c.showPage()


def slide_agent1(c: canvas.Canvas) -> None:
    page_header(c, "Agent 1：从源码证据生成七项能力地图", "05 Agent 1 输入 / 输出", 12)
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
    footer_source(c, "消息能力要求每条声明支持的路径都有显式缓存控制面；生命周期允许组合已有调度与重建入口")
    c.showPage()


def slide_agent2(c: canvas.Canvas) -> None:
    page_header(c, "Agent 2：为真实缺口生成目标原生控制面", "06 Agent 2 输入 / 输出", 13)
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
    draw_text(c, 473, 157, "消息捕获 + 注入联合", size=11, fill=CYAN, font="NotoBold", align="center")
    draw_text(c, 473, 137, "其余能力逐项预算", size=9, fill="#C8D4ED", align="center")

    arrow(c, 609, 274, 650, 274, stroke=TEAL, width=3)
    rounded_box(c, 658, 104, 262, 340, fill=WHITE)
    draw_text(c, 678, 411, "输出", size=18, fill=TEAL_DARK, font="NotoBold")
    outputs = [
        ("目标原生代码", "wrapper / hook / config / accessor"),
        ("新增目标语言测试", "不修改既有测试"),
        ("接口报告", "引用有效期、路由归属、缓存语义"),
        ("候选补丁", "原仓库保持不变"),
    ]
    for i, (title, sub) in enumerate(outputs):
        y = 343 - i * 62
        rounded_box(c, 678, y, 222, 49, fill="#F5F8FE", stroke="#D9E6FA", radius=10)
        draw_text(c, 692, y + 27, title, size=10.5, fill=NAVY, font="NotoBold")
        draw_text(c, 692, y + 10, sub, size=8, fill=MUTED)
    footer_source(c, "通用要求：快照安全｜引用或过期检测｜同路径缓存与输入｜成功与消费语义｜合法值域")
    c.showPage()


def slide_agent3(c: canvas.Canvas) -> None:
    page_header(c, "Agent 3：把静态审查变成自动反馈回路", "07 Agent 3 输入 / 输出", 14)
    # 输入双视图。
    rounded_box(c, 42, 304, 196, 112, fill=WHITE, stroke=BLUE)
    draw_text(c, 140, 380, "原始源码", size=15, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 140, 350, "original scope", size=10, fill=MUTED, align="center")
    rounded_box(c, 264, 304, 196, 112, fill=WHITE, stroke=TEAL)
    draw_text(c, 362, 380, "候选源码", size=15, fill=TEAL_DARK, font="NotoBold", align="center")
    draw_text(c, 362, 350, "patched scope + diff", size=10, fill=MUTED, align="center")
    arrow(c, 238, 360, 258, 360, stroke=MUTED, width=1.5)

    rounded_box(c, 498, 276, 420, 168, fill=NAVY_2, stroke=None, radius=18)
    draw_text(c, 520, 412, "核心检查", size=17, fill=WHITE, font="NotoBold")
    checks = [
        "路径与入口是否真实可达",
        "缓存、handle 与真实目标是否一致",
        "快照别名与控制状态是否安全",
        "成功、失败与消息消费是否一致",
        "配置值、示例和调用范围是否真实",
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
    footer_source(c, "原则：阻塞问题必须进入 issues；Reviewer 修订只重跑问题涉及的能力，其他接口报告由 Controller 保留")
    c.showPage()


def slide_artifacts(c: canvas.Canvas) -> None:
    page_header(c, "产物链：区分修改前事实、候选声明与审查结论", "08 可审计产物", 15)
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
    draw_text(c, 80, 143, "USAGE.md｜面向测试方；AUDIT.md｜面向审计者", size=16, fill=WHITE, font="NotoBold")
    draw_text(c, 80, 116, "未完成运行写入 failure.json，并在两份 Markdown 顶部标记：不得作为最终使用说明。", size=10.5, fill="#C8D4ED")
    badge(c, 744, 118, "INCOMPLETE", fill=CORAL, width=132)
    footer_source(c, "latest 只保存报告、补丁、统计与日志；完整 patched-worktree 不上传；未审查候选不伪装为 PASS")
    c.showPage()


def slide_etcd_setup(c: canvas.Canvas) -> None:
    page_header(c, "etcd/raft 3.6：不预设 API 形状的真实目标", "09 实验设置", 16)
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
    for i, text in enumerate(("无人工 ground truth", "无预设 etcd 专属 API", "无 capability checks", "目标 9118047 / Controller 858eff8")):
        badge(c, 704, 183 - i * 25, text, fill="#203765", text_fill="#D8E4FF", width=194)
    footer_source(c, "命令：consensus-seam patch｜正式实验从 clean Git revision 启动；本轮第二次 Agent 2 修订时中断")
    c.showPage()


def slide_etcd_results(c: canvas.Canvas) -> None:
    page_header(c, "最新 etcd 实验：代码通过测试，工作流仍以 INCOMPLETE 结束", "10 实验时间线", 17)
    rounded_box(c, 42, 106, 408, 350, fill=WHITE)
    draw_text(c, 62, 423, "Agent 1 能力结论", size=17, fill=NAVY, font="NotoBold")
    rows = [
        ("消息捕获", "PATCHABLE", TEAL),
        ("消息注入", "PATCHABLE", TEAL),
        ("时间控制", "SUPPORTED", GREEN),
        ("随机性控制", "PATCHABLE", PURPLE),
        ("生命周期控制", "PATCHABLE｜误判", CORAL),
        ("状态观察", "SUPPORTED", GREEN),
        ("外部输入", "SUPPORTED", GREEN),
    ]
    for i, (capability, status, accent) in enumerate(rows):
        y = 374 - i * 39
        draw_text(c, 66, y + 6, capability, size=10.5, fill=INK, font="NotoBold")
        badge(c, 210, y, status, fill=accent, width=208)

    rounded_box(c, 474, 106, 444, 350, fill=WHITE)
    draw_text(c, 494, 423, "自动闭环实际发生了什么", size=17, fill=NAVY, font="NotoBold")
    timeline = [
        ("A1", "发现 4 项 PATCHABLE", BLUE),
        ("A2-1", "生成消息 / 随机性 / 生命周期；构建通过", TEAL),
        ("A3", "REVISE_AGENT2：深拷贝 + 外部示例 2 个阻塞", PURPLE),
        ("A2-2", "补全 ConfState 深拷贝；go test ./... 通过", AMBER),
        ("中断", "接口报告多报能力 → ValueError → INCOMPLETE", CORAL),
    ]
    for i, (mark, text, accent) in enumerate(timeline):
        y = 367 - i * 58
        set_fill(c, accent)
        c.circle(520, y + 14, 17, fill=1, stroke=0)
        draw_text(c, 520, y + 8, mark, size=8.5, fill=WHITE, font="NotoBold", align="center")
        if i < len(timeline) - 1:
            line(c, 520, y - 4, 520, y - 27, stroke=LINE, width=2)
        draw_text(c, 550, y + 8, text, size=10, fill=INK, font="NotoBold", max_width=330)
    footer_source(c, "实验后框架已修复：Reviewer 只重跑受影响能力；多报字段进入 JSON 重试；生命周期缺少便利包装不再判为缺口")
    c.showPage()


def slide_etcd_code(c: canvas.Canvas) -> None:
    page_header(c, "InteractionEnv 消息控制：内容用于选择，handle 用于调用", "11 生成接口", 18)
    draw_text(c, 48, 430, "已覆盖：公开 rafttest InteractionEnv + 异步存储响应 + 快照缓存", size=15, fill=NAVY, font="NotoBold")
    sources = [
        (48, "ProcessReady", BLUE),
        (48, "Append / Apply 响应", PURPLE),
        (48, "SendSnapshot", AMBER),
    ]
    for i, (x, label, accent) in enumerate(sources):
        y = 354 - i * 54
        rounded_box(c, x, y, 154, 40, fill=WHITE, stroke=accent, radius=10)
        draw_text(c, x + 77, y + 13, label, size=9.2, fill=INK, font="NotoBold", align="center")
        arrow(c, x + 154, y + 20, 244, 327, stroke=accent, width=1.8)

    rounded_box(c, 252, 278, 188, 96, fill="#E3F8F5", stroke=TEAL, radius=14)
    draw_text(c, 346, 340, "权威缓存", size=13, fill=TEAL_DARK, font="NotoBold", align="center")
    draw_text(c, 346, 314, "MessageController 缓存", size=9.5, fill=INK, align="center")
    draw_text(c, 346, 293, "每个实例一个稳定 handle", size=8.5, fill=MUTED, align="center")

    arrow(c, 440, 326, 482, 326, stroke=TEAL, width=2.5)
    rounded_box(c, 490, 278, 190, 96, fill=WHITE, stroke=BLUE, radius=14)
    draw_text(c, 585, 341, "Pending", size=10.5, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 585, 315, "EnvMessage { Handle, Msg }", size=8.7, fill=INK, align="center")
    draw_text(c, 585, 292, "测试按 Msg 内容选择", size=8.5, fill=MUTED, align="center")

    arrow(c, 680, 326, 720, 326, stroke=BLUE, width=2.5)
    rounded_box(c, 728, 278, 184, 96, fill="#EEF6FF", stroke=BLUE, radius=14)
    draw_text(c, 820, 342, "Pending / Drop / Clear", size=10.2, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 820, 316, "InjectMessage(handle)", size=9.4, fill=BLUE_DARK, font="NotoBold", align="center")
    draw_text(c, 820, 292, "env.Nodes[msg.To-1].Step", size=8, fill=MUTED, align="center")

    draw_text(c, 48, 221, "当前边界与待修问题", size=15, fill=NAVY, font="NotoBold")
    findings = [
        (50, "未覆盖", "直接 RawNode / Node 路径", CORAL),
        (270, "统一引用", "不透明稳定 MessageHandle", AMBER),
        (490, "失败语义", "Step 失败前已移除消息", PURPLE),
        (710, "第二轮", "深拷贝修复且全量测试通过", GREEN),
    ]
    for x, title, sub, accent in findings:
        rounded_box(c, x, 110, 202, 72, fill=WHITE, stroke=accent, radius=12)
        draw_text(c, x + 101, 151, title, size=11, fill=accent, font="NotoBold", align="center")
        draw_text(c, x + 101, 126, sub, size=8.3, fill=MUTED, align="center")
    footer_source(c, "核心进展：不再用可变下标或协议消息 ID；测试按内容选择，后续操作使用与缓存实例绑定的 opaque handle")
    c.showPage()


def slide_validation(c: canvas.Canvas) -> None:
    page_header(c, "当前结论：保留正确抽象，修正实现边界，删除误生成部分", "12 结果与启示", 19)
    rounded_box(c, 42, 108, 382, 346, fill=WHITE)
    draw_text(c, 62, 420, "本轮工程事实", size=17, fill=NAVY, font="NotoBold")
    metric_card(c, 62, 330, 154, "+438 / -8", "生产代码行", TEAL)
    metric_card(c, 236, 330, 154, "+473", "新增测试行", BLUE)
    metric_card(c, 62, 240, 154, "22", "生产文件变更", PURPLE)
    metric_card(c, 236, 240, 154, "2", "Reviewer 阻塞项", CORAL)
    rounded_box(c, 62, 142, 328, 70, fill="#FFF8ED", stroke="#F7D7A4", radius=12)
    draw_text(c, 82, 184, "第二轮 go test ./...：全部通过", size=11.5, fill=GREEN_DARK, font="NotoBold")
    draw_text(c, 82, 159, "最终状态：INCOMPLETE，不是 PASS", size=10, fill=CORAL, font="NotoBold")

    rounded_box(c, 448, 108, 470, 346, fill=WHITE)
    draw_text(c, 468, 420, "保留 / 修改 / 删除", size=17, fill=NAVY, font="NotoBold")
    decisions = [
        ("保留", "RandomizedElectionTimeout：默认路径不变，四条路径可用", GREEN),
        ("保留", "MessageController + Pending / Drop / Clear / Inject", TEAL),
        ("修改", "公开 Messages 与私有 ID 的稳定性；同步失败消费语义", AMBER),
        ("继续分析", "RawNode / Node wrapper 可行性，不能直接判 INVASIVE", BLUE),
        ("收紧", "生命周期区分 Pause、Stop、Crash 与 Restart", CORAL),
    ]
    for i, (decision, text, accent) in enumerate(decisions):
        y = 365 - i * 52
        rounded_box(c, 468, y, 430, 44, fill="#F7F9FD", stroke="#E0E7F2", radius=9)
        badge(c, 478, y + 10, decision, fill=accent, width=78)
        draw_text(c, 568, y + 14, text, size=8.8, fill=INK, font="NotoBold", max_width=318)
    rounded_box(c, 468, 118, 430, 42, fill=NAVY_2, stroke=None, radius=10)
    draw_text(c, 683, 133, "当前框架：选择性 Reviewer 修订 + JSON 重试 + 失败报告警告", size=9.5, fill=WHITE, font="NotoBold", align="center")
    footer_source(c, "实验成本：261 次 API｜426 次工具调用｜约 43.6 分钟 Agent 墙钟时间；优化重点是收敛与减少误分类后的无效生成")
    c.showPage()


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("ConsensusSeam：当前架构与 etcd/raft 最新实验")
    c.setAuthor("ConsensusSeam")
    slide_cover(c)
    slide_problem(c)
    for index, detail in enumerate(CAPABILITY_DETAILS, start=1):
        slide_capability_detail(c, detail, index, index + 2)
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
