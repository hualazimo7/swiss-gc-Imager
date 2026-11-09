#!/usr/bin/env python3
"""Build a custom Swiss backdrop (swiss/backdrop.tpl) from ordinary images.

Swiss already looks for `<boot device>:/swiss/backdrop.tpl` at startup
(see DrawLoadBackdrop() in gui/FrameBufferMagic.c) and, when it finds a valid
TPL there, uses it instead of the built-in backdrop for the whole main UI.

Multiple images in one TPL are picked by the calendar: the loader counts the
textures and picks an index from the month / weekday / hour / day-of-year, so
2/3/4/6/7/12/24/30/31/365/366 images give you seasonal, monthly, daily or
hourly rotation. Any other count falls back to a random pick per boot.

CI4/CI8 need palfmt=2 (RGB5A3 TLUT). With gxtexconv's default palfmt=0 (IA8)
Swiss' TEX_BACKDROP branch selects the TEV setup meant for the built-in CI4
backdrop and renders the image in wrong colours (verified on real hardware:
two different source images both showed the same stale bright yellow).

    python tools/make_backdrop.py art/summer.png
    python tools/make_backdrop.py spring.png summer.png autumn.png winter.png
    python tools/make_backdrop.py photo.jpg --format ci8 --fit cover
    python tools/make_backdrop.py logo.png --height 240

Output defaults to tmp/backdrop.tpl; copy it to <sd>/swiss/backdrop.tpl.
"""
import argparse
import os
import subprocess
import sys
import tempfile

from PIL import Image

GXTEXCONV = r"C:/msys64/opt/devkitpro/tools/bin/gxtexconv.exe"

FORMATS = {
    # name: (gxtexconv colfmt, bytes per pixel at 640x480)
    "rgb5a3": (5, 2),
    "rgb565": (4, 2),
    "ci8": (9, 1 + 256 * 2 / (640 * 480)),
    "ci4": (8, 0.5 + 16 * 2 / (640 * 480)),
    "ia8": (3, 2),
    "i8": (1, 1),
    "cmpr": (14, 0.5),
}

# Temporaries must live on an ASCII-only path: gxtexconv crashes on non-ASCII.
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "backdrop")


def fit_image(im, w, h, mode):
    im = im.convert("RGB")
    if mode == "stretch":
        return im.resize((w, h), Image.LANCZOS)
    src_ratio = im.width / im.height
    dst_ratio = w / h
    if mode == "contain":
        scale = min(w / im.width, h / im.height)
        im = im.resize((max(1, round(im.width * scale)),
                        max(1, round(im.height * scale))), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
        return canvas
    # cover (default): fill the frame, crop the overflow
    if src_ratio > dst_ratio:
        new_w = round(h * src_ratio)
        im = im.resize((new_w, h), Image.LANCZOS)
        left = (new_w - w) // 2
        return im.crop((left, 0, left + w, h))
    new_h = round(w / src_ratio)
    im = im.resize((w, new_h), Image.LANCZOS)
    top = (new_h - h) // 2
    return im.crop((0, top, w, top + h))


def build(images, out, width, height, fmt, fit, label):
    os.makedirs(WORK, exist_ok=True)
    colfmt, bpp = FORMATS[fmt]

    prepared = []
    for i, path in enumerate(images):
        im = Image.open(path)
        im = fit_image(im, width, height, fit)
        if fmt in ("ci4", "ci8"):
            # gxtexconv only accepts palettised input for the CI formats
            im = im.convert("P", palette=Image.ADAPTIVE,
                            colors=16 if fmt == "ci4" else 256)
        dst = os.path.join(WORK, "t%02d.png" % i)
        im.save(dst)
        prepared.append(dst)
        print("  [%d] %s -> %dx%d" % (i, os.path.basename(path), width, height))

    if len(prepared) == 1:
        extra = " palfmt=2" if fmt in ("ci4", "ci8") else ""
        cmd = [GXTEXCONV, "-i", prepared[0], "-o", out,
               "colfmt=%d%s" % (colfmt, extra)]
        if label:
            pass
    else:
        scf = os.path.join(WORK, "backdrop.scf")
        with open(scf, "w", encoding="ascii") as fh:
            for i, p in enumerate(prepared):
                pal = " palfmt=2" if fmt in ("ci4", "ci8") else ""
                fh.write('<filepath="%s" id="bg%02d" colfmt=%d%s />\n'
                         % (p, i, colfmt, pal))
        cmd = [GXTEXCONV, "-s", scf, "-o", out]

    print("  " + " ".join(os.path.basename(c) if os.path.isabs(c) else c for c in cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(out):
        print("--- gxtexconv stdout ---")
        print(res.stdout)
        print("--- gxtexconv stderr ---")
        print(res.stderr)
        raise SystemExit("gxtexconv failed (rc=%d)" % res.returncode)

    size = os.path.getsize(out)
    print("  %s: %d bytes (%.0f KB)" % (out, size, size / 1024.0))
    print("  %d texture(s) of %dx%d %s" % (len(images), width, height, fmt))
    return size


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", help="PNG/JPG/TIF, one per rotation slot")
    ap.add_argument("--out", default=os.path.join(WORK, "backdrop.tpl"))
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--format", default="rgb5a3", choices=sorted(FORMATS))
    ap.add_argument("--fit", default="cover", choices=("cover", "contain", "stretch"))
    ap.add_argument("--label", default=None, help="ignored, kept for scripting")
    a = ap.parse_args(argv[1:])

    if not os.path.exists(GXTEXCONV):
        raise SystemExit("gxtexconv not found at %s" % GXTEXCONV)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    print("building backdrop from %d image(s)" % len(a.images))
    build(a.images, os.path.abspath(a.out), a.width, a.height, a.format, a.fit, a.label)
    print("\ncopy it to <sd>/swiss/backdrop.tpl, then reboot Swiss")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
