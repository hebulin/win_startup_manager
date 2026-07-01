# -*- coding: utf-8 -*-
"""DOC 渲染：HTML 内容 + Office 命名空间头，Word 可直接打开。

doc 导出本质是带 Office 命名空间的 HTML，故 HTML 渲染与 doc 导出合并在本文件。
"""

from app.features.markdown_tools.parser import parse_inline, _xml_escape, _xml_attr_escape


def render_html(blocks):
    """把块结构渲染为 HTML 字符串"""
    html = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            lvl = block[1]
            html.append("<h{0}>{1}</h{0}>".format(lvl, _inline_html(parse_inline(block[2]))))
        elif kind == "paragraph":
            html.append("<p>{0}</p>".format(_inline_html(parse_inline(block[1]))))
        elif kind == "code":
            html.append("<pre><code>{0}</code></pre>".format(_xml_escape(block[2])))
        elif kind == "quote":
            inner = "<br/>".join(_xml_escape(l) for l in block[1])
            html.append("<blockquote>{0}</blockquote>".format(inner))
        elif kind == "ul":
            items = "".join("<li>{0}</li>".format(_inline_html(parse_inline(it))) for it in block[1])
            html.append("<ul>{0}</ul>".format(items))
        elif kind == "ol":
            items = "".join("<li>{0}</li>".format(_inline_html(parse_inline(it))) for it in block[1])
            html.append("<ol>{0}</ol>".format(items))
        elif kind == "hr":
            html.append("<hr/>")
        elif kind == "table":
            rows = block[1]
            head = rows[0]
            body = rows[1:]
            thead = "".join("<th>{0}</th>".format(_xml_escape(c)) for c in head)
            tbody = "".join(
                "<tr>{0}</tr>".format("".join("<td>{0}</td>".format(_xml_escape(c)) for c in r))
                for r in body
            )
            html.append('<table border="1"><thead><tr>{0}</tr></thead><tbody>{1}</tbody></table>'.format(thead, tbody))
    return "\n".join(html)


def _inline_html(runs):
    """把 run 列表渲染为 HTML 内联片段"""
    out = []
    for r in runs:
        t = _xml_escape(r["text"])
        if r.get("code"):
            out.append("<code>{0}</code>".format(t))
        elif r.get("href"):
            out.append('<a href="{0}">{1}</a>'.format(_xml_attr_escape(r["href"]), t))
        else:
            if r.get("bold"):
                t = "<b>{0}</b>".format(t)
            if r.get("italic"):
                t = "<i>{0}</i>".format(t)
            if r.get("strike"):
                t = "<s>{0}</s>".format(t)
            out.append(t)
    return "".join(out)


def export_doc(blocks, output_path):
    """把块结构导出为 .doc 文件（本质是带 Office 命名空间的 HTML，Word 可直接打开）"""
    body = render_html(blocks)
    # 加入 Office 命名空间与 WordDocument 指令，让 Word 识别为文档并按打印视图打开
    doc = (
        "<!DOCTYPE html>"
        "<html xmlns:o='urn:schemas-microsoft-com:office:office' "
        "xmlns:w='urn:schemas-microsoft-com:office:word' "
        "xmlns='http://www.w3.org/TR/REC-html40'>"
        "<head><meta charset='utf-8'>"
        "<!--[if gte mso 9]><xml><w:WordDocument>"
        "<w:View>Print</w:View><w:Zoom>100</w:Zoom>"
        "</w:WordDocument></xml><![endif]-->"
        "<style>"
        "body{font-family:'宋体';font-size:12pt;line-height:1.6;}"
        "h1{font-size:20pt;}h2{font-size:16pt;}h3{font-size:14pt;}"
        "h4{font-size:13pt;}h5{font-size:12pt;}h6{font-size:11pt;}"
        "pre{font-family:Consolas,monospace;background:#f5f5f5;padding:8px;}"
        "blockquote{border-left:3px solid #ccc;padding-left:8px;color:#555;}"
        "table{border-collapse:collapse;} th,td{border:1px solid #000;padding:4px 8px;}"
        "th{background:#eee;}"
        "</style></head><body>" + body + "</body></html>"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)
