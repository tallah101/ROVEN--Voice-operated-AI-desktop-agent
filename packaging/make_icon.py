"""Creates packaging/roven.ico (multi-size) used by the EXE, installer and Start-menu shortcut."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).with_name("roven.ico")
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((8, 8, 248, 248), fill=(124, 156, 255, 255))
d.ellipse((28, 28, 228, 228), fill=(20, 22, 27, 255))
try:
    font = ImageFont.truetype("segoeuib.ttf", 150)
except OSError:
    font = ImageFont.load_default()
d.text((128, 132), "R", fill=(124, 156, 255, 255), font=font, anchor="mm")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
