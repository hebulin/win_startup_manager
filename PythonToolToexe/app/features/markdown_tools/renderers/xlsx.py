# -*- coding: utf-8 -*-
"""XLSX 导出：手写最小化 SpreadsheetML（zip 包），纯标准库。"""

import io
import zipfile

from app.features.markdown_tools.parser import parse_inline, _plain_text, _xml_escape


def export_xlsx(blocks, output_path):
    """把块结构导出为 .xlsx 文件（手写 SpreadsheetML zip 包）"""
    rows = _xlsx_rows(blocks)
    buf = io.BytesIO()
    zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    zf.writestr("[Content_Types].xml", _xlsx_content_types())
    zf.writestr("_rels/.rels", _xlsx_root_rels())
    zf.writestr("xl/workbook.xml", _xlsx_workbook())
    zf.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_rels())
    zf.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet(rows))
    zf.close()
    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


def _xlsx_rows(blocks):
    """把块结构展开为 Excel 行（每行一个单元格文本列表）"""
    rows = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            rows.append(["#" * block[1] + " " + _plain_text(parse_inline(block[2]))])
        elif kind == "paragraph":
            rows.append([_plain_text(parse_inline(block[1]))])
        elif kind == "code":
            for l in block[2].split("\n"):
                rows.append([l if l else ""])
        elif kind == "quote":
            for l in block[1]:
                rows.append(["> " + _plain_text(parse_inline(l))])
        elif kind == "ul":
            for it in block[1]:
                rows.append(["• " + _plain_text(parse_inline(it))])
        elif kind == "ol":
            for i, it in enumerate(block[1], 1):
                rows.append(["{0}. ".format(i) + _plain_text(parse_inline(it))])
        elif kind == "hr":
            rows.append(["-" * 30])
        elif kind == "table":
            for row in block[1]:
                rows.append([_plain_text(parse_inline(c)) for c in row])
    return rows


def _xlsx_col_letter(ci):
    """把 0 基列号转为 Excel 列字母（0->A, 25->Z, 26->AA）"""
    s = ""
    ci += 1
    while ci > 0:
        ci, rem = divmod(ci - 1, 26)
        s = chr(65 + rem) + s
    return s


def _xlsx_sheet(rows):
    """生成 sheet1.xml 内容（使用内联字符串 t=inlineStr，避免 sharedStrings 复杂度）"""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetData>']
    for ri, row in enumerate(rows, 1):
        out.append('<row r="{0}">'.format(ri))
        for ci, cell in enumerate(row):
            ref = "{0}{1}".format(_xlsx_col_letter(ci), ri)
            t = _xml_escape(cell)
            out.append('<c r="{0}" t="inlineStr"><is><t xml:space="preserve">{1}</t></is></c>'.format(ref, t))
        out.append('</row>')
    out.append('</sheetData></worksheet>')
    return "".join(out)


def _xlsx_content_types():
    """生成 xlsx 的 [Content_Types].xml"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )


def _xlsx_root_rels():
    """生成 xlsx 的包级关系 _rels/.rels"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _xlsx_workbook():
    """生成 xl/workbook.xml（声明一个名为 Sheet1 的工作表）"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Markdown" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )


def _xlsx_workbook_rels():
    """生成 xl/_rels/workbook.xml.rels（指向 sheet1.xml）"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
