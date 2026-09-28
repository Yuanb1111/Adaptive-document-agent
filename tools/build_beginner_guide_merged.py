"""Combine the guides into a step-by-step Chinese beginner manual."""
from pathlib import Path
from io import BytesIO
import pymupdf
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, Flowable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/Adaptive_Document_Agent_Beginner_Guide_Public.pdf'
SOURCE = Path(r'C:\Users\yuanb\Desktop\Adaptive_Document_Agent_Beginner_Guide_Latest.pdf')
pdfmetrics.registerFont(TTFont('CN', r'C:\Windows\Fonts\msyh.ttc'))
pdfmetrics.registerFont(TTFont('CNB', r'C:\Windows\Fonts\msyhbd.ttc'))
pdfmetrics.registerFontFamily('CN', normal='CN', bold='CNB', italic='CN', boldItalic='CNB')
NAVY='#173652'; BLUE='#246BFD'; TEAL='#087B69'
styles={
 'title': ParagraphStyle('title',fontName='CNB',fontSize=23,leading=32,textColor=colors.HexColor(NAVY),spaceAfter=12),
 'body': ParagraphStyle('body',fontName='CN',fontSize=11,leading=17,spaceAfter=9,textColor=colors.HexColor('#223548')),
 'h': ParagraphStyle('h',fontName='CNB',fontSize=13,leading=20,spaceBefore=9,spaceAfter=7,textColor=colors.HexColor(NAVY)),
 'small': ParagraphStyle('small',fontName='CN',fontSize=9,leading=13,spaceAfter=8,textColor=colors.HexColor('#607184')),
 'cell': ParagraphStyle('cell',fontName='CN',fontSize=10.5,leading=15,textColor=colors.HexColor('#223548')),
}
for style in styles.values():
 style.wordWrap = 'CJK'
pages=[]; titles=[]; current=[]
def p(t,style='body'): return Paragraph(t,styles[style])
def add(t,style='body'): current.append(p(t,style))
def note(title,text,color='#EAF8F4'):
 t=Table([[p(title,'h')],[p(text)]],colWidths=[496])
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(color)),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,0),7),('BOTTOMPADDING',(0,-1),(-1,-1),9)]))
 current.extend([Spacer(1,6),t,Spacer(1,10)])
def table(rows,widths):
 cells=[[p(str(v),'cell') for v in row] for row in rows]
 t=Table(cells,colWidths=widths,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF1FA')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F6F8FA')]),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#D4DFE8')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
 current.extend([t,Spacer(1,12)])
def link(url,label=None): return f'<link href="{url}" color="{BLUE}">{label or url}</link>'
def page(title,sub):
 global current
 current=[];pages.append(current);titles.append(title.replace('<br/>',' '));add(title,'title');add(sub,'small')
def step(n,title,text): add(f'{n}. {title}','h');add(text)
def pic(src_page,max_h=245):
 asset=ROOT / f'output/pdf/assets/guide_illustration_{src_page}.png'
 if asset.exists():
  loaded=Image(str(asset));w,h=loaded.imageWidth,loaded.imageHeight;scale=min(496/w,max_h/h)
  loaded.drawWidth=w*scale;loaded.drawHeight=h*scale;current.append(loaded)
  current.append(Spacer(1,6));add('操作示意图；具体布局和按钮文字以实际页面为准。','small');return
 source_page=src_page if SOURCE.exists() else {2:5,4:8,5:10}[src_page]
 doc=pymupdf.open(SOURCE if SOURCE.exists() else OUT); info=doc[source_page-1].get_image_info(xrefs=True)[0]; data=doc.extract_image(info['xref'])
 asset.parent.mkdir(parents=True,exist_ok=True)
 pymupdf.Pixmap(doc,info['xref']).save(str(asset))
 w,h=data['width'],data['height']; scale=min(496/w,max_h/h)
 current.append(Image(BytesIO(data['image']),width=w*scale,height=h*scale))
 current.append(Spacer(1,6));add('操作示意图；具体布局和按钮文字以实际页面为准。','small');doc.close()

class PPTButtonGuide(Flowable):
 """Vector illustration, not a screenshot or edited source image."""
 def __init__(self):
  super().__init__()
  self.width=496
  self.height=145
 def draw(self):
  c=self.canv
  c.setFillColor(colors.HexColor('#F5F7FA'));c.roundRect(0,0,496,145,8,fill=1,stroke=0)
  c.setFillColor(colors.HexColor(NAVY));c.setFont('CNB',14);c.drawString(18,116,'PPT 自动准备完成后，点击下载')
  c.setFillColor(colors.HexColor('#EA580C'));c.roundRect(18,56,285,42,6,fill=1,stroke=0)
  c.setFillColor(colors.white);c.setFont('CNB',11);c.drawCentredString(160,72,'Download presentation (.pptx)')
  c.setFillColor(colors.HexColor(NAVY));c.setFont('CN',11);c.drawString(320,72,'下载到电脑')
  c.setFont('CN',10);c.drawString(18,29,'正常流程无需再点击生成；等待文件准备好即可。')

page('Adaptive Document Agent<br/>零基础上手手册','Beginner Guide')
add('从第一次听说 API Key，到自己上传 PDF、生成并检查 PPT。','h')
add('Agent 就是帮助你阅读、分析文件并制作汇报的工具。你不需要写代码，也不需要先判断 PDF 是哪一类文档。')
note('先知道你要做什么','第一次：创建自己的 DeepSeek Key → 填入 Agent → 上传 PDF → 等待自动分析和生成 PPT → 检查并下载。')
add('开始前准备','h')
add('一台能上网的电脑、一份你有权使用的 PDF，以及用于注册 DeepSeek 的个人账户信息。还没有 Key 没关系，本手册从创建开始教。')
note('怎样阅读','第一次使用：从目录里的“账号、钥匙、余额”开始。<br/>已经有 Key：直接跳到“填好模型设置”。<br/>想复制提示词或处理报错：点击第 2 页目录，或打开 PDF 阅读器的书签栏。')
add('打开 Agent：'+link('https://ipo-insight.streamlit.app'))
add('默认上传后自动运行到 PPT 构建与检查，无需手动选择页面。遇到错误或质量检查未通过时，页面会提示处理。','small')

page('目录','点击条目跳转；PDF 书签栏也可以导航。')
toc_items=current

page('01 先认识“账号、钥匙、余额”','读懂这一页，就可以开始操作。')
add('API 可以理解为：让两个软件互相使用服务的连接方式。这里是 Agent 请 DeepSeek 帮忙理解你的文档。')
add('API Key 是一串秘密文字，相当于你交给 Agent 的专用钥匙。DeepSeek 用它识别这次服务由哪个账户使用和付费。')
table([['名称','通俗理解','你用它做什么'],['DeepSeek 账号','你的登录身份','登录 DeepSeek 开放平台'],['API Key（访问密钥）','软件使用服务的钥匙','复制到 Agent 的 API key 输入框'],['API 余额','调用服务的钱包','支付实际使用产生的费用']],[133,151,212])
note('最容易弄混的一点','能在 DeepSeek 聊天网页里聊天，不代表已经创建了 API Key，也不代表 API 账户一定有余额。')
add('什么才是要复制的 Key？','h')
add('创建后平台显示的完整密钥，通常以 <b>sk-</b> 开头。不要把登录密码、短信验证码、模型名或充值订单号填进去。')
note('把它当密码保管','别人拿到 Key，可能会使用你的 API 余额。不要将完整 Key 放进群聊、邮件、操作截图或公开文件。','#FFF6DE')

page('02 打开 DeepSeek 开放平台','这一步在 DeepSeek 网站完成，暂时不用打开 Agent。')
step(1,'在浏览器打开官方入口',link('https://platform.deepseek.com')+'<br/>可以直接点击上面的链接；也可以复制到浏览器最上方的地址栏，按 Enter。')
step(2,'已有账户就登录，没有账户就注册','选择页面提供的登录或注册方式，按提示填写信息并完成验证。密码和验证码只填写在官方页面，具体注册选项以当时页面为准。')
step(3,'找到 API Keys（密钥管理）','登录后，在平台菜单中找 <b>API Keys</b>。也可以打开：<br/>'+link('https://platform.deepseek.com/api_keys'))
note('看到什么算完成？','页面显示 API Keys，或看到 Create new secret key / 创建密钥之类的按钮。接着看下一页。')
add('如果你打开的是聊天窗口','h')
add('请检查地址栏。创建密钥应在 <b>platform.deepseek.com</b> 开放平台进行。聊天窗口不是本步骤要找的页面。')
add('如果打开 API Keys 链接后又要求登录，先完成登录，再重新打开该链接。','small')

page('03 创建一把自己的 API Key','跟着图中红色编号操作；按钮中英文可能略有变化。')
pic(2,265)
step(1,'点击“创建密钥”','找到 <b>Create new secret key / Create new API key</b> 或“创建 API Key”按钮。')
step(2,'给它起一个名字','在 Name（名称）里填写 <b>Adaptive Document Agent</b>。这只是方便自己辨认的备注，不是密码，也不是 Key。')
step(3,'点击 Create（创建）','生成后应出现一串密钥文字。先不要关闭窗口，下一页教你复制和保存。')

page('04 复制并保存 Key','要复制完整密钥，不要只复制开头或列表里的星号。')
step(1,'点击 Copy（复制）','优先使用密钥旁边的 Copy 按钮。如果没有按钮，可选中完整密钥，再用快捷键复制：<br/><b>Windows：Ctrl+C　macOS：Command+C</b>。')
step(2,'保存到自己的安全位置','例如你已经在使用的可信密码管理器。点击保存位置的输入框，用快捷键粘贴：<br/><b>Windows：Ctrl+V　macOS：Command+V</b>。<br/>确认已保存，不要只依赖临时剪贴板。')
step(3,'保存好再关闭创建窗口','完整 Key 可能只显示一次。如果以后只能看到星号或部分字符，就不能用这些内容代替完整 Key。')
table([['你看到的内容','能填到 Agent 吗？'],['刚创建时复制的完整密钥','可以'],['sk-•••••• 或密钥列表中的遮蔽字符','不可以，这不是完整密钥'],['Adaptive Document Agent','不可以，这只是刚填写的备注名'],['DeepSeek 登录密码 / 手机验证码','不可以']],[290,206])
note('忘记保存或怀疑泄露怎么办？','回到 API Keys 页面创建新 Key，并在 Agent 中换成新 Key。旧 Key 不再使用时撤销；如果已经泄露，应立即撤销。其他使用旧 Key 的工具也需更新。','#FFF6DE')

page('05 检查余额：Key 和钱是两回事','创建 Key 后，还要确认 API 账户能支付调用费用。')
step(1,'打开余额页面','在 DeepSeek 平台菜单中找 <b>Balance（余额）</b> 或 <b>Top Up（充值）</b>。名称以实际页面为准。')
step(2,'查看可用余额','有 Key 但余额不足，仍然无法完成分析。看到 <b>402 / Insufficient balance</b>，就是提示 API 余额不足。')
step(3,'如需充值，按页面完成','点击 Top Up / 充值 → 查看可选金额和付款方式 → 选择自己接受的金额 → 核对付款信息后支付。金额和方式以平台实际提供为准。')
step(4,'回到账户确认到账','付款后回到余额页面，确认显示可用余额，再去 Agent 使用。不需要把付款凭证粘贴到 Agent。')
note('一次分析多少钱？','按实际处理和生成的内容量计费，平台称这种计量单位为 token。长文件、复杂分析和重复运行可能增加费用，无法保证每份 PDF 都是固定价格。')
add('第一次可先用一份较短、文字可选中的 PDF 熟悉操作，再在平台的 Usage（用量）或账单页面查看实际消耗。')
add('模型与价格：'+link('https://api-docs.deepseek.com/quick_start/pricing/','DeepSeek 官方价格页（可点击）'),'small')

page('06 回到 Agent，填好模型设置','现在才需要用到刚才保存的 Key。')
add('打开 '+link('https://ipo-insight.streamlit.app')+'，找到左侧 <b>Model Settings（模型设置）</b>。侧栏折叠时先展开它。')
pic(4,233)
table([['界面字段','照着填写'],['Execution Mode（运行方式）','Cloud（云端）'],['Provider（AI 平台）','DeepSeek'],['Model（模型名称）','deepseek-flash'],['Base URL（服务地址）','通常保持空白'],['API key（访问密钥）','粘贴自己的完整 Key']],[230,266])
add('模型名已按 2026-09-23 官方文档核对；以后如提示模型不存在，请看“遇到问题，按提示处理”。','small')

page('07 粘贴 Key，做最后一次检查','这一步填完后，就可以准备上传 PDF。')
step(1,'复制自己保存的完整 Key','从安全保存位置复制。不要复制本手册中的示例，也不要使用别人发来的密钥。')
step(2,'粘贴到 API key 输入框','点击 Agent 左侧的 <b>API key</b> 输入框，然后粘贴：<br/><b>Windows：Ctrl+V　macOS：Command+V</b>。<br/>如果里面已有旧内容，先在该输入框全选（Windows：Ctrl+A；macOS：Command+A），再粘贴新 Key。')
step(3,'检查其他设置','Provider 是 <b>DeepSeek</b>；Model 是 <b>deepseek-flash</b>；Base URL 通常为空。输入完成后点击空白处，让设置生效。')
note('输入框显示圆点，是正常的','圆点用于遮住秘密内容。但显示圆点只说明已输入，不能证明 Key 有效；要等上传后的实际调用成功，才能确认连接可用。')
add('用之前知道这两件事','h')
add('<b>文档内容：</b>Cloud 模式会把分析所需的内容发送给所选模型平台。上传前确认文件可以用于这样的处理。')
add('<b>下次还要不要填：</b>线上版 Key 只用于当前网页会话。重新打开或会话结束后可能需要重新填写，所以要安全保存。')
add('Base URL 通常不用改。如确需手填 DeepSeek 官方服务地址，是 https://api.deepseek.com；不要把登录网址填在这里。','small')

page('08 上传 PDF，默认不用选页','先设置好模型，再上传文件；上传后会自动开始。')
pic(5,253)
step(1,'Analysis Focus（分析重点）可以留空','想指定重点时，复制后面“4 条可以直接复制的提示词”中的一条，粘贴到这里。Prompt 就是给 Agent 的任务说明，不需要另外上传文件。')
step(2,'把可选选页开关保持关闭','<b>Review page scope before analysis (optional)</b> 是“分析前人工检查页码”。保持 <b>OFF</b>；默认流程不用选页、确认范围或再点 Analyse。')
step(3,'在 Upload one PDF 区域上传','点击 <b>Upload / Browse files</b>，在电脑中找到 PDF → 选中文件 → 点击“打开”。也可以将文件拖到上传框。一次上传一份。')
add('完成标志：文件上传后页面开始显示处理状态；若提示缺少 Key 或文件错误，按提示处理。','small')

page('09 上传后等它自动完成','文件越长、表格越复杂或模型响应越慢，等待时间可能越长。')
progress_image=Image(str(ROOT / 'output/pdf/assets/agent_progress_current.png'))
progress_scale=min(496/progress_image.imageWidth,305/progress_image.imageHeight)
progress_image.drawWidth=progress_image.imageWidth*progress_scale
progress_image.drawHeight=progress_image.imageHeight*progress_scale
current.extend([progress_image,Spacer(1,6)])
add('实际运行截图（局部）；页码和批次数量随上传的文件变化。','small')
add('看懂这几行就够了','h')
add('<b>Reading PDF / Understanding document：</b>正在读取和理解文件。<br/><b>Mapping… / selecting relevant sections：</b>Agent 正在自动选择相关章节，你不需要手动选页。')
add('<b>Understood selected pages 81-85 (1/25)：</b>已处理第 81–85 页这一批；本阶段共 25 批，已完成 1 批。这里不是整份任务的完成百分比，也不是让你输入页码。')
add('<b>3 concurrent requests：</b>同时处理 3 个请求，所以完成的页码可能不按顺序出现，这是正常的。')
note('接下来怎么做？','保持页面打开，等待后续分析和 PPT 准备；不要重复上传或刷新。看到 Analysis complete 后，再等 PPTX 下载按钮可用即可下载。明确报错时查看本手册的排错页。')

page('10 PPT 会自动准备：最后这样下载','PPTX 就是可以用 PowerPoint 或 WPS 演示打开的文件。')
download_image=Image(str(ROOT / 'output/pdf/assets/agent_download_current.png'))
download_image.drawHeight=496*download_image.imageHeight/download_image.imageWidth
download_image.drawWidth=496
current.extend([download_image,Spacer(1,8)])
add('实际下载区截图：左侧红色按钮下载 PPT；本例为证据草稿。','small')
step(1,'等待 PPT 按钮可点击，再下载','Agent 会自动准备 PPT。左侧 <b>.pptx</b> 按钮可点击后，即可下载。本例是证据草稿；完整分析版显示 <b>Download presentation (.pptx)</b>。')
note('看到 draft（草稿），先留意','本例是备用的“仅含证据的草稿”，尚不是完整分析汇报。可下载查看；正式使用前需补充分析并核对内容。','#FFF6DE')
step(2,'找到下载的文件','查看浏览器下载列表，或电脑的“下载”文件夹；也可以保存到自己选择的位置。')
step(3,'打开并检查','用 PowerPoint 或 WPS 演示打开，核对标题、年份和关键数字，再编辑成自己的汇报。')
table([['其他格式','什么时候用'],['PDF report','点击 Generate PDF report 按需生成 PDF；这是报告，不是 PPT'],['CSV','用 Excel 查看和核对抽取的数据'],['Markdown','文字版分析，便于继续改写'],['JSON','完整分析数据及来源证据；第一次可以不下载']],[137,359])

page('11 提示词：选一条直接复制','4 个常用示例。Prompt = 任务说明，粘贴到 Analysis Focus 后再上传 PDF。')
add('选中一个框内的整段文字并复制，再点击 Agent 的 Analysis Focus 输入框粘贴。<br/><b>Windows：Ctrl+C / Ctrl+V<br/>macOS：Command+C / Command+V</b><br/>一次选一条，不必把四条全贴进去。不知道选哪条就留空。')
note('A 公司 / 招股书：快速了解公司','请用中文分析这份文件，说明公司的主营业务、收入和利润变化、现金流、增长动力及主要风险，整理成适合向同事汇报的重点。关键数字注明期间、单位和来源页码；缺失信息请明确说明。')
note('B 财务报告：看变化和风险','请用中文比较文件中可用期间的收入、毛利率、净利润、经营现金流和债务情况，解释主要变化与异常，区分文件原有数字和计算结果。结论保留来源页码；没有依据的原因不要猜测。')
note('C 市场报告：看机会与竞争','请用中文总结市场规模、增长趋势、细分市场、主要竞争者及机会和风险。注明数据年份、地区、单位和来源页码，区分历史数据与预测，并说明预测的假设或限制。')
note('D 调查报告：看反馈与差异','请用中文总结调查对象、样本数量、主要发现、不同群体的差异及最值得关注的问题。保留问题口径、比例和来源页码；文件未提供的信息请说明，不要把相关性说成因果关系。')
add('重新运行前先下载已有结果。修改重点后按页面提示重新分析；再次运行可能产生 API 费用。','small')

page('12 遇到问题，按提示处理','先看错误文字，再采取对应动作；不需要懂程序代码。')
table([['屏幕提示 / 现象','你可以怎么做'],['401 / Unauthorized\nKey 认证失败','确认 Provider 是 DeepSeek；重新粘贴完整 Key；若已撤销，换新 Key。'],['402 / Insufficient balance\n余额不足','回 DeepSeek 余额页，按需充值并确认到账，然后按 Agent 页面提示重试。'],['Model not found\n模型不存在','去官方模型页确认当前模型名，修改 Model。不要把模型名填进 Key 输入框。'],['400 / 422\n请求格式或参数问题','先检查设置；仍报错就把遮住 Key 的错误信息交给维护者。不能只凭 400 判断是模型名错误。'],['429 / Rate limit\n请求太频繁','等一会儿再试，避免多窗口同时重复运行。'],['500 / 503\n服务异常或繁忙','稍后再试；持续失败时联系服务方或维护者。'],['抽取的数据很少 / Charts = 0','看 Data Quality。扫描图片可能难以读取；有可复制文字的 PDF 时优先用它。没有图不等于整个分析失败。'],['PPTX 按钮不能点','看 Data Quality 和导出诊断，区分数据问题与文件生成问题；反复点击不能解除检查限制。']],[178,318])
add('求助时说明：文件大约多少页、卡在哪一步、错误原文。不要发送完整 API Key；截图前遮住密钥和文件中的敏感内容。','small')

page('13 第二次使用，只看这一页','已经有安全保存的 Key 时，不需要每次重新创建。')
step(1,'打开 Agent',link('https://ipo-insight.streamlit.app'))
step(2,'核对左侧设置','Cloud → Provider 选 DeepSeek → Model 填 deepseek-flash → Base URL 通常留空。若 API key 为空，粘贴自己的完整 Key。')
step(3,'设置重点并上传','Analysis Focus 可留空；可选 Page Scope 开关保持 OFF；上传一份 PDF。')
step(4,'等待自动处理','自动完成分析、图表和 PPT 构建与检查。无需人工选页。')
step(5,'下载并打开','等待 PPT 自动准备完成。到导出区点击可用的 PPTX 下载按钮，再用 PowerPoint 或 WPS 演示打开文件。')
note('下载前问自己三件事','这是不是我要分析的文件和年份？<br/>关键数字是否核过来源、单位和币种？<br/>数据质量警告是否已经看懂并处理？')
add('第一次推荐完成一个小练习：用一份较短的 PDF 跑通流程，下载 PPT，找一个关键数字回原 PDF 核对，再到 DeepSeek 平台查看这次用量。')

page('常用入口与英文对照','收藏这一页。网址可以直接点击。')
add('Agent：'+link('https://ipo-insight.streamlit.app'))
add('DeepSeek 开放平台：'+link('https://platform.deepseek.com'))
add('创建 / 管理 Key：'+link('https://platform.deepseek.com/api_keys'))
add('模型和价格：'+link('https://api-docs.deepseek.com/quick_start/pricing/','DeepSeek 官方模型与价格'))
add('错误说明：'+link('https://api-docs.deepseek.com/zh-cn/quick_start/error_codes/','DeepSeek 官方错误码说明'))
table([['页面英文','意思'],['Create / Copy / Top Up','创建 / 复制 / 充值'],['Provider / Model / API key','AI 平台 / 模型名称 / 访问密钥'],['Analysis Focus / Upload','分析重点 / 上传'],['Analysis complete / Download','分析完成 / 下载'],['Sources / Data Quality','来源证据 / 数据质量'],['Warning / Critical blocker','需留意的提示 / 严重阻断问题'],['Export diagnostics / Session','导出诊断 / 当前网页会话']],[282,214])
add('关于本手册','h')
add('本手册面向首次接触 API 的用户。界面可能随版本更新，请以实际页面为准。图中公司名、页数、金额和状态均为示例。','small')
add('模型名、地址和错误码参考上述官方资料，于 2026-09-23 核对。登录选项、充值金额及按钮位置可能变化，以官方实际页面为准。','small')

def footer(c,doc):
 c.bookmarkPage(f'page-{doc.page}')
 c.addOutlineEntry(titles[doc.page-1],f'page-{doc.page}',level=0,closed=False)
 c.setStrokeColor(colors.HexColor('#D7E2EB'));c.line(48,44,564,44)
 c.setFont('CN',8);c.setFillColor(colors.HexColor('#6E8091'))
 c.drawString(48,29,'Adaptive Document Agent · 零基础上手手册 · 2026-09-23')
 c.drawRightString(564,29,f'{doc.page} / {len(pages)}')

OUT.parent.mkdir(parents=True,exist_ok=True)
for i,title in enumerate(titles,1):
 if i<=2: continue
 toc_items.append(p(f'<link href="#page-{i}" color="{BLUE}">{title}　······　{i}</link>'))
toc_items.append(Spacer(1,8))
toc_items.append(p('PDF 书签栏：在阅读器中打开“目录 / 书签”侧栏，即可随时跳转。','small'))
story=[]
for i,items in enumerate(pages):
 height=sum(f.wrap(496,10000)[1]+f.getSpaceBefore()+f.getSpaceAfter() for f in items)
 print(f'Page {i+1}: estimated {height:.1f} pt')
 if height>650: raise ValueError(f'Page {i+1} too tall: {height}')
 story.extend(items)
 if i<len(pages)-1: story.append(PageBreak())
doc=SimpleDocTemplate(str(OUT),pagesize=(612,792),leftMargin=58,rightMargin=58,topMargin=50,bottomMargin=64,title='Adaptive Document Agent 零基础上手手册',author='Adaptive Document Agent')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
check=pymupdf.open(OUT)
assert len(check)==len(pages),(len(check),len(pages))
print(OUT)
