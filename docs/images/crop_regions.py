"""Crop named regions out of a cam_combiner_gui.py screenshot for docs/GUIDE.md.

Region boxes are fractions (left, top, right, bottom) of the full window
image, calibrated against gui-overview.png (3730x1863, all panels populated,
default window size/layout). Re-run `python crop_regions.py list` after a
fresh screenshot to sanity-check a region still lines up before using it --
these will drift if the window is resized or panels are rearranged.

Usage:
    python crop_regions.py <screenshot.png> <region> [out.png]
    python crop_regions.py <screenshot.png> all              # crop every region
    python crop_regions.py list                               # show region names/boxes
"""
import sys
from PIL import Image

REGIONS = {
    "toolbar":          (0.000, 0.015, 1.000, 0.160),  # Base Dir .. Sessions rows
    "generate_row":     (0.000, 0.165, 0.360, 0.180),  # Generate Output button + status label
    "features_panel":   (0.000, 0.185, 0.145, 0.760),
    "parameters_panel": (0.148, 0.185, 0.290, 0.760),
    "model_params":     (0.291, 0.185, 0.403, 0.400),  # "Model And Fixture Parameters" summary
    "chosen_params":    (0.291, 0.400, 0.403, 0.760),  # "Chosen Parameters:" summary
    "files_panel":      (0.406, 0.185, 0.805, 0.760),
    "tools_panel":      (0.806, 0.185, 1.000, 0.760),
    "outputs_table":    (0.000, 0.762, 1.000, 0.895),
    "log_window":       (0.000, 0.922, 1.000, 1.000),
}


def crop(img_path: str, name: str, out_path: str = None):
    img = Image.open(img_path)
    l, t, r, b = REGIONS[name]
    box = (int(l * img.width), int(t * img.height), int(r * img.width), int(b * img.height))
    out = img.crop(box)
    out_path = out_path or f"{name}.png"
    out.save(out_path)
    print(f"{name}: {box} -> {out_path} ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "list":
        for name, box in REGIONS.items():
            print(f"{name:18s} {box}")
        sys.exit(0)

    src, region = sys.argv[1], sys.argv[2]
    if region == "all":
        for name in REGIONS:
            crop(src, name, f"{name}.png")
    else:
        out = sys.argv[3] if len(sys.argv) > 3 else None
        crop(src, region, out)
