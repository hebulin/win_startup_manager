# -*- coding: utf-8 -*-
"""PDF 导出：手写 PDF 文件结构 + 嵌入 Windows 系统 TrueType 字体以支持中文。

包含 TTFFont 字体解析类与 PDF 布局/分页/写入的全部辅助函数。
"""

import os
import io
import struct

from app.features.markdown_tools.parser import parse_inline, _new_run


def _find_system_font():
    """在 Windows Fonts 目录下查找一个可用的 TrueType(.ttf) 字体文件路径"""
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    # 优先选择常见的中文字体（.ttf 优先，避免 .ttc 集合字体的额外解析）
    candidates = ["simhei.ttf", "simfang.ttf", "simsun.ttf", "simkai.ttf",
                  "STSONG.ttf", "STKAITI.ttf", "msyh.ttf", "msyhbd.ttf"]
    for name in candidates:
        p = os.path.join(fonts_dir, name)
        if os.path.isfile(p):
            return p
    # 回退：扫描目录下任意 .ttf 文件
    if os.path.isdir(fonts_dir):
        for fn in os.listdir(fonts_dir):
            if fn.lower().endswith(".ttf"):
                return os.path.join(fonts_dir, fn)
    return None


class TTFFont:
    """解析 TrueType 字体文件的必要表，提供 Unicode->glyph 映射与字符宽度"""

    def __init__(self, data):
        """接收字体文件的原始字节并触发解析"""
        self.data = data
        self.tables = {}       # tag -> (offset, length)
        self.units_per_em = 1000
        self.num_glyphs = 0
        self.num_h_metrics = 0
        self.widths = []       # 每个 glyph 的 advance width（字体单位）
        self.cmap = {}         # unicode 码点 -> glyph id
        self._parse()

    def _u16(self, offset):
        """按大端读取 2 字节无符号整数"""
        return struct.unpack(">H", self.data[offset:offset + 2])[0]

    def _s16(self, offset):
        """按大端读取 2 字节有符号整数"""
        return struct.unpack(">h", self.data[offset:offset + 2])[0]

    def _u32(self, offset):
        """按大端读取 4 字节无符号整数"""
        return struct.unpack(">I", self.data[offset:offset + 4])[0]

    def _parse(self):
        """解析字体偏移表与各必要表"""
        num_tables = self._u16(4)
        # 表目录从偏移 12 开始，每条 16 字节
        for i in range(num_tables):
            rec_off = 12 + i * 16
            tag = self.data[rec_off:rec_off + 4].decode("latin1")
            tbl_off = self._u32(rec_off + 8)
            tbl_len = self._u32(rec_off + 12)
            self.tables[tag] = (tbl_off, tbl_len)
        self._parse_head()
        self._parse_hhea()
        self._parse_maxp()
        self._parse_hmtx()
        self._parse_cmap()

    def _parse_head(self):
        """解析 head 表：取 unitsPerEm 等度量"""
        if "head" not in self.tables:
            return
        off, _ = self.tables["head"]
        self.units_per_em = self._u16(off + 18)

    def _parse_hhea(self):
        """解析 hhea 表：取水平度量表的数量"""
        if "hhea" not in self.tables:
            return
        off, _ = self.tables["hhea"]
        self.num_h_metrics = self._u16(off + 34)

    def _parse_maxp(self):
        """解析 maxp 表：取 glyph 总数"""
        if "maxp" not in self.tables:
            return
        off, _ = self.tables["maxp"]
        self.num_glyphs = self._u16(off + 4)

    def _parse_hmtx(self):
        """解析 hmtx 表：取每个 glyph 的 advance width"""
        if "hmtx" not in self.tables or self.num_h_metrics == 0:
            # 异常时给每个 glyph 一个默认宽度
            self.widths = [self.units_per_em] * self.num_glyphs
            return
        off, _ = self.tables["hmtx"]
        for i in range(self.num_h_metrics):
            self.widths.append(self._u16(off + i * 4))
        # 超过 num_h_metrics 的 glyph 复用最后一个 advance width
        last_w = self.widths[-1] if self.widths else 0
        for _ in range(self.num_glyphs - self.num_h_metrics):
            self.widths.append(last_w)

    def _parse_cmap(self):
        """解析 cmap 表：优先 format 12，其次 format 4，建立 Unicode->glyph 映射"""
        if "cmap" not in self.tables:
            return
        off, _ = self.tables["cmap"]
        num_subtables = self._u16(off + 2)
        best = None  # (子表偏移, 格式)
        for i in range(num_subtables):
            rec = off + 4 + i * 8
            sub_off = self._u32(rec + 4)
            fmt = self._u16(off + sub_off)
            if fmt == 12:
                best = (off + sub_off, 12)
                break
            if fmt == 4 and best is None:
                best = (off + sub_off, 4)
        if best is None:
            return
        if best[1] == 4:
            self._parse_cmap_format4(best[0])
        else:
            self._parse_cmap_format12(best[0])

    def _parse_cmap_format4(self, sub_off):
        """解析 cmap format 4 子表（覆盖 BMP 平面字符）"""
        seg_count_x2 = self._u16(sub_off + 6)
        seg_count = seg_count_x2 // 2
        end_off = sub_off + 14
        start_off = end_off + seg_count_x2 + 2
        delta_off = start_off + seg_count_x2
        range_off = delta_off + seg_count_x2
        for i in range(seg_count):
            end = self._u16(end_off + i * 2)
            if end == 0xFFFF:
                continue
            start = self._u16(start_off + i * 2)
            delta = self._s16(delta_off + i * 2)
            ro = self._u16(range_off + i * 2)
            for c in range(start, end + 1):
                if ro == 0:
                    gid = (c + delta) & 0xFFFF
                else:
                    idx_off = range_off + i * 2 + ro + (c - start) * 2
                    if idx_off + 2 > len(self.data):
                        continue
                    gid = self._u16(idx_off)
                    if gid != 0:
                        gid = (gid + delta) & 0xFFFF
                if gid != 0:
                    self.cmap[c] = gid

    def _parse_cmap_format12(self, sub_off):
        """解析 cmap format 12 子表（覆盖完整 Unicode，含辅助平面）"""
        num_groups = self._u32(sub_off + 12)
        groups_off = sub_off + 16
        for i in range(num_groups):
            rec = groups_off + i * 12
            start_char = self._u32(rec)
            end_char = self._u32(rec + 4)
            start_gid = self._u32(rec + 8)
            for c in range(start_char, end_char + 1):
                self.cmap[c] = start_gid + (c - start_char)

    def glyph_id(self, ch):
        """返回字符对应的 glyph id，找不到返回 0"""
        return self.cmap.get(ord(ch), 0)

    def to_pdf_width(self, gid):
        """返回归一化到 1000 单位的字符宽度（PDF 字体度量单位）"""
        if 0 <= gid < len(self.widths):
            w = self.widths[gid]
        else:
            w = self.units_per_em
        return w * 1000 // self.units_per_em if self.units_per_em else 0


def export_pdf(blocks, output_path):
    """把块结构渲染为 PDF 文件（嵌入 Windows 系统 TrueType 字体以支持中文）"""
    font_path = _find_system_font()
    if not font_path:
        raise RuntimeError("未在 C:\\Windows\\Fonts 下找到可用的 TrueType 字体（.ttf），无法生成中文 PDF。")
    with open(font_path, "rb") as f:
        font_data = f.read()
    font = TTFFont(font_data)

    # A4 页面尺寸（单位 pt），左右上下各留 50pt 边距
    page_w = 595.0
    page_h = 842.0
    margin = 50.0
    base_size = 11.0
    content_w = page_w - margin * 2

    # 布局：把块结构按可用宽度自动换行，生成"逻辑行"列表
    lines = _layout_pdf(blocks, font, content_w, base_size)
    # 分页：按页面高度切分，得到每页的内容流字节
    page_streams = _paginate(lines, font, page_w, page_h, margin, base_size)
    if not page_streams:
        page_streams = [b""]

    # 收集所有用到的字符，用于构建宽度数组与 ToUnicode 反向映射
    chars = _collect_chars(blocks)
    w_array = _build_w_array(font, chars)
    ascent, descent, bbox = _font_metrics(font)
    tounicode = _build_tounicode(font, chars)

    num_pages = len(page_streams)
    # 对象编号约定：1=Catalog, 2=Pages, 3..(2+num_pages)=Page, 4=Type0 字体,
    # 5=CIDFontType2, 6=ToUnicode, 7=FontDescriptor, 8=FontFile2,
    # 9..(8+num_pages)=Content
    content_start = 9
    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join("{0} 0 R".format(3 + i) for i in range(num_pages))
    objects[2] = "<< /Type /Pages /Kids [{0}] /Count {1} >>".format(kids, num_pages).encode("latin1")
    # Type0 字体：用 Identity-H 编码，CID 直接等于 glyph id
    objects[4] = (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /EmbeddedFont "
        b"/Encoding /Identity-H /DescendantFonts [5 0 R] /ToUnicode 6 0 R >>"
    )
    # CIDFontType2：嵌入 TrueType 字体的 CID 字体
    objects[5] = (
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /EmbeddedFont "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        "/FontDescriptor 7 0 R /DW 1000 /W {0} >>".format(w_array).encode("latin1")
    )
    # ToUnicode CMap：glyph id -> Unicode，用于复制粘贴与搜索
    objects[6] = ("<< /Length {0} >>\nstream\n".format(len(tounicode)).encode("latin1")
                  + tounicode + b"\nendstream")
    # FontDescriptor：字体度量与嵌入字体文件引用
    objects[7] = (
        "<< /Type /FontDescriptor /FontName /EmbeddedFont /Flags 32 "
        "/FontBBox [{0} {1} {2} {3}] /ItalicAngle 0 "
        "/Ascent {4} /Descent {5} /CapHeight {4} /StemV 80 "
        "/FontFile2 8 0 R >>".format(bbox[0], bbox[1], bbox[2], bbox[3], ascent, descent).encode("latin1")
    )
    # FontFile2：嵌入的完整 TrueType 字体字节流
    objects[8] = ("<< /Length {0} /Length1 {0} >>\nstream\n".format(len(font_data)).encode("latin1")
                  + font_data + b"\nendstream")
    # 每页 Page 对象与 Content 对象
    for i in range(num_pages):
        objects[3 + i] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {0} {1}] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents {2} 0 R >>".format(
                _fmt(page_w), _fmt(page_h), content_start + i
            ).encode("latin1")
        )
        data = page_streams[i]
        objects[content_start + i] = ("<< /Length {0} >>\nstream\n".format(len(data)).encode("latin1")
                                     + data + b"\nendstream")

    _write_pdf(output_path, objects)


def _layout_pdf(blocks, font, content_w, base_size):
    """把块结构布局为逻辑行列表，每行含 runs、字号、段前距"""
    lines = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            level = block[1]
            # 标题字号：一级 20pt ~ 六级 12pt
            size = max(12.0, 22.0 - (level - 1) * 2.0)
            _wrap_add_lines(lines, parse_inline(block[2]), size, font, content_w, space_before=10.0)
        elif kind == "paragraph":
            _wrap_add_lines(lines, parse_inline(block[1]), base_size, font, content_w, space_before=5.0)
        elif kind == "code":
            for cl in block[2].split("\n"):
                # 代码块用单 run（等宽视觉，仍用嵌入字体）
                _wrap_add_lines(lines, [_new_run(cl if cl else " ")], base_size - 1, font, content_w, space_before=2.0)
        elif kind == "quote":
            for ql in block[1]:
                _wrap_add_lines(lines, parse_inline(ql), base_size, font, content_w - 12.0, space_before=2.0)
        elif kind == "ul":
            for it in block[1]:
                _wrap_add_lines(lines, parse_inline("• " + it), base_size, font, content_w - 12.0, space_before=2.0)
        elif kind == "ol":
            for i, it in enumerate(block[1], 1):
                _wrap_add_lines(lines, parse_inline("{0}. ".format(i) + it), base_size, font, content_w - 12.0, space_before=2.0)
        elif kind == "hr":
            lines.append(([_new_run("-" * 40)], base_size, 6.0))
        elif kind == "table":
            for ri, row in enumerate(block[1]):
                runs = parse_inline(" | ".join(row))
                # 表头行加粗
                if ri == 0:
                    for r in runs:
                        r["bold"] = True
                _wrap_add_lines(lines, runs, base_size, font, content_w, space_before=2.0)
    return lines


def _wrap_add_lines(lines, runs, size, font, max_width, space_before=0.0):
    """按页面宽度对 runs 做自动换行，生成的逻辑行追加到 lines（仅首行带段前距）"""
    # 展平为 (字符, 粗体, 斜体) 序列
    chars = []
    for r in runs:
        for ch in r["text"]:
            chars.append((ch, r.get("bold", False), r.get("italic", False)))

    cur = []
    cur_w = 0.0
    first = True  # 标记是否为本段第一行（用于段前距）

    def emit(seg):
        """把一段字符序列合并为 run 并作为一行加入 lines"""
        nonlocal first
        if not seg:
            first = False
            return
        line_runs = _merge_runs(seg)
        lines.append((line_runs, size, space_before if first else 0.0))
        first = False

    for ch, b, it in chars:
        # 显式换行符：直接断行
        if ch == "\n":
            emit(cur)
            cur = []
            cur_w = 0.0
            continue
        gid = font.glyph_id(ch)
        cw = font.to_pdf_width(gid) / 1000.0 * size
        # 超宽且当前行非空则断行
        if cur and cur_w + cw > max_width:
            emit(cur)
            cur = []
            cur_w = 0.0
        cur.append((ch, b, it))
        cur_w += cw
    emit(cur)


def _merge_runs(chars):
    """把 (字符, 粗体, 斜体) 列表合并为 run 列表（连续同风格字符合并）"""
    runs = []
    buf = []
    cur_b = None
    cur_i = None
    for ch, b, it in chars:
        if cur_b is None:
            cur_b, cur_i = b, it
            buf = [ch]
        elif b == cur_b and it == cur_i:
            buf.append(ch)
        else:
            runs.append({"text": "".join(buf), "bold": cur_b, "italic": cur_i,
                         "code": False, "strike": False, "href": None})
            cur_b, cur_i = b, it
            buf = [ch]
    if buf:
        runs.append({"text": "".join(buf), "bold": cur_b, "italic": cur_i,
                     "code": False, "strike": False, "href": None})
    return runs


def _runs_width(runs, font, size):
    """计算 runs 在指定字号下的总宽度（pt）"""
    total = 0.0
    for r in runs:
        for ch in r["text"]:
            gid = font.glyph_id(ch)
            total += font.to_pdf_width(gid) / 1000.0 * size
    return total


def _encode_glyphs(text, font):
    """把文本编码为 PDF 文本流所需的十六进制字符串（glyph id 序列）"""
    out = []
    for ch in text:
        gid = font.glyph_id(ch)
        out.append("{0:04X}".format(gid))
    return "".join(out)


def _paginate(lines, font, page_w, page_h, margin, base_size):
    """按页面高度对逻辑行分页，返回每页内容流字节列表"""
    pages = []
    cur = io.BytesIO()
    y = page_h - margin
    line_h_factor = 1.5
    for runs, size, space_before in lines:
        # 当前页放不下则换页
        if y - space_before - size * line_h_factor < margin and cur.getvalue():
            pages.append(cur.getvalue())
            cur = io.BytesIO()
            y = page_h - margin
        y -= space_before
        _render_line(cur, runs, margin, y, size, font)
        y -= size * line_h_factor
    if cur.getvalue():
        pages.append(cur.getvalue())
    return pages


def _render_line(cur, runs, x, y, size, font):
    """把一行 runs 渲染为 PDF 内容流（含粗体/斜体模拟）写入缓冲 cur"""
    for r in runs:
        text = r["text"]
        if not text:
            continue
        bold = r.get("bold", False)
        italic = r.get("italic", False)
        hex_str = _encode_glyphs(text, font)
        if not hex_str:
            continue
        w = _runs_width([r], font, size)
        # 斜体用文本矩阵的 c 分量做水平斜切模拟
        c = "0.3" if italic else "0"
        cur.write(b"BT\n")
        cur.write("/F1 {0} Tf\n".format(_fmt(size)).encode("latin1"))
        cur.write("1 0 {0} 1 {1} {2} Tm\n".format(c, _fmt(x), _fmt(y)).encode("latin1"))
        cur.write("<{0}> Tj\n".format(hex_str).encode("latin1"))
        if bold:
            # 粗体模拟：水平偏移 0.5pt 再绘制一遍
            cur.write("1 0 {0} 1 {1} {2} Tm\n".format(c, _fmt(x + 0.5), _fmt(y)).encode("latin1"))
            cur.write("<{0}> Tj\n".format(hex_str).encode("latin1"))
        cur.write(b"ET\n")
        x += w


def _collect_chars(blocks):
    """收集所有块中出现的字符（去重），用于构建宽度数组与 ToUnicode"""
    chars = []
    seen = set()

    def add(text):
        """把文本中的新字符加入收集列表"""
        for ch in text:
            if ch not in seen:
                seen.add(ch)
                chars.append(ch)

    for block in blocks:
        kind = block[0]
        if kind == "heading":
            add(block[2])
        elif kind == "paragraph":
            add(block[1])
        elif kind == "code":
            add(block[2])
        elif kind == "quote":
            for ql in block[1]:
                add(ql)
        elif kind in ("ul", "ol"):
            for it in block[1]:
                add(it)
        elif kind == "table":
            for row in block[1]:
                for cell in row:
                    add(cell)
    return chars


def _build_w_array(font, chars):
    """构建 CIDFont 的 W 宽度数组字符串（gid gid width 形式）"""
    seen = set()
    items = []
    for ch in chars:
        gid = font.glyph_id(ch)
        if gid == 0 or gid in seen:
            continue
        seen.add(gid)
        items.append((gid, font.to_pdf_width(gid)))
    items.sort()
    parts = ["{0} {1} {2}".format(gid, gid, w) for gid, w in items]
    return "[" + " ".join(parts) + "]"


def _build_tounicode(font, chars):
    """构建 ToUnicode CMap 字节流，建立 glyph id -> Unicode 的反向映射"""
    header = (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin\n"
        b"begincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n"
        b"/CMapType 2 def\n"
        b"1 begincodespacerange\n"
        b"<0000> <FFFF>\n"
        b"endcodespacerange\n"
    )
    # 收集 (gid, unicode) 对并排序
    pairs = []
    for ch in chars:
        gid = font.glyph_id(ch)
        if gid == 0:
            continue
        pairs.append((gid, ord(ch)))
    pairs = sorted(set(pairs))
    body = io.BytesIO()
    i = 0
    # bfchar 每段最多 100 条
    while i < len(pairs):
        chunk = pairs[i:i + 100]
        body.write("{0} beginbfchar\n".format(len(chunk)).encode("latin1"))
        for gid, uni in chunk:
            body.write("<{0:04X}> <{1:04X}>\n".format(gid, uni).encode("latin1"))
        body.write(b"endbfchar\n")
        i += 100
    footer = b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    return header + body.getvalue() + footer


def _font_metrics(font):
    """从 head/hhea 表读取 ascent/descent 与 BBox（归一化到 1000 单位）"""
    scale = 1000.0 / font.units_per_em if font.units_per_em else 1.0
    head_off, _ = font.tables.get("head", (0, 0))
    hhea_off, _ = font.tables.get("hhea", (0, 0))
    ascent = int(round(font._s16(hhea_off + 4) * scale)) if hhea_off else 800
    descent = int(round(font._s16(hhea_off + 6) * scale)) if hhea_off else -200
    if head_off:
        x_min = int(round(font._s16(head_off + 36) * scale))
        y_min = int(round(font._s16(head_off + 38) * scale))
        x_max = int(round(font._s16(head_off + 40) * scale))
        y_max = int(round(font._s16(head_off + 42) * scale))
        bbox = (x_min, y_min, x_max, y_max)
    else:
        bbox = (-100, -200, 1000, 800)
    return ascent, descent, bbox


def _fmt(x):
    """格式化浮点数为 PDF 文本（最多 3 位小数，去尾零）"""
    s = "{0:.3f}".format(x).rstrip("0").rstrip(".")
    return s if s else "0"


def _write_pdf(output_path, objects):
    """把对象字典写入标准 PDF 文件（含 xref 交叉引用表与 trailer）"""
    max_obj = max(objects.keys())
    with open(output_path, "wb") as f:
        f.write(b"%PDF-1.4\n")
        # 二进制标记，让 PDF 阅读器按二进制处理
        f.write(b"%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(objects.keys()):
            offsets[num] = f.tell()
            f.write("{0} 0 obj\n".format(num).encode("latin1"))
            obj = objects[num]
            f.write(obj if isinstance(obj, bytes) else obj.encode("latin1"))
            f.write(b"\nendobj\n")
        xref_off = f.tell()
        f.write("xref\n0 {0}\n".format(max_obj + 1).encode("latin1"))
        f.write(b"0000000000 65535 f \n")
        for num in range(1, max_obj + 1):
            off = offsets.get(num, 0)
            f.write("{0:010d} 00000 n \n".format(off).encode("latin1"))
        f.write(
            "trailer\n<< /Size {0} /Root 1 0 R >>\nstartxref\n{1}\n%%EOF".format(max_obj + 1, xref_off).encode("latin1")
        )
