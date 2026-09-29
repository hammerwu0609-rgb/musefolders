"""Assemble page renders into full-resolution 2x2 review sheets."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent / ".qa_handoff_word"
PAGES = sorted(ROOT.glob("page-*.png"))
FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")
FONT = ImageFont.truetype(str(FONT_PATH), 28) if FONT_PATH.exists() else None

for start in range(0, len(PAGES), 4):
    group = PAGES[start : start + 4]
    images = [Image.open(path).convert("RGB") for path in group]
    max_w = max(image.width for image in images)
    max_h = max(image.height for image in images)
    sheet = Image.new("RGB", (max_w * 2 + 72, max_h * 2 + 110), "#E8EDF2")
    draw = ImageDraw.Draw(sheet)
    for offset, (path, page) in enumerate(zip(group, images)):
        col, row = offset % 2, offset // 2
        x, y = 24 + col * (max_w + 24), 45 + row * (max_h + 35)
        sheet.paste(page, (x, y))
        draw.text((x, y - 32), path.stem, fill="#244052", font=FONT)
    result = ROOT / f"sheet-{start // 4 + 1:02d}.png"
    sheet.save(result)
    print(result)
