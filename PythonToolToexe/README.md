# 多能工具箱（开机启动管理 + Markdown 转文档 + 默认应用清理 + 目录数据同步）

> 版本：**v2.3.0** ｜ 程序名：**ToolBox** ｜ UI：**Python 自带 tkinter**（无第三方 GUI 依赖）

一个 Windows 桌面工具，集成四个功能（ttk.Notebook 多页签）：

1. **开机启动项管理**：把任意 `.exe` / `.bat` / `.cmd` 程序添加为开机自启，并随时查看 / 删除已添加的启动项（页签内左侧导航切换 设置/取消/历史）。
2. **Markdown 转文档**：把 Markdown 内容导出为 `.doc` / `.docx` / `.pdf` / `.xlsx` 四种文档格式。
3. **默认应用清理**：读取系统中各文件扩展名 / URL 协议的默认打开程序信息，一键识别 WPS 篡改并批量还原，支持手动设置默认软件。
4. **目录数据同步器**：局域网两台电脑经 TCP 配对后，把源目录（含子目录、隐藏文件）递归增量同步到目标目录；配对信息自动保存，下次直接选用。

所有注册表写操作都在 `HKEY_CURRENT_USER`（当前用户）下完成，**不需要管理员权限、不会弹 UAC**。界面用 Python 自带 tkinter 构建，无兼容性问题，打包体积小。

---

## ✨ 功能特性

### 开机启动项管理
- 🖱️ **纯图形界面**：选目录 → 扫描 → 添加，全程鼠标操作。
- 🔍 **递归扫描**：后台线程遍历所有子文件夹，扫描期间显示进度条。
- 🔓 **免管理员权限**：仅写入 `HKCU` 注册表。
- 🏷️ **别名支持**：可给启动项起好记的名字，记录保存在 `aliases.json`。
- ✅ **二次确认**：添加 / 删除前弹出确认对话框。
- 📋 **表格管理**：`Treeview` 列出启动项，多选删除；删除历史可追溯、可清空。
- 🧭 **左侧导航**：单页签内通过左侧菜单切换 设置 / 取消 / 历史 三个子功能。

### Markdown 转文档
- 📄 **四种格式**：doc / docx / pdf（嵌入系统 TTF 中文字体）/ xlsx。
- 🧩 **完整 Markdown 语法**：标题、段落、代码块、引用、列表、表格、分隔线、行内样式。
- 🪶 **纯标准库渲染**：PDF/DOCX/XLSX 均手写实现。
- ⚙️ **后台导出**：导出在后台线程执行，不卡界面。

### 默认应用清理
- 🔍 **读取默认应用**：扫描常见扩展名（.pdf/.doc/.docx/.xls/.xlsx/.ppt/.txt/.jpg/.mp4 等）与 URL 协议（http/https/mailto/ftp），显示类型、默认应用、ProgId、当前软件名、厂商、产品名、可执行路径、是否被 WPS 占用。
- 🎯 **一键识别 WPS 篡改**：只显示被 WPS / 金山占用或捆绑替换了系统原生默认应用的列表。
- ☑️ **全选 + 一键还原**：全选 WPS 项后一键还原为系统原生默认（删除 UserChoice，立即生效，不受 Windows Hash 保护限制）。
- 🛠️ **手动设置默认**：选中某项后弹窗选择目标程序 ProgId，写入 `HKCU\Software\Classes`，避开 UserChoice Hash 校验生效。
- 🌐 **打开 Windows 设置**：调用 `ms-settings:defaultapps` 作为后备手动设置入口。

### 目录数据同步器
- 🔗 **局域网 TCP 配对**：纯标准库 socket，**程序启动即自动监听**（无需手动启动），配对码首次随机生成并持久化，端口 52000 起自动选择可用端口。
- 📋 **一键复制 / 一键粘贴识别**：顶部直接显示本机连接信息，一键复制到剪贴板（含 IP/端口/配对码/设备名）；连接端一键粘贴并自动识别（容错解析，支持带说明文字、设备名、中英文标点）。
- 📁 **递归同步**：源目录下所有子目录与文件（**含隐藏文件/目录**）递归同步到目标，保留隐藏属性与修改时间。
- 📦 **流式分块传输**：大文件按 64KB 分块流式收发，不一次性读入内存，适合 GB 级大文件；双进度（文件级进度条 + 当前文件字节进度）。
- ➕ **增量不删除**：仅复制/覆盖源已有的文件，不删目标多余文件；同名且大小+修改时间相同则跳过（SKIP，不传文件体），减少传输量。
- 💾 **目标非空先备份**：目标目录非空时，同步前自动把目标全部内容打包成 zip 备份（`目标名_backup_时间戳.zip`），经二次确认后再同步；为空则直接同步。
- 📊 **同步历史日志**：每次同步自动记录到 `sync_log.json`，含时间、方向、对方、文件数（传输/跳过）、数据量、耗时、是否备份、成功与否；页签内「同步历史」按钮可查看与清空。
- 🧭 **设备管理**：生成本机连接信息 / 连接到目标设备 / 已配对设备列表（连接、删除、重新匹配）。
- ⚙️ **后台传输**：传输在后台线程执行，进度条 + 日志区实时反馈，不卡界面。

---

## 🖼️ 界面说明（页签）

- **Markdown 转文档**：编辑/加载 Markdown → 选格式 → 导出。
- **开机启动项管理**：页签内左侧导航切换
  - 设置开机启动：选目录 → 扫描 → 选文件 → 设别名 → 添加（二次确认）。
  - 取消开机启动：`Treeview` 列出 `Run` 键下所有启动项，多选删除（二次确认）。
  - 应用取消历史：按删除时间倒序展示历史，可清空。
- **默认应用清理**：刷新 / 识别WPS篡改 / 显示全部 / 全选WPS / 一键还原 / 手动设置。
- **目录数据同步器**：
  - 顶部自动显示本机连接信息（程序启动即自动监听，无需手动操作），点「一键复制」发给对方。
  - 源端：点「连接设备」→「连接到目标设备」→ 点「一键粘贴识别」自动识别剪贴板里的连接信息并填入（支持带说明文字、设备名），连接成功后保存设备；或在已配对设备下拉框选设备点「连接此设备」。
  - 选源目录（本机）与目标目录（对方机器上的路径）→ 点「开始同步」→ 二次确认 → 后台传输，文件级进度条 + 当前文件字节进度 + 实时日志。
  - 同步完成显示汇总（时间/方向/对方/文件数/数据量/耗时/备份/状态），并自动记录到历史；点「同步历史」查看所有记录。
- **关于**：版本号与项目地址。

---

## 📁 项目结构

分层架构：业务逻辑层纯逻辑（不依赖 GUI 库）、视图层用 tkinter、各功能包独立成目录。

```
PythonToolToexe/
├── main.py                              # 入口：创建 Tk + apply_theme + MainWindow
├── toolbox.spec                         # PyInstaller 打包配置（产物名 ToolBox）
├── app/
│   ├── config.py                        # 全局常量（应用名、版本、注册表路径、导出格式、窗口尺寸）
│   ├── paths.py                         # 程序目录与数据文件路径（兼容 PyInstaller）
│   ├── view/                            # 视图层（tkinter）+ 全局信息（关于页）
│   │   ├── theme.py                     # ttk.Style 配色与全局样式
│   │   ├── context.py                   # FeatureContext（功能包与主窗口契约）
│   │   ├── worker.py                    # threading 后台 Worker + after 主线程回调
│   │   └── main_window.py              # MainWindow：Notebook + 关于页 + 状态栏 + 装配
│   └── features/                        # 各功能包（core 业务逻辑 + view 视图）
│       ├── startup_manager/{core,view}.py   # 开机启动项管理
│       ├── markdown_tools/
│       │   ├── parser.py               # Markdown 解析
│       │   ├── renderers/{doc,docx,xlsx,pdf}.py
│       │   └── view.py
│       ├── default_apps/{core,view}.py  # 默认应用清理（注册表 + 版本信息 + 还原/设置）
│       └── dir_sync/{core,view}.py      # 目录数据同步器（TCP 配对 + 文件传输 + 备份）
└── README.md
```

> 说明：`features/startup_manager/` 是内部模块目录名（开机启动功能的实现），不代表整个应用名称，应用对外的名称为「多能工具箱」。

**依赖方向**：`main_window → feature.view → feature.core → config/paths`。功能包经 `FeatureContext`（`root` + `set_status` + `run_thread` + 对话框 + 剪贴板）与主窗口交互，不反向依赖。业务逻辑层（core/parser/renderers）不依赖 tkinter，可独立复用。

---

## 📁 数据存储位置

| 数据 | 位置 |
|------|------|
| 启动项（注册表） | `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
| 别名记录（文件） | 与 **exe 同目录** 的 `aliases.json` |
| 删除历史（文件） | 与 **exe 同目录** 的 `deleted_startup.json` |
| 默认应用设置（注册表） | `HKCU\...\FileExts\<ext>\UserChoice` 与 `HKCU\Software\Classes` |
| 同步设备记录（文件） | 与 **exe 同目录** 的 `devices.json` |
| 本机配对码（文件） | 与 **exe 同目录** 的 `pair_code.json`（首次随机生成，之后复用） |
| 同步历史日志（文件） | 与 **exe 同目录** 的 `sync_log.json`（保留最近 200 条） |
| 同步备份（文件） | 目标目录同级的 `目标名_backup_时间戳.zip` |

> exe 采用 onefile 模式打包，程序以 exe 自身所在目录为基准读写 json。请把 exe 放到有写入权限、固定不变的目录（如 `D:\Tools\`），不要放在系统保护目录（`C:\Program Files`）。

---

## 🚀 运行与打包

### 环境要求

- **Windows** 10/11（64 位）
- **Python 3.8+**（建议 3.10+），已加入 PATH
- **无需安装任何第三方包**（GUI 用自带 tkinter，业务逻辑全标准库）

### 运行（源码模式）

```bash
cd PythonToolToexe
python main.py
```

### 打包成单文件 exe

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name ToolBox --clean --noconfirm main.py
```

或使用打包配置文件：

```bash
pyinstaller toolbox.spec --noconfirm
```

**参数说明：**

| 参数 | 作用 |
|------|------|
| `--onefile` | 打包为单个 exe 文件 |
| `--noconsole` | 运行时不显示控制台黑窗（适合 GUI 程序） |
| `--name ToolBox` | 指定输出 exe 文件名（生成 `ToolBox.exe`） |
| `--clean` | 清理 PyInstaller 缓存，重新构建 |
| `--noconfirm` | 输出目录已存在时直接覆盖 |

产物位于 `dist\ToolBox.exe`。因 tkinter 随 Python 运行时打包，体积约 **10–12MB**，远小于 Flet/Qt 方案。

### 指定图标（可选）

```bash
pyinstaller --onefile --noconsole --name ToolBox --icon app.ico --clean --noconfirm main.py
```

### 仅使用 exe（不碰源码）

直接双击 `dist\ToolBox.exe` 运行即可，无需安装 Python。

---

## 🧰 技术栈

- 语言：Python 3
- GUI：**tkinter + ttk**（Python 自带，无第三方依赖，无兼容性问题）
- 业务逻辑：winreg、json、threading、os、re、struct、zipfile、ctypes 等标准库
- 文档生成：手写 OOXML / SpreadsheetML / PDF（纯标准库，PDF 嵌入系统 TTF 字体）
- 目录同步：`socket` 自定义 TCP 协议（length-prefixed JSON 头 + 流式分块 body），大文件 64KB 分块流式收发不占内存，`zipfile` 备份
- 可执行文件版本信息：ctypes 调用 version.dll 读取公司名/产品名
- 后台任务：`threading` + `root.after` 回主线程更新 UI（线程安全）
- 打包：PyInstaller

---

## ❓ 常见问题

**Q：双击 exe 没反应 / 闪退？**
A：多半是杀毒软件拦截，或 exe 放在无写入权限的目录。请放到普通用户目录（如桌面、`D:\Tools\`）后再试。

**Q：换台电脑别名没了？**
A：别名存在当前电脑的 `aliases.json`（exe 旁边）和注册表中，换电脑不会自动同步，需在新电脑上重新添加。

**Q：PDF 导出失败提示找不到字体？**
A：PDF 需读取 `C:\Windows\Fonts` 下的 TrueType 字体（.ttf）以支持中文，正常 Windows 系统均自带。

**Q：默认应用"还原"后没立即生效？**
A：还原会删除 UserChoice 并发送 `SHChangeNotify` 通知系统刷新。若个别扩展仍显示旧程序，重启资源管理器或重新打开对应文件即可。

**Q：手动设置默认后系统仍用旧程序？**
A：本工具写 `HKCU\Software\Classes` 避开 UserChoice Hash 校验，删除旧 UserChoice 后即生效。若被组策略或杀软锁定，请用"在 Windows 设置中打开"按钮手动设置。

**Q：怎么彻底卸载？**
A：先在程序里删除所有开机启动项、还原默认应用，再删除 `ToolBox.exe` 和同目录的 `aliases.json`、`deleted_startup.json`、`devices.json`、`pair_code.json`、`sync_log.json` 即可。

**Q：目录同步时连接不上对方设备？**
A：本程序启动即自动监听，对方只要运行着本程序即可被连接。若仍连不上：① 确认两台电脑在同一局域网/同一网段；② **Windows 防火墙首次会弹窗询问是否允许 ToolBox 通信，需点「允许」**（首次运行时触发）；③ 确认 IP、端口、配对码无误（让对方复制其顶部的连接信息发来）；④ 公司网络可能隔离了设备间通信，可尝试用 127.0.0.1 本机自测。

**Q：目录同步的"目标目录"填哪里的路径？**
A：目标目录是**对方（接收端）电脑上的本地路径**，由源端填写后通过协议传给对方执行写入。例如 A 同步到 B，A 填 B 上的 `D:\myfile\test`。B 端不需要手动填目标目录，程序会自动接收并写入。

**Q：目录同步会删除目标里原有的文件吗？**
A：不会。采用增量复制策略，只把源目录里的文件复制/覆盖到目标，不删除目标里源没有的文件。若目标非空，同步前会自动备份整个目标目录为 zip 再继续。
