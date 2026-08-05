"""Run this once to create the default avatar image."""
from PIL import Image, ImageDraw
import os

img = Image.new('RGB', (300, 300), color='#e8f5ee')
draw = ImageDraw.Draw(img)
# Draw a simple person silhouette
draw.ellipse([100, 50, 200, 150], fill='#b2bec3')   # head
draw.ellipse([60, 160, 240, 320], fill='#b2bec3')   # body

path = os.path.join('static', 'img', 'default_avatar.png')
os.makedirs(os.path.dirname(path), exist_ok=True)
img.save(path)
print(f'Default avatar created at {path}')
