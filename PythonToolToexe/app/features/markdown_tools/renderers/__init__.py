# -*- coding: utf-8 -*-
"""Markdown 渲染器注册与统一导出入口。

各格式渲染器（doc/docx/xlsx/pdf）互不依赖，统一在此处分发。
"""

from app.features.markdown_tools.parser import parse_blocks
from app.features.markdown_tools.renderers import doc, docx, xlsx, pdf

# 格式键 -> 渲染函数
_DISPATCH = {
    "doc": doc.export_doc,
    "docx": docx.export_docx,
    "pdf": pdf.export_pdf,
    "xlsx": xlsx.export_xlsx,
}


def export_markdown(md_text, fmt, output_path):
    """解析 Markdown 并按指定格式键导出到 output_path。不支持 fmt 抛 ValueError。"""
    blocks = parse_blocks(md_text)
    func = _DISPATCH.get(fmt)
    if func is None:
        raise ValueError("不支持的导出格式：{0}".format(fmt))
    func(blocks, output_path)
