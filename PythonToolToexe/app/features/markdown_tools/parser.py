# -*- coding: utf-8 -*-
"""Markdown 解析：把 Markdown 文本解析为统一的"块结构"与行内 run 列表，供各渲染器共用。

本模块定义块/行内数据模型与共享文本工具（XML 转义、run 字典构造等），
渲染器统一从此处导入这些工具，避免重复定义。
"""

import re


def parse_blocks(md_text):
    """把 Markdown 文本解析为块级结构列表，每个元素是一个 tuple，首元素为块类型。"""
    # 统一换行符，便于按行处理
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # 空行直接跳过
        if not line.strip():
            i += 1
            continue
        # 代码块围栏 ```lang
        if line.lstrip().startswith("```"):
            code_lang = line.lstrip()[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏（若存在）
            blocks.append(("code", code_lang, "\n".join(code_lines)))
            continue
        # 标题 # ~ ######
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            blocks.append(("heading", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue
        # 分隔线 --- / *** / ___（至少 3 个同类符号，可含空格）
        stripped = line.strip()
        if stripped and set(stripped) <= set("-*_ ") and len(stripped.replace(" ", "")) >= 3:
            blocks.append(("hr",))
            i += 1
            continue
        # 表格：当前行含 | 且下一行为分隔行
        if "|" in line and i + 1 < n and _is_table_separator(lines[i + 1]):
            header = _split_table_row(line)
            i += 2
            rows = [header]
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            blocks.append(("table", rows))
            continue
        # 引用 >
        if line.lstrip().startswith(">"):
            quote_lines = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote_lines.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            blocks.append(("quote", quote_lines))
            continue
        # 无序列表 - / * / +
        if re.match(r"^\s*[-*+]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]))
                i += 1
            blocks.append(("ul", items))
            continue
        # 有序列表 1.
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            blocks.append(("ol", items))
            continue
        # 其余视为段落：连续收集直到遇到块级起始符或空行
        para_lines = [line]
        i += 1
        while i < n:
            nl = lines[i]
            if not nl.strip():
                break
            if nl.lstrip().startswith("```"):
                break
            if re.match(r"^#{1,6}\s", nl):
                break
            if nl.lstrip().startswith(">"):
                break
            if re.match(r"^\s*[-*+]\s", nl):
                break
            if re.match(r"^\s*\d+\.\s", nl):
                break
            if "|" in nl and i + 1 < n and _is_table_separator(lines[i + 1]):
                break
            para_lines.append(nl)
            i += 1
        # 段落内单换行按 Markdown 惯例合并为空格
        blocks.append(("paragraph", " ".join(s.strip() for s in para_lines)))
    return blocks


def _is_table_separator(line):
    """判断一行是否为 Markdown 表格的分隔行（如 |---|:--:|）"""
    if "-" not in line or "|" not in line:
        return False
    # 只允许 | 、- 、: 、空格
    return set(line) <= set("|-: ")


def _split_table_row(line):
    """按 | 分割表格行，并去掉首尾多余的空单元格"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


# 行内标记正则：依次匹配代码、图片、链接、粗体、斜体、删除线
_INLINE_RE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|!\[(?P<imgalt>[^\]]*)\]\((?P<imgurl>[^)]+)\)"
    r"|\[(?P<lnktext>[^\]]+)\]\((?P<lnkurl>[^)]+)\)"
    r"|\*\*(?P<bold2>[^*]+)\*\*"
    r"|__(?P<boldu>[^_]+)__"
    r"|\*(?P<italic1>[^*]+)\*"
    r"|_(?P<italicu>[^_]+)_"
    r"|~~(?P<strike>[^~]+)~~"
)


def parse_inline(text):
    """解析行内 Markdown 标记，返回 run 列表，每个 run 是带样式的 dict"""
    runs = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        # 匹配前的纯文本作为普通 run
        if m.start() > pos:
            runs.append(_new_run(text[pos:m.start()]))
        if m.group("code") is not None:
            r = _new_run(m.group("code"))
            r["code"] = True
            runs.append(r)
        elif m.group("imgalt") is not None:
            # 图片无样式，仅显示占位文本 [alt]
            runs.append(_new_run("[" + (m.group("imgalt") or "图片") + "]"))
        elif m.group("lnktext") is not None:
            r = _new_run(m.group("lnktext"))
            r["href"] = m.group("lnkurl")
            runs.append(r)
        elif m.group("bold2") is not None or m.group("boldu") is not None:
            r = _new_run(m.group("bold2") or m.group("boldu"))
            r["bold"] = True
            runs.append(r)
        elif m.group("italic1") is not None or m.group("italicu") is not None:
            r = _new_run(m.group("italic1") or m.group("italicu"))
            r["italic"] = True
            runs.append(r)
        elif m.group("strike") is not None:
            r = _new_run(m.group("strike"))
            r["strike"] = True
            runs.append(r)
        pos = m.end()
    # 末尾剩余纯文本
    if pos < len(text):
        runs.append(_new_run(text[pos:]))
    return runs


def _new_run(text):
    """创建一个带默认样式字段的 run 字典"""
    return {"text": text, "bold": False, "italic": False,
            "code": False, "strike": False, "href": None}


def _plain_text(runs):
    """把 run 列表合并为纯文本（丢弃所有样式标记），供 xlsx 等使用"""
    return "".join(r["text"] for r in runs)


def _xml_escape(text):
    """转义 XML 文本节点中的特殊字符"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr_escape(text):
    """转义 XML 属性值中的特殊字符"""
    return _xml_escape(text).replace('"', "&quot;")
