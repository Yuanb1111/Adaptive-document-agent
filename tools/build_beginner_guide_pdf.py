"""Build the updated Adaptive Document Agent beginner guide PDF."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "Adaptive_Document_Agent_Beginner_Guide_Final_Updated_2026-09.pdf"

PAGE_W, PAGE_H = letter
MARGIN_X = 48
CONTENT_W = PAGE_W - 2 * MARGIN_X

NAVY = colors.HexColor("#173652")
BLUE = colors.HexColor("#246BFD")
TEAL = colors.HexColor("#0E8A74")
RED = colors.HexColor("#EA4335")
ORANGE = colors.HexColor("#E28A18")
INK = colors.HexColor("#142536")
MUTED = colors.HexColor("#5E6D7B")
LINE = colors.HexColor("#D9E2EA")
PALE_BLUE = colors.HexColor("#EDF4FF")
PALE_TEAL = colors.HexColor("#EAF8F4")
PALE_YELLOW = colors.HexColor("#FFF6D8")
PALE_RED = colors.HexColor("#FDEBEC")
PALE_GRAY = colors.HexColor("#F4F7F9")


def register_fonts() -> None:
    regular = Path(r"C:\Windows\Fonts\msyh.ttc")
    bold = Path(r"C:\Windows\Fonts\msyhbd.ttc")
    pdfmetrics.registerFont(TTFont("CN", str(regular)))
    pdfmetrics.registerFont(TTFont("CN-Bold", str(bold)))


register_fonts()


BODY = ParagraphStyle(
    "Body", fontName="CN", fontSize=9.2, leading=14, textColor=INK, spaceAfter=5
)
BODY_SMALL = ParagraphStyle(
    "BodySmall", fontName="CN", fontSize=7.8, leading=11.5, textColor=INK
)
NOTE = ParagraphStyle(
    "Note", fontName="CN", fontSize=8.3, leading=12.5, textColor=INK
)
H2 = ParagraphStyle(
    "H2", fontName="CN-Bold", fontSize=12.5, leading=17, textColor=NAVY
)
WHITE_SMALL = ParagraphStyle(
    "WhiteSmall", fontName="CN", fontSize=8, leading=11, textColor=colors.white
)
CENTER_SMALL = ParagraphStyle(
    "CenterSmall", fontName="CN", fontSize=8, leading=11, alignment=TA_CENTER, textColor=INK
)


def para(c: canvas.Canvas, text: str, x: float, y_top: float, width: float, style=BODY) -> float:
    p = Paragraph(text, style)
    _, h = p.wrap(width, PAGE_H)
    p.drawOn(c, x, y_top - h)
    return y_top - h


def page_header(c: canvas.Canvas, section: str, page_num: int, title: str, subtitle: str | None = None) -> float:
    c.setFillColor(BLUE)
    c.setFont("CN-Bold", 7.5)
    c.drawString(MARGIN_X, PAGE_H - 37, section.upper())
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 20)
    c.drawString(MARGIN_X, PAGE_H - 68, title)
    y = PAGE_H - 84
    if subtitle:
        c.setFillColor(MUTED)
        c.setFont("CN", 8.5)
        c.drawString(MARGIN_X, y, subtitle)
        y -= 12
    c.setStrokeColor(LINE)
    c.setLineWidth(0.7)
    c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
    footer(c, page_num)
    return y - 18


def footer(c: canvas.Canvas, page_num: int) -> None:
    c.setFillColor(colors.HexColor("#8392A1"))
    c.setFont("CN", 6.5)
    c.drawCentredString(PAGE_W / 2, 22, f"Adaptive Document Agent · 新手操作指南（2026-09 更新）  |  {page_num}")


def box(c: canvas.Canvas, x: float, y_top: float, w: float, h: float, fill, stroke=LINE, radius: float = 4) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y_top - h, w, h, radius, fill=1, stroke=1)


def callout(c: canvas.Canvas, y_top: float, title: str, text: str, kind: str = "blue", height: float = 62) -> float:
    palette = {
        "blue": (PALE_BLUE, BLUE),
        "teal": (PALE_TEAL, TEAL),
        "yellow": (PALE_YELLOW, ORANGE),
        "red": (PALE_RED, RED),
        "gray": (PALE_GRAY, MUTED),
    }
    fill, accent = palette[kind]
    box(c, MARGIN_X, y_top, CONTENT_W, height, fill, fill)
    c.setFillColor(accent)
    c.rect(MARGIN_X, y_top - height, 4, height, fill=1, stroke=0)
    c.setFillColor(accent)
    c.setFont("CN-Bold", 9)
    c.drawString(MARGIN_X + 13, y_top - 18, title)
    para(c, text, MARGIN_X + 13, y_top - 27, CONTENT_W - 26, NOTE)
    return y_top - height - 12


def number_badge(c: canvas.Canvas, x: float, y: float, n: int, color=RED) -> None:
    c.setFillColor(color)
    c.circle(x, y, 9, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("CN-Bold", 7.5)
    c.drawCentredString(x, y - 2.6, str(n))


def bullet_list(c: canvas.Canvas, items: list[str], x: float, y_top: float, width: float, font_size: float = 8.7) -> float:
    style = ParagraphStyle("Bullets", parent=BODY, fontSize=font_size, leading=13, leftIndent=13, firstLineIndent=-10)
    y = y_top
    for item in items:
        y = para(c, f"<font color='#246BFD'>●</font> {item}", x, y, width, style) - 3
    return y


def draw_table(c: canvas.Canvas, data: list[list[object]], x: float, y_top: float, widths: list[float], row_heights=None, font_size=7.8) -> float:
    formatted = []
    for r, row in enumerate(data):
        style = ParagraphStyle(
            f"T{r}",
            fontName="CN-Bold" if r == 0 else "CN",
            fontSize=font_size,
            leading=font_size + 3.2,
            textColor=colors.white if r == 0 else INK,
            alignment=TA_LEFT,
        )
        formatted.append([Paragraph(str(cell), style) for cell in row])
    t = Table(formatted, colWidths=widths, rowHeights=row_heights, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    _, h = t.wrap(CONTENT_W, PAGE_H)
    t.drawOn(c, x, y_top - h)
    return y_top - h


def mock_sidebar(c: canvas.Canvas, x: float, y_top: float, w: float = 310, h: float = 270) -> None:
    box(c, x, y_top, w, h, colors.white, LINE, 5)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(x + 16, y_top - 24, "Model Settings")
    labels = [
        ("Execution Mode", "Cloud"),
        ("Provider", "DeepSeek"),
        ("Model", "deepseek-flash"),
        ("Base URL (optional)", ""),
        ("API key", "••••••••••••••••"),
    ]
    y = y_top - 46
    for idx, (label, value) in enumerate(labels, 1):
        c.setFillColor(MUTED)
        c.setFont("CN", 6.8)
        c.drawString(x + 16, y, label)
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#B8C5D1"))
        c.roundRect(x + 16, y - 31, w - 32, 25, 3, fill=1, stroke=1)
        c.setFillColor(INK if value else colors.HexColor("#A0ABB5"))
        c.setFont("CN", 7.4)
        c.drawString(x + 24, y - 22, value or "留空")
        number_badge(c, x + w + 15, y - 18, idx, RED)
        y -= 43
    c.setFillColor(PALE_BLUE)
    c.roundRect(x + 16, y_top - h + 14, w - 32, 25, 3, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.setFont("CN", 6.8)
    c.drawString(x + 24, y_top - h + 23, "Cloud model · 文档相关内容会发送到配置的模型平台")


def mock_upload(c: canvas.Canvas, x: float, y_top: float, w: float = 480, h: float = 210) -> None:
    box(c, x, y_top, w, h, colors.white, LINE, 5)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 13)
    c.drawString(x + 18, y_top - 28, "Adaptive Document Intelligence Agent")
    c.setFillColor(MUTED)
    c.setFont("CN", 7.2)
    c.drawString(x + 18, y_top - 44, "上传 PDF 后，Agent 会理解文档、发现数据、验证结果并生成汇报。")
    c.setFillColor(PALE_GRAY)
    c.roundRect(x + 18, y_top - 91, w - 36, 34, 3, fill=1, stroke=0)
    c.setFillColor(MUTED)
    c.setFont("CN", 7)
    c.drawString(x + 29, y_top - 78, "Analysis focus (optional) · 可留空")
    c.setFillColor(PALE_TEAL)
    c.roundRect(x + 18, y_top - 127, w - 36, 25, 3, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont("CN", 7.2)
    c.drawString(x + 29, y_top - 118, "Review page scope before analysis (optional)   OFF")
    c.setStrokeColor(colors.HexColor("#AFC0CD"))
    c.setDash(4, 3)
    c.roundRect(x + 18, y_top - 190, w - 36, 50, 5, fill=0, stroke=1)
    c.setDash()
    c.setFillColor(BLUE)
    c.setFont("CN-Bold", 9)
    c.drawCentredString(x + w / 2, y_top - 164, "Upload one PDF")
    c.setFillColor(MUTED)
    c.setFont("CN", 6.8)
    c.drawCentredString(x + w / 2, y_top - 179, "上传后自动开始，无需选择文档类型或页码")


def flow(c: canvas.Canvas, y: float, labels: list[str]) -> None:
    n = len(labels)
    gap = 12
    w = (CONTENT_W - gap * (n - 1)) / n
    for i, label in enumerate(labels):
        x = MARGIN_X + i * (w + gap)
        box(c, x, y, w, 56, PALE_BLUE if i < n - 1 else PALE_TEAL, BLUE if i < n - 1 else TEAL, 5)
        c.setFillColor(BLUE if i < n - 1 else TEAL)
        c.setFont("CN-Bold", 8.5)
        c.drawCentredString(x + w / 2, y - 21, f"{i + 1:02d}")
        para(c, label, x + 5, y - 29, w - 10, CENTER_SMALL)
        if i < n - 1:
            c.setFillColor(BLUE)
            c.setFont("CN-Bold", 13)
            c.drawCentredString(x + w + gap / 2, y - 31, "→")


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=letter)
    c.setTitle("Adaptive Document Agent 新手操作指南（2026-09 更新）")
    c.setAuthor("Adaptive Document Agent")

    # 1 — Cover
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 226, PAGE_W, 226, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#78A9FF"))
    c.setFont("CN-Bold", 8)
    c.drawString(MARGIN_X, PAGE_H - 58, "BEGINNER GUIDE · UPDATED 2026-09")
    c.setFillColor(colors.white)
    c.setFont("CN-Bold", 24)
    c.drawString(MARGIN_X, PAGE_H - 104, "Adaptive Document Agent")
    c.setFont("CN-Bold", 21)
    c.drawString(MARGIN_X, PAGE_H - 139, "新手操作指南")
    c.setFont("CN", 9.5)
    c.drawString(MARGIN_X, PAGE_H - 168, "上传一个 PDF，Agent 自动分析并生成 PPT。")
    c.setFillColor(PALE_TEAL)
    c.roundRect(MARGIN_X, PAGE_H - 313, CONTENT_W, 61, 5, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont("CN-Bold", 11)
    c.drawString(MARGIN_X + 16, PAGE_H - 277, "这版最重要的变化")
    c.setFillColor(INK)
    c.setFont("CN", 9)
    c.drawString(MARGIN_X + 16, PAGE_H - 298, "不再要求选择页码、确认 scope 或手动点击 Analyse。上传后默认自动运行到 PPT。")
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, PAGE_H - 356, "开始前只准备 3 样东西")
    flow(c, PAGE_H - 379, ["一份 PDF", "一个 AI API Key", "可选：一句分析重点"])
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, PAGE_H - 474, "最新默认流程")
    flow(c, PAGE_H - 498, ["设置模型", "上传 PDF", "自动分析", "生成并下载 PPT"])
    callout(c, PAGE_H - 590, "在线地址", "<link href='https://ipo-insight.streamlit.app' color='#246BFD'>https://ipo-insight.streamlit.app</link><br/>API Key、公司名称和示例数值请使用你自己的真实信息。", "blue", 62)
    footer(c, 1)
    c.showPage()

    # 2 — Quick start
    y = page_header(c, "QUICK START", 2, "1. 第一次使用：只做这 4 步", "默认自动模式不需要选择文档类型或页码。")
    data = [
        ["步骤", "你要做什么", "完成标志"],
        ["1", "左侧选择 Cloud / DeepSeek，填写模型和 API Key", "模型设置完整"],
        ["2", "Analysis focus 可留空；上传 1 份 PDF", "页面开始显示 pipeline 进度"],
        ["3", "等待自动读取、抽取、分析、校验、制图和生成 PPT", "不要反复上传或刷新页面"],
        ["4", "结果出现后先看 Data Quality，再下载 PPTX", "得到可编辑的汇报文件"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [46, 285, 185], font_size=8) - 20
    y = callout(c, y, "旧版手册里哪些步骤已经取消？", "默认流程不再要求 <b>Review analysis scope → 检查页码 → Confirm → Analyse selected pages</b>。当前页面仍保留一个可选审阅开关，但普通用户保持关闭即可。", "teal", 72)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, y - 8, "上传后 Agent 会自动完成什么？")
    y -= 28
    y = bullet_list(c, [
        "识别文档内容与主要章节，不要求你预先选择文档类型。",
        "抽取文本、表格、指标、期间、单位和来源页码。",
        "决定哪些分析真正有价值，并用确定性计算执行数学运算。",
        "检查冲突、低置信度与数据质量问题。",
        "生成分析、图表、证据页，并尝试自动生成 PowerPoint。",
    ], MARGIN_X, y, CONTENT_W)
    y = callout(c, y - 8, "运行期间", "大 PDF 和复杂表格会花更久。看到进度在变化就继续等待；不要连续点击、刷新或重复上传。", "yellow", 55)
    c.showPage()

    # 3 — Model settings
    y = page_header(c, "MODEL SETTINGS", 3, "2. 先设置模型", "以下以 DeepSeek 云端 API 为例。")
    mock_sidebar(c, MARGIN_X, y - 2, 330, 292)
    x2 = MARGIN_X + 360
    labels = [
        ("1", "Execution Mode", "选 Cloud。"),
        ("2", "Provider", "选 DeepSeek。"),
        ("3", "Model", "填写官方当前可用模型名。"),
        ("4", "Base URL", "通常留空；平台明确要求时再填。"),
        ("5", "API Key", "粘贴完整 Key，不要带空格。"),
    ]
    yy = y - 11
    for num, title, desc in labels:
        number_badge(c, x2 + 9, yy - 7, int(num))
        c.setFillColor(NAVY)
        c.setFont("CN-Bold", 8.5)
        c.drawString(x2 + 25, yy - 3, title)
        yy = para(c, desc, x2 + 25, yy - 10, PAGE_W - MARGIN_X - x2 - 25, BODY_SMALL) - 13
    y2 = y - 322
    y2 = callout(c, y2, "API Key 是什么？", "它是 Agent 调用模型 API 的通行证。普通聊天产品的会员或订阅，<b>不等于</b>自动拥有 API 额度。DeepSeek 网页聊天账号与 DeepSeek API 的余额/计费也要分别查看。", "blue", 74)
    y2 = callout(c, y2, "隐私提醒", "Cloud 模式会把与分析相关的文档内容发送给你配置的模型平台。API Key 仅用于当前会话，不要截图、转发或写入公开文档。", "red", 67)
    c.showPage()

    # 4 — DeepSeek account
    y = page_header(c, "DEEPSEEK API KEY", 4, "3. 创建 DeepSeek API Key（第 1/2）", "先注册/登录开发者平台，再进入 API Keys 页面。")
    steps = [
        ("1", "打开 DeepSeek 开放平台", "浏览器访问 <link href='https://platform.deepseek.com' color='#246BFD'>platform.deepseek.com</link>。不要在非官方镜像站创建 Key。"),
        ("2", "注册或登录", "按页面提示使用支持的方式完成登录；如平台要求邮箱/手机验证，请按页面完成。"),
        ("3", "进入 API Keys", "登录后打开左侧 <b>API Keys</b>，或直接访问 <link href='https://platform.deepseek.com/api_keys' color='#246BFD'>platform.deepseek.com/api_keys</link>。"),
        ("4", "确认 API 余额", "在平台的余额/充值或用量页面查看可用余额。API 调用按 token 计费；余额不足会导致请求失败。"),
    ]
    for n, title, text in steps:
        box(c, MARGIN_X, y, CONTENT_W, 83, colors.white, LINE, 5)
        number_badge(c, MARGIN_X + 24, y - 27, int(n), BLUE)
        c.setFillColor(NAVY)
        c.setFont("CN-Bold", 10.5)
        c.drawString(MARGIN_X + 48, y - 23, title)
        para(c, text, MARGIN_X + 48, y - 33, CONTENT_W - 65, BODY_SMALL)
        y -= 96
    y = callout(c, y, "容易混淆", "DeepSeek 聊天网页能正常对话，不代表 API 一定有可用余额。Agent 使用的是开发者 API Key 和 API 账户余额。", "yellow", 60)
    y = callout(c, y, "官方参考", "创建 Key：<link href='https://platform.deepseek.com/api_keys' color='#246BFD'>DeepSeek Platform / API Keys</link>　API 文档：<link href='https://api-docs.deepseek.com' color='#246BFD'>api-docs.deepseek.com</link>", "gray", 55)
    c.showPage()

    # 5 — Create key
    y = page_header(c, "DEEPSEEK API KEY", 5, "4. 创建 DeepSeek API Key（第 2/2）", "创建后立刻复制，并把它当密码保管。")
    data = [
        ["步骤", "页面操作", "你应该看到什么"],
        ["1", "点击 Create new API key / 创建 API Key", "弹出创建窗口"],
        ["2", "输入容易识别的名称，例如 adaptive-document-agent", "名称只用于你自己区分用途"],
        ["3", "点击 Create / 创建", "页面显示新 Key"],
        ["4", "立即点击 Copy / 复制", "Key 通常以 sk- 开头"],
        ["5", "安全保存后关闭窗口", "之后可在 Agent 中粘贴使用"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [45, 260, 211], font_size=7.8) - 18
    y = callout(c, y, "非常重要：完整 Key 往往只显示一次", "如果忘记保存，通常不能再次查看原文。请删除旧 Key 并新建一个，不要猜测、不要截图发群。", "red", 68)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, y - 5, "安全保存建议")
    y -= 24
    y = bullet_list(c, [
        "优先放进可信密码管理器；不要写进 Word、PPT、聊天记录或公开代码仓库。",
        "不要把 Key 发给同事共用；不同用途分别创建，便于撤销和排查。",
        "怀疑泄露时，立刻到 API Keys 页面删除/撤销，再创建新 Key。",
        "Agent 输入框会遮蔽 Key；使用结束后关闭会话，下次需要重新输入。",
    ], MARGIN_X, y, CONTENT_W)
    y = callout(c, y - 3, "计费提醒", "费用会从充值余额或赠送余额中扣除。模型名和价格会更新，请以 DeepSeek 官方 <link href='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/' color='#246BFD'>模型与价格页</link> 为准。", "yellow", 62)
    c.showPage()

    # 6 — Configure DeepSeek
    y = page_header(c, "DEEPSEEK SETUP", 6, "5. 把 DeepSeek Key 填进 Agent", "截至 2026-09-23 的官方配置示例。")
    data = [
        ["字段", "推荐填写", "说明"],
        ["Execution Mode", "Cloud", "使用云端模型 API"],
        ["Provider", "DeepSeek", "必须与 Key 的来源一致"],
        ["Model", "deepseek-flash", "当前官方快速模型名；以后可能变化"],
        ["Base URL", "留空", "Agent 已识别 Provider 时通常不需要手填"],
        ["API Key", "粘贴 sk-…", "复制完整，不要包含前后空格"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [95, 145, 276], font_size=7.8) - 18
    y = callout(c, y, "为什么模型名仍要看官方？", "模型会升级或退役。当前官方文档建议使用 <b>deepseek-flash</b>；若 Agent 显示 Model not found，请回到 DeepSeek 官方模型与价格页复制最新模型名。", "blue", 70)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, y - 6, "10 秒自检")
    y -= 28
    y = bullet_list(c, [
        "Provider = DeepSeek。",
        "API Key 来自 DeepSeek Platform，不是别的平台。",
        "Model 在当前 DeepSeek API 文档中可用。",
        "Key 已完整粘贴，没有引号和多余空格。",
        "账户有可用余额；如果刚充值，稍等后再试。",
    ], MARGIN_X, y, CONTENT_W)
    y = callout(c, y - 2, "官方 API 参数", "OpenAI 兼容 Base URL 为 <b>https://api.deepseek.com</b>。本 Agent 的 DeepSeek Provider 通常会自动处理；只有自定义兼容端点才需要手填。", "gray", 60)
    c.showPage()

    # 7 — Upload
    y = page_header(c, "UPLOAD", 7, "6. 写 Analysis Focus，然后上传 PDF", "Analysis Focus 可留空；上传后默认自动运行。")
    mock_upload(c, MARGIN_X, y - 2, CONTENT_W, 210)
    y -= 235
    y = callout(c, y, "最省事的做法", "Analysis Focus 完全留空。Agent 会自己判断文档类型、重要章节、指标和可做的分析。", "teal", 60)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, y - 3, "有明确目标时，只写一句")
    y -= 25
    examples = [
        ["场景", "可直接参考"],
        ["招股书/年报", "重点分析业务、收入利润现金流、业务分部、主要风险，并保留来源页码。"],
        ["市场报告", "总结市场规模、增长、细分、竞争格局和关键假设，重要数字标明页码。"],
        ["调查报告", "分析主要主题、群体差异、最高最低项和数据质量限制。"],
    ]
    y = draw_table(c, examples, MARGIN_X, y, [90, 426], font_size=7.8) - 14
    y = callout(c, y, "不要做的事", "不要把 Focus 写成几十个问题，也不要手动列出所有页码。目标越清楚越好，不是越长越好。", "yellow", 55)
    c.showPage()

    # 8 — Auto pipeline
    y = page_header(c, "AUTOMATIC PIPELINE", 8, "7. 上传后：让 Agent 自动跑完", "新版默认从上传一直运行到生成 PPT。")
    stages = [
        ("读取", "验证 PDF、读取页面、抽取文本与表格"),
        ("理解", "识别文档内容、指标、期间、单位与证据"),
        ("分析", "选择高价值分析，用 Python 做计算"),
        ("校验", "检查冲突、来源、单位与低置信度"),
        ("输出", "生成报告、图表与 PowerPoint"),
    ]
    for i, (name, desc) in enumerate(stages, 1):
        box(c, MARGIN_X, y, CONTENT_W, 64, PALE_BLUE if i < 5 else PALE_TEAL, LINE, 5)
        number_badge(c, MARGIN_X + 25, y - 32, i, BLUE if i < 5 else TEAL)
        c.setFillColor(NAVY)
        c.setFont("CN-Bold", 10)
        c.drawString(MARGIN_X + 50, y - 27, name)
        c.setFillColor(MUTED)
        c.setFont("CN", 8)
        c.drawString(MARGIN_X + 115, y - 27, desc)
        if i < 5:
            c.setFillColor(BLUE)
            c.setFont("CN-Bold", 12)
            c.drawCentredString(PAGE_W / 2, y - 78, "↓")
        y -= 82
    y = callout(c, y, "可选：人工审阅页码", "当前界面仍有 <b>Review page scope before analysis (optional)</b> 开关。只有你确实想先检查范围时才打开；默认保持关闭，普通流程无需选页。", "gray", 70)
    y = callout(c, y, "如果页面很久没变化", "先继续等待；超大 PDF、扫描件或复杂表格耗时更长。只有明确报错后，再按本指南的排查页处理。", "yellow", 58)
    c.showPage()

    # 9 — Results tabs
    y = page_header(c, "RESULTS", 9, "8. 分析完成后：先认这 7 个 Tabs", "推荐阅读顺序：Overview → Analysis → Charts → Sources → Data Quality。")
    data = [
        ["Tab", "主要看什么"],
        ["Overview", "文档类型、页数、重要发现、分析数量和警告"],
        ["Analysis", "完整分析正文；区分事实、计算结果与解释"],
        ["Charts", "趋势、比较和构成；可查看图表使用的 exact data"],
        ["Extracted Data", "指标、原始值、期间、单位、币种、置信度与页码"],
        ["Sources", "关键结论对应的原文/表格证据和来源页码"],
        ["Data Quality", "冲突、低置信度、OCR、验证警告与 Critical QA"],
        ["Technical Details", "模型、分析计划、工具、用量和运行时间等开发者信息"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [120, 396], font_size=7.8) - 20
    y = callout(c, y, "先看结果，还是先下载 PPT？", "建议先快速扫一遍 Overview 和 Data Quality。重要汇报尤其要检查 Sources；这样能避免把明显冲突或低置信度内容直接带进正式演示。", "blue", 72)
    y = callout(c, y, "记住", "Agent 会保留页码证据，但自动分析仍需要人做最终判断。数字越重要，越应该回到 Sources 和原 PDF 复核。", "teal", 62)
    c.showPage()

    # 10 — Evidence and charts
    y = page_header(c, "VERIFY", 10, "9. 图表、来源和数据质量怎么核", "不要只看结论好不好看；要确认它能回到原始证据。")
    cols = [
        ("Charts", "看标题、指标、期间和单位；展开 exact data；记住 Source pages。", PALE_BLUE, BLUE),
        ("Sources", "核 page + source text；必要时回原 PDF 对照表格行列和上下文。", PALE_TEAL, TEAL),
        ("Data Quality", "黄色 Warning 需要留意；红色 Critical blocker 应先处理再汇报。", PALE_YELLOW, ORANGE),
    ]
    w = (CONTENT_W - 24) / 3
    for i, (title, text, fill, accent) in enumerate(cols):
        x = MARGIN_X + i * (w + 12)
        box(c, x, y, w, 166, fill, fill, 5)
        c.setFillColor(accent)
        c.setFont("CN-Bold", 12)
        c.drawString(x + 12, y - 24, title)
        para(c, text, x + 12, y - 39, w - 24, NOTE)
    y -= 190
    data = [
        ["你看到的情况", "怎么判断"],
        ["Charts = 0", "不一定是故障；可能没有足够且通过验证的可视化数据"],
        ["Warning", "提示数据或解释存在限制；不一定代表结果错误"],
        ["Critical blocker", "严重事实/财务矛盾或验证失败；先核对应来源"],
        ["数字和原文不一致", "保留两者，检查期间、单位、币种、口径与四舍五入"],
        ["来源页码合理但结论奇怪", "回原 PDF 看完整上下文，必要时调整 Focus 后重跑"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [150, 366], font_size=7.8) - 18
    y = callout(c, y, "最稳的核查顺序", "Exact data → Source pages → 原 PDF → Data Quality。", "blue", 52)
    c.showPage()

    # 11 — PPT
    y = page_header(c, "POWERPOINT", 11, "10. PPT 会自动生成：最后这样下载", "结果完成后，在导出区选择所需文件。")
    data = [
        ["文件", "适合场景", "一句话理解"],
        ["PPTX", "汇报 / Presentation", "可编辑；最适合继续调整成正式汇报"],
        ["PDF", "阅读 / 分享", "排版好的分析报告，打开即可阅读"],
        ["Markdown", "二次编辑 / 继续交给 AI", "结构清楚，适合文本加工"],
        ["CSV", "核数据 / Excel", "结构化 observations，方便复核分析"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [85, 175, 256], font_size=7.8) - 20
    y = callout(c, y, "推荐下载顺序", "先下载 PPTX，再根据需要下载 PDF/CSV 留档。PPTX 可继续改标题、删页、调整品牌色或加入你自己的判断。", "teal", 65)
    y = callout(c, y, "PPTX 没生成或按钮不可用？", "先看 Data Quality 和页面报错。Critical QA 可能主动阻止可疑内容进入正式演示；这是一种保护机制。", "red", 66)
    c.setFillColor(NAVY)
    c.setFont("CN-Bold", 12)
    c.drawString(MARGIN_X, y - 3, "交付前最后 3 个检查")
    y -= 25
    y = bullet_list(c, [
        "PPT 标题、公司名、期间和币种是否正确。",
        "关键数字是否能在 Sources 找到页码证据。",
        "Warning / Critical blocker 是否已理解并妥善处理。",
    ], MARGIN_X, y, CONTENT_W)
    c.showPage()

    # 12 — Troubleshooting
    y = page_header(c, "TROUBLESHOOTING", 12, "11. 出问题了？按屏幕现象排查", "先看现象，不需要先理解技术原因。")
    data = [
        ["你看到的情况", "最可能原因", "怎么办"],
        ["401 / Unauthorized", "Key 无效、复制不完整或平台不匹配", "重新复制；确认 Provider = DeepSeek"],
        ["Model not found", "模型名已变更或账户无权限", "去 DeepSeek 官方模型页复制当前名称"],
        ["Rate limit / quota", "余额、限额或并发限制", "检查余额；稍后重试；必要时换可用模型"],
        ["上传后很慢", "PDF 大、表格复杂或模型响应慢", "继续等待，不要重复上传或刷新"],
        ["Extracted Data 很少", "扫描件、图片表格或版式复杂", "先看 Data Quality；换可复制文字的 PDF"],
        ["Charts = 0", "没有足够可验证的可视化数据", "看 Extracted Data / Data Quality"],
        ["PPTX 未生成", "Critical QA、渲染失败或分析未完成", "看 Data Quality 和页面错误；核对应来源"],
        ["结论感觉不对", "口径、期间、单位或解释需复查", "去 Sources 对照原 PDF；调整 Focus 重跑"],
    ]
    y = draw_table(c, data, MARGIN_X, y, [123, 180, 213], font_size=6.9) - 18
    y = callout(c, y, "万能排查顺序", "Provider / Model / Key → 余额 → 上传进度 → Extracted Data → Sources → Data Quality → PPT 导出。", "blue", 60)
    y = callout(c, y, "Key 疑似泄露", "立即去 DeepSeek API Keys 页面撤销旧 Key，并创建新 Key。不要继续使用已泄露的密钥。", "red", 58)
    c.showPage()

    # 13 — Cheat sheet
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 122, PAGE_W, 122, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#78A9FF"))
    c.setFont("CN-Bold", 7.5)
    c.drawString(MARGIN_X, PAGE_H - 47, "ONE-PAGE CHEAT SHEET")
    c.setFillColor(colors.white)
    c.setFont("CN-Bold", 22)
    c.drawString(MARGIN_X, PAGE_H - 83, "一分钟速查")
    c.setFont("CN", 8.5)
    c.drawString(MARGIN_X, PAGE_H - 102, "以后忘了怎么用，只看这一页。")
    y = PAGE_H - 148
    blocks = [
        ("① 创建 DeepSeek Key", ["登录 platform.deepseek.com", "进入 API Keys → Create new API key", "立即复制，以 sk- 开头；安全保存", "确认 API 账户有可用余额"]),
        ("② 左侧模型设置", ["Execution Mode → Cloud", "Provider → DeepSeek", "Model → deepseek-flash（以官方最新文档为准）", "Base URL → 通常留空", "API Key → 粘贴完整 Key"]),
        ("③ 上传并等待", ["Analysis Focus → 可空", "Review page scope → 默认关闭", "Upload one PDF → 上传", "上传后自动分析、校验、制图并生成 PPT"]),
        ("④ 结果与下载", ["先看 Overview + Data Quality", "重要数字去 Sources 核页码", "下载 PPTX；按需下载 PDF / Markdown / CSV"]),
    ]
    for title, items in blocks:
        c.setFillColor(NAVY)
        c.setFont("CN-Bold", 11)
        c.drawString(MARGIN_X, y, title)
        y -= 15
        y = bullet_list(c, items, MARGIN_X + 8, y, CONTENT_W - 8, 8.1) - 7
    y = callout(c, y, "最后记住一句", "设置好模型和 Key，上传 PDF 后就让 Agent 自动跑完；正式汇报前，再用 Sources 和 Data Quality 核一次。", "yellow", 63)
    para(c, "打开在线 Agent：<link href='https://ipo-insight.streamlit.app' color='#246BFD'>ipo-insight.streamlit.app</link>", MARGIN_X, 63, CONTENT_W, ParagraphStyle("Link", parent=BODY, alignment=TA_CENTER, fontName="CN-Bold"))
    footer(c, 13)
    c.showPage()

    c.save()
    print(OUTPUT)


if __name__ == "__main__":
    build()
