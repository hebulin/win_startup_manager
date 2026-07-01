# -*- coding: utf-8 -*-
"""全局配置：版本、URL、注册表路径、扩展名、导出格式、窗口尺寸。

所有模块统一从此处取常量，避免历史代码中 APP_VERSION 两处不一致的问题。
本文件只定义常量，不包含任何逻辑，不依赖 app 内其他模块。
"""

# 应用名称与版本号（多功能集成工具箱）
APP_NAME = "多能工具箱"
APP_VERSION = "2.3.0"

# 项目地址（用于"关于"页展示与跳转）
PROJECT_URL = "https://github.com/hebulin/win_startup_manager"

# 注册表 Run 键的固定路径（HKCU 下，不需要管理员权限）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# 需要扫描的可执行文件扩展名
TARGET_EXTS = (".exe", ".bat", ".cmd")

# 主窗口尺寸（宽 x 高），启动时按此尺寸居中显示
# 重构后加入"默认应用清理"页签（表格列多），窗口加宽
WINDOW_WIDTH = 1040
WINDOW_HEIGHT = 700

# 支持的 Markdown 导出格式配置：(键, 下拉显示文本, 默认扩展名, 文件类型过滤器)
EXPORT_FORMATS = [
    ("doc", "Word 文档 (.doc)", ".doc", [("Word 文档", "*.doc"), ("所有文件", "*.*")]),
    ("docx", "Word 文档 (.docx)", ".docx", [("Word 文档", "*.docx"), ("所有文件", "*.*")]),
    ("pdf", "PDF 文档 (.pdf)", ".pdf", [("PDF 文档", "*.pdf"), ("所有文件", "*.*")]),
    ("xlsx", "Excel 表格 (.xlsx)", ".xlsx", [("Excel 表格", "*.xlsx"), ("所有文件", "*.*")]),
]
