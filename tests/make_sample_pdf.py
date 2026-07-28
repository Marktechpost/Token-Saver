#!/usr/bin/env python3
"""make_sample_pdf.py - write a tiny, valid, multi-page TEXT pdf with no deps.

For dry-running the index/retrieve pipeline without needing a real PDF.
Each page has a distinct topic so semantic vs keyword behavior is observable.

Usage:
  python tests/make_sample_pdf.py /tmp/sample.pdf
"""
import sys
from pathlib import Path

PAGES = [
    "Chapter 1 Introduction. This document defines EBITDA as earnings before "
    "interest taxes depreciation and amortization. See section 4 for revenue recognition.",
    "Chapter 2 Market Overview. The widget market grew twelve percent. "
    "Competitors include Acme and Globex in the consumer segment.",
    "Chapter 3 Operations. Manufacturing throughput improved. Supply chain costs "
    "fell after renegotiating vendor contracts in the second quarter.",
    "Section 4 Revenue Recognition. For SaaS subscriptions revenue is recognized "
    "ratably over the contract term under the performance obligation model.",
    "Chapter 5 Risk Factors. Currency exposure and customer concentration remain "
    "the principal risks. EBITDA could decline if churn rises sharply.",
]


def make_pdf(path, pages_text=PAGES):
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages_text)))
    objs.append(f"<< /Type /Pages /Count {len(pages_text)} /Kids [{kids}] >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, t in enumerate(pages_text):
        content = f"BT /F1 11 Tf 50 750 Td ({esc(t)}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    Path(path).write_bytes(out)
    return Path(path)


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sample.pdf"
    p = make_pdf(dest)
    print(f"wrote {p}  ({p.stat().st_size} bytes, {len(PAGES)} pages)")
