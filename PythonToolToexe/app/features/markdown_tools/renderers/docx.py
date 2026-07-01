# -*- coding: utf-8 -*-
"""DOCX 导出：手写最小化 OOXML（zip 包），纯标准库。"""

import io
import zipfile

from app.features.markdown_tools.parser import parse_inline, _xml_escape, _new_run


def export_docx(blocks, output_path):
    """把块结构导出为 .docx 文件（手写 OOXML zip 包）"""
    buf = io.BytesIO()
    zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    # [Content_Types].xml：声明 rels 与 xml 默认类型，并覆盖 document.xml 的类型
    zf.writestr("[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
    # _rels/.rels：包级关系，指向 word/document.xml
    zf.writestr("_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="word/document.xml"/>'
                '</Relationships>')
    # word/_rels/document.xml.rels：文档级关系（本实现无图片等外部资源，留空）
    zf.writestr("word/_rels/document.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    # word/document.xml：正文
    body_parts = []
    for block in blocks:
        body_parts.append(_docx_block(block))
    # 节属性：A4 纵向页面
    body_parts.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + "".join(body_parts) + '</w:body></w:document>'
    )
    zf.writestr("word/document.xml", document)
    zf.close()
    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


def _docx_block(block):
    """把单个块渲染为 docx 的段落/表格 XML 片段"""
    kind = block[0]
    if kind == "heading":
        # 标题字号（半磅）：一级 28pt ~ 六级 11pt
        sizes = [56, 44, 36, 30, 26, 24]
        sz = sizes[min(block[1] - 1, 5)]
        return _docx_paragraph(parse_inline(block[2]), sz_half=sz, bold=True, outline=min(block[1] - 1, 8))
    if kind == "paragraph":
        return _docx_paragraph(parse_inline(block[1]), sz_half=24)
    if kind == "code":
        # 代码块每行作为一个等宽段落
        lines = block[2].split("\n") or [""]
        return "".join(
            _docx_paragraph([_code_run(l if l else " ")], sz_half=20)
            for l in lines
        )
    if kind == "quote":
        return "".join(_docx_paragraph(parse_inline(l), sz_half=24, indent=480) for l in block[1])
    if kind == "ul":
        return "".join(_docx_paragraph(parse_inline("• " + it), sz_half=24, indent=240) for it in block[1])
    if kind == "ol":
        return "".join(
            _docx_paragraph(parse_inline("{0}. ".format(i) + it), sz_half=24, indent=240)
            for i, it in enumerate(block[1], 1)
        )
    if kind == "hr":
        # 分隔线：段落底边框
        return ('<w:p><w:pPr><w:pBdr>'
                '<w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/>'
                '</w:pBdr></w:pPr></w:p>')
    if kind == "table":
        return _docx_table(block[1])
    return ""


def _code_run(text):
    """构造一个代码样式的 run（等宽字体）"""
    r = _new_run(text)
    r["code"] = True
    return r


def _docx_paragraph(runs, sz_half=24, bold=False, italic=False, indent=0, align=None, outline=None):
    """生成一个 docx 段落 XML，根据各 run 的样式生成对应 run 节点"""
    ppr = []
    if outline is not None:
        ppr.append('<w:outlineLvl w:val="{0}"/>'.format(outline))
    if indent:
        ppr.append('<w:ind w:left="{0}"/>'.format(indent))
    if align:
        ppr.append('<w:jc w:val="{0}"/>'.format(align))
    ppr_xml = "<w:pPr>{0}</w:pPr>".format("".join(ppr)) if ppr else ""

    out = ["<w:p>", ppr_xml]
    for r in runs:
        # 基础 run 属性：字体 + 字号
        if r.get("code"):
            rpr = ('<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="宋体"/>'
                   '<w:sz w:val="{0}"/><w:szCs w:val="{0}"/>'.format(sz_half))
        else:
            rpr = ('<w:rPr><w:rFonts w:ascii="宋体" w:eastAsia="宋体" w:hAnsi="宋体"/>'
                   '<w:sz w:val="{0}"/><w:szCs w:val="{0}"/>'.format(sz_half))
        if bold or r.get("bold"):
            rpr += "<w:b/>"
        if italic or r.get("italic"):
            rpr += "<w:i/>"
        if r.get("strike"):
            rpr += "<w:strike/>"
        rpr += "</w:rPr>"
        text = _xml_escape(r["text"])
        out.append("<w:r>{0}<w:t xml:space=\"preserve\">{1}</w:t></w:r>".format(rpr, text))
    out.append("</w:p>")
    return "".join(out)


def _docx_table(rows):
    """把二维表格渲染为 docx 表格 XML（含四周边框与内边框）"""
    borders = (
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '</w:tblBorders>'
    )
    out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>', borders, '</w:tblPr>']
    for ri, row in enumerate(rows):
        out.append("<w:tr>")
        for cell in row:
            # 表头行加粗
            para = _docx_paragraph(parse_inline(cell), sz_half=24, bold=(ri == 0))
            out.append('<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr>{0}</w:tc>'.format(para))
        out.append("</w:tr>")
    out.append("</w:tbl>")
    # docx 规范要求表格后跟一个段落
    out.append("<w:p/>")
    return "".join(out)
