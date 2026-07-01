# -*- coding: utf-8 -*-
"""应用根包：开机启动管理器 + Markdown 转文档的分层重构实现。

子包：
- config / paths：全局常量与路径工具（兼容 PyInstaller 打包）。
- view：视图层骨架（主题、主窗口、功能上下文）。
- features：各功能包（每个功能一个独立目录，含 core 业务逻辑 + view 视图）。
"""
