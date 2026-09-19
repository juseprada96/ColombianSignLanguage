"""Split img.png (3x9 alphabet sprite sheet) into letters/<letter>.png.

- Drops the gray caption letter under each hand (painted white).
- Keeps the original white background (RGB, no alpha).
- Excludes the author-credit strip at the bottom.

Run:  python scripts/split_letters.py
"""

import os
import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "img.png")
OUT = os.path.join(REPO, "letters")

LETTERS = list("ABCDEFGHIJKLMNÑOPQRSTUVWXYZ")
ROWS, COLS = 9, 3
PAD = 14


def content_mask(arr):
    """Pixels belonging to the hand/arrow (colored or very dark), not the gray label."""
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    spread = mx - mn
    return (spread >= 30) | (mx < 110)


def gray_mask(arr):
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    spread = mx - mn
    return (spread < 30) & (mx >= 60) & (mx <= 252)


def bands(profile, thr):
    out, start = [], None
    for i, v in enumerate(profile):
        if v > thr and start is None:
            start = i
        elif v <= thr and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(profile) - 1))
    return out


def midpoints(bs):
    edges = [bs[0][0]]
    for a, b in zip(bs, bs[1:]):
        edges.append((a[1] + b[0]) // 2)
    edges.append(bs[-1][1] + 1)
    return edges


def main():
    img = Image.open(SRC).convert("RGB")
    arr = np.asarray(img).astype(np.int16)
    h, w, _ = arr.shape

    nonwhite = (arr.max(axis=2) < 245)
    row_bands = [b for b in bands(nonwhite.sum(axis=1), 2) if b[1] - b[0] > 40]
    col_bands = bands(nonwhite.sum(axis=0), 2)
    print("row bands:", row_bands)
    print("col bands:", col_bands)
    assert len(row_bands) == ROWS, f"expected {ROWS} rows, got {len(row_bands)}"
    assert len(col_bands) == COLS, f"expected {COLS} cols, got {len(col_bands)}"

    r_edges = midpoints(row_bands)
    c_edges = midpoints(col_bands)
    cmask = content_mask(arr)
    gmask = gray_mask(arr)

    os.makedirs(OUT, exist_ok=True)
    tiles = []
    for r in range(ROWS):
        for c in range(COLS):
            letter = LETTERS[r * COLS + c]
            y0, y1 = r_edges[r], r_edges[r + 1]
            x0, x1 = c_edges[c], c_edges[c + 1]
            sub = cmask[y0:y1, x0:x1]
            ys, xs = np.where(sub)
            if len(ys) == 0:
                raise RuntimeError(f"no content for {letter}")
            by0, by1 = ys.min(), ys.max()
            bx0, bx1 = xs.min(), xs.max()
            ty0 = max(0, y0 + by0 - PAD)
            ty1 = min(h, y0 + by1 + 1 + PAD)
            tx0 = max(0, x0 + bx0 - PAD)
            tx1 = min(w, x0 + bx1 + 1 + PAD)

            tile = arr[ty0:ty1, tx0:tx1].astype(np.uint8).copy()
            # erase any gray caption pixel that falls inside the tight box
            g = gmask[ty0:ty1, tx0:tx1]
            tile[g] = 255
            out = Image.fromarray(tile)
            name = "ENYE" if letter == "Ñ" else letter
            out.save(os.path.join(OUT, f"{name}.png"))
            tiles.append((letter, out))
            print(f"{letter:>2} -> letters/{name}.png  {out.size}")

    # verification montage (temp only)
    tmp = r"C:\Users\jusep\AppData\Local\Temp\opencode\csl\letters_montage.png"
    cell = 220
    sheet = Image.new("RGB", (cell * COLS, cell * ROWS), (235, 235, 235))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    for i, (letter, im) in enumerate(tiles):
        r, c = divmod(i, COLS)
        im2 = im.copy()
        im2.thumbnail((cell - 30, cell - 30))
        sheet.paste(im2, (c * cell + 15, r * cell + 15))
        draw.text((c * cell + 5, r * cell + 5), letter, fill=(200, 0, 0))
    sheet.save(tmp)
    print("montage:", tmp)
    print("done:", len(tiles), "letters")


if __name__ == "__main__":
    main()
