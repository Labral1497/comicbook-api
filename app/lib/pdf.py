# app/lib/pdf.py
from typing import List
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app import logger

log = logger.get_logger(__name__)

def make_pdf(files: List[str], pdf_name: str = "comic.pdf") -> str:
    log.info(f"Combining {len(files)} pages into PDF: {pdf_name}")
    c = canvas.Canvas(pdf_name, pagesize=A4)
    w, h = A4
    for file in files:
        img = Image.open(file)
        img_ratio = img.width / img.height
        if w / h > img_ratio:
            ih = h
            iw = ih * img_ratio
        else:
            iw = w
            ih = iw / img_ratio
        x = (w - iw) / 2
        y = (h - ih) / 2
        c.drawImage(file, x, y, iw, ih)
        c.showPage()
    c.save()
    print(f"📄 Comic saved as {pdf_name}")
    return pdf_name
