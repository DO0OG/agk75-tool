"""icon.ico 생성(Pillow): 둥근 사각형 키보드 + 키 격자, 주황 강조."""
from PIL import Image, ImageDraw

ACCENT, BODY, KEY = (255, 90, 31, 255), (38, 40, 46, 255), (214, 217, 224, 255)


def draw(size):
    s = 1024  # 크게 그린 뒤 줄여서 가장자리를 부드럽게 한다
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 160, 992, 864), radius=140, fill=BODY, outline=ACCENT, width=44)
    x0, y0, gap = 120, 250, 28
    kw, kh = (784 - 5 * gap) // 6, 120  # 6열 x 3행
    for r in range(3):
        for c in range(6):
            x, y = x0 + 36 + c * (kw + gap), y0 + r * (kh + gap)
            d.rounded_rectangle((x, y, x + kw, y + kh), radius=22, fill=KEY)
    d.rounded_rectangle((x0 + 36 + 1 * (kw + gap), y0 + 3 * (kh + gap), x0 + 36 + 5 * kw + 4 * gap, y0 + 3 * (kh + gap) + kh),
                        radius=22, fill=ACCENT)  # 스페이스바
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    draw(256).save("icon.ico", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
    print("icon.ico")
