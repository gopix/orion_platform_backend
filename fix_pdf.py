"""
Standalone script: apply ToUnicode CMap fix to any PDF.
Usage: python fix_pdf.py input.pdf
Output: input_fixed.pdf in the same folder
"""
import sys
import shutil
from pathlib import Path

# ── inline the font_encoding_fixer so it works without the server ──────────
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject,
    NameObject, NumberObject, StreamObject,
)

_WINANSI_MAP = {
    0x20: 0x0020, 0x21: 0x0021, 0x22: 0x0022, 0x23: 0x0023, 0x24: 0x0024,
    0x25: 0x0025, 0x26: 0x0026, 0x27: 0x0027, 0x28: 0x0028, 0x29: 0x0029,
    0x2A: 0x002A, 0x2B: 0x002B, 0x2C: 0x002C, 0x2D: 0x002D, 0x2E: 0x002E,
    0x2F: 0x002F, 0x30: 0x0030, 0x31: 0x0031, 0x32: 0x0032, 0x33: 0x0033,
    0x34: 0x0034, 0x35: 0x0035, 0x36: 0x0036, 0x37: 0x0037, 0x38: 0x0038,
    0x39: 0x0039, 0x3A: 0x003A, 0x3B: 0x003B, 0x3C: 0x003C, 0x3D: 0x003D,
    0x3E: 0x003E, 0x3F: 0x003F, 0x40: 0x0040, 0x41: 0x0041, 0x42: 0x0042,
    0x43: 0x0043, 0x44: 0x0044, 0x45: 0x0045, 0x46: 0x0046, 0x47: 0x0047,
    0x48: 0x0048, 0x49: 0x0049, 0x4A: 0x004A, 0x4B: 0x004B, 0x4C: 0x004C,
    0x4D: 0x004D, 0x4E: 0x004E, 0x4F: 0x004F, 0x50: 0x0050, 0x51: 0x0051,
    0x52: 0x0052, 0x53: 0x0053, 0x54: 0x0054, 0x55: 0x0055, 0x56: 0x0056,
    0x57: 0x0057, 0x58: 0x0058, 0x59: 0x0059, 0x5A: 0x005A, 0x5B: 0x005B,
    0x5C: 0x005C, 0x5D: 0x005D, 0x5E: 0x005E, 0x5F: 0x005F, 0x60: 0x0060,
    0x61: 0x0061, 0x62: 0x0062, 0x63: 0x0063, 0x64: 0x0064, 0x65: 0x0065,
    0x66: 0x0066, 0x67: 0x0067, 0x68: 0x0068, 0x69: 0x0069, 0x6A: 0x006A,
    0x6B: 0x006B, 0x6C: 0x006C, 0x6D: 0x006D, 0x6E: 0x006E, 0x6F: 0x006F,
    0x70: 0x0070, 0x71: 0x0071, 0x72: 0x0072, 0x73: 0x0073, 0x74: 0x0074,
    0x75: 0x0075, 0x76: 0x0076, 0x77: 0x0077, 0x78: 0x0078, 0x79: 0x0079,
    0x7A: 0x007A, 0x7B: 0x007B, 0x7C: 0x007C, 0x7D: 0x007D, 0x7E: 0x007E,
    0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026,
    0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030, 0x8A: 0x0160,
    0x8B: 0x2039, 0x8C: 0x0152, 0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019,
    0x93: 0x201C, 0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
    0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153,
    0x9E: 0x017E, 0x9F: 0x0178,
    **{i: i for i in range(0xA0, 0x100)},
}

def _build_cmap(cmap_dict):
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        f"{len(cmap_dict)} beginbfchar",
    ]
    for src, dst in sorted(cmap_dict.items()):
        lines.append(f"<{src:02X}> <{dst:04X}>")
    lines += ["endbfchar", "endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("latin-1")

def _needs_tounicode(font_dict):
    if "/ToUnicode" in font_dict:
        return False
    subtype = font_dict.get("/Subtype", "")
    if hasattr(subtype, "original_bytes"):
        subtype = str(subtype)
    enc = font_dict.get("/Encoding", "")
    base = font_dict.get("/BaseFont", "")
    subtype_s = str(subtype)
    enc_s = str(enc)
    base_s = str(base)
    return (
        subtype_s in ("/Type1", "/TrueType", "/MMType1")
        or "WinAnsi" in enc_s
        or "MacRoman" in enc_s
        or "StandardEncoding" in enc_s
    )

def fix_pdf(input_path, output_path):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    writer.clone_reader_document_root(reader)

    patched = 0
    for page in writer.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        fonts = resources.get("/Font")
        if not fonts:
            continue
        if hasattr(fonts, "get_object"):
            fonts = fonts.get_object()
        for fname in list(fonts.keys()):
            font_ref = fonts[fname]
            font_dict = font_ref.get_object() if hasattr(font_ref, "get_object") else font_ref
            if not isinstance(font_dict, DictionaryObject):
                continue
            if not _needs_tounicode(font_dict):
                continue
            cmap_data = _build_cmap(_WINANSI_MAP)
            stream = DecodedStreamObject()
            stream.set_data(cmap_data)
            stream.update({
                NameObject("/Filter"): NameObject("/FlateDecode"),
            })
            ref = writer._add_object(stream)
            font_dict[NameObject("/ToUnicode")] = ref
            patched += 1

    with open(output_path, "wb") as f:
        writer.write(f)
    return patched

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_pdf.py input.pdf")
        sys.exit(1)
    inp = Path(sys.argv[1])
    if not inp.exists():
        print(f"File not found: {inp}")
        sys.exit(1)
    out = inp.with_name(inp.stem + "_FIXED.pdf")
    print(f"Input:  {inp}")
    print(f"Output: {out}")
    n = fix_pdf(str(inp), str(out))
    print(f"Done — patched {n} fonts. Open {out.name} in Acrobat.")
