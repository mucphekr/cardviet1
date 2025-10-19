#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate random Vietnamese student names and write them onto the template image
right after the "Họ và tên:" label (beneath "Vừa làm vừa học").
- Works offline (built-in name lists) to avoid duplicates.
- You can control how many images to create with NUM_IMAGES.
- Coordinates are ratio-based so it scales with different image sizes.
- If the text is a bit off, tweak the four R_* ratios below.
- NEW: Support Gemini API for automatic name generation
"""
import random
import argparse
import json
from typing import Iterable
import re
import os
try:
    import requests  # optional, used for API fetch
except Exception:
    requests = None  # fallback to urllib if needed
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

# ============ USER SETTINGS ============
TEMPLATE_PATH = r"C:\Users\Muc Phe\Desktop\Card Viet\template.png"
   # put your base image path here
OUTPUT_DIR = str((Path(__file__).parent / "out_names").resolve())
NAMES_LOG = str((Path(__file__).parent / "out_names" / "names_log.txt").resolve())
API_SOURCES_FILE = str((Path(__file__).parent / "api_sources.txt").resolve())
# Default to names file inside the project folder
DEFAULT_NAMES_FILE = str((Path(__file__).parent / "students_1000.txt").resolve())
NUM_IMAGES = 1                 # default number of images when no --num is given
SEED = 42                        # set None for fully random

# Position to place the student's name (AFTER "Họ và tên:")
# These are ratios of the image size; they should work well with the sample provided.
# If needed, nudge them a little.
R_X = 0.56      # left X ratio of the name area
R_Y = 0.455      # top Y ratio of the name area (line with "Họ và tên:")
R_W = 0.52       # width ratio of the name area
R_H = 0.055      # height ratio of the name area

# Font config (choose a font that supports Vietnamese accents).
# On most systems, DejaVuSans or Arial Unicode MS works. Change to a local .ttf if needed.
FONT_CANDIDATES = [
    "DejaVuSans.ttf",            # Linux / Colab
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "Arial Unicode.ttf",         # Windows (if installed)
    "Arial.ttf",                 # Windows
    r"C:\\Windows\\Fonts\\arial.ttf",
    r"C:\\Windows\\Fonts\\arialuni.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # macOS
]

# Preferred initial font size (the script auto-shrinks to fit the box if needed)
BASE_FONT_SIZE = 54

# ============ NAME DATA ============
# Common Vietnamese family names
FAMILY_NAMES = [
    "Nguyễn","Trần","Lê","Phạm","Hoàng","Huỳnh","Phan","Vũ","Võ","Đặng",
    "Bùi","Đỗ","Hồ","Ngô","Dương","Lý","Đinh","Trương","Đoàn","Mai",
    "Văn","Tạ","Trịnh","Cao","Quách","Hà","Châu","Tô","La","Giang","Đào"
]

# Frequent middle names (unisex + gendered forms used commonly on IDs)
MIDDLE_NAMES = [
    "Thị","Văn","Hữu","Ngọc","Minh","Quang","Gia","Anh","Thuỳ","Phương",
    "Thanh","Tuấn","Hải","Đình","Tiến","Bảo","Xuân","Kim","Diệu","Trung",
    "Hoài","Thế","Khánh","Thùy","Thảo","Mạnh","Phúc","Thắng","Phú","Đức"
]

# Common given names (mix male/female)
GIVEN_NAMES = [
    "An","Anh","Bách","Bảo","Bích","Bình","Châu","Chi","Dũng","Duy","Duyên",
    "Giang","Hiếu","Hiền","Hoa","Hoà","Hoài","Hùng","Huy","Huyền","Hương",
    "Khánh","Khang","Khoa","Kiên","Lan","Linh","Loan","Long","Luân","Mai",
    "Minh","My","Nam","Ngân","Ngọc","Nghĩa","Nhi","Nhung","Phát","Phú",
    "Phúc","Phong","Phương","Quang","Quân","Quỳnh","Sang","Sơn","Tài","Tâm",
    "Tân","Thái","Thắng","Thảo","Thành","Thanh","Thiện",
    "Thịnh","Thọ","Thúy","Tiên","Tiến","Toàn","Trang","Trí","Trinh","Trọng",
    "Trung","Tú","Tùng","Tuyết","Uyên","Vi","Vinh","Vy","Yến"
]

def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    # Fallback to PIL default (limited Vietnamese support)
    return ImageFont.load_default()

def load_previous_names(log_path: str) -> set[str]:
    path = Path(log_path)
    if not path.exists():
        return set()
    try:
        return set(x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip())
    except Exception:
        return set()

def append_names_to_log(log_path: str, names: Iterable[str]) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for name in names:
            f.write(f"{name}\n")

def make_unique_names(n: int) -> list[str]:
    """Create up to n unique full names."""
    seen = set()
    names = []
    attempts = 0
    while len(names) < n and attempts < n * 20:
        full = f"{random.choice(FAMILY_NAMES)} {random.choice(MIDDLE_NAMES)} {random.choice(GIVEN_NAMES)}"
        if full not in seen:
            seen.add(full)
            names.append(full)
        attempts += 1
    return names

def try_extract_full_names_from_json(payload) -> list[str]:
    # Accept formats: ["Nguyễn Văn A", ...] or [{"name": ...}] or {"data": [...]}
    candidates = []
    data = payload
    if isinstance(payload, dict):
        # common keys
        for key in ("data", "results", "items", "names"):
            if key in payload:
                data = payload[key]
                break
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                for key in ("full_name", "name", "fullname"):
                    if key in item and isinstance(item[key], str):
                        candidates.append(item[key])
                        break
    elif isinstance(data, dict):
        for key in ("full_name", "name", "fullname"):
            if key in data and isinstance(data[key], str):
                candidates.append(data[key])
                break
    return candidates

def fetch_names_from_api(api_url: str, count: int) -> list[str]:
    if not api_url:
        return []
    try:
        if requests is not None:
            resp = requests.get(api_url, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        else:
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as r:
                content = r.read().decode("utf-8", errors="ignore")
            try:
                payload = json.loads(content)
            except Exception:
                payload = content
        # Try JSON extraction first
        names = try_extract_full_names_from_json(payload)
        # If string content, try HTML/text extraction heuristics
        if not names and isinstance(payload, str):
            text = payload
            # Remove HTML tags quickly
            text_no_tags = re.sub(r"<[^>]+>", " ", text)
            # Vietnamese-looking full names: 2-4 capitalized tokens possibly with accents
            # Basic pattern: Capitalized word (with Vietnamese letters) separated by spaces
            word = r"[A-ZÀÁÂÃÄÅĂẠẢẤẦẨẪẬẮẰẲẴẶÈÉÊËẸẺẼẾỀỂỄỆÌÍÎÏỊỈĨÒÓÔÕÖƠỌỎỐỒỔỖỘỚỜỞỠỢÙÚÛÜƯỤỦỨỪỬỮỰỲÝỶỸỴĐ][a-zàáâãäåăạảấầẩẫậắằẳẵặèéêëẹẻẽếềểễệìíîïịỉĩòóôõöơọỏốồổỗộớờởỡợùúûüưụủứừửữựỳýỷỹỵđ]+"
            pattern = rf"\b{word}(\s+{word}){{1,3}}\b"
            candidates = re.findall(pattern, text_no_tags)
            # re.findall with groups returns only the last group unless we use finditer
            names_found = []
            for m in re.finditer(pattern, text_no_tags):
                names_found.append(m.group(0).strip())
            # Fallback: newline-based
            if not names_found:
                names_found = [x.strip() for x in text_no_tags.splitlines() if x.strip()]
            names = names_found
        # Trim and dedupe order-preserving
        seen = set()
        result = []
        for nm in names:
            nm = nm.strip()
            if nm and nm not in seen:
                seen.add(nm)
                result.append(nm)
        return result[:count]
    except (HTTPError, URLError, Exception):
        return []

def generate_names_api_only(num_needed: int, api_url: str, avoid: set[str]) -> list[str]:
    collected: list[str] = []
    api_names = fetch_names_from_api(api_url, num_needed * 5)
    for nm in api_names:
        if len(collected) >= num_needed:
            break
        if nm not in avoid and nm not in collected:
            collected.append(nm)
    return collected

def load_candidate_api_urls(sources_file: str) -> list[str]:
    urls: list[str] = []
    # Read from local file if present
    p = Path(sources_file)
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
        except Exception:
            pass
    # Hard-coded candidates can be extended here if you have known endpoints
    # Keep this list minimal to avoid hitting unknown services unintentionally
    return urls

def try_auto_api(num_needed: int, avoid: set[str], sources_file: str) -> list[str]:
    urls = load_candidate_api_urls(sources_file)
    if not urls:
        return []
    param_variants = [
        "count", "limit", "size", "n"
    ]
    collected: list[str] = []
    for base in urls:
        candidates = [base]
        # try with common count params
        for key in param_variants:
            sep = "&" if "?" in base else "?"
            candidates.append(f"{base}{sep}{key}={num_needed*5}")
        for url in candidates:
            names = fetch_names_from_api(url, num_needed * 5)
            for nm in names:
                if len(collected) >= num_needed:
                    break
                if nm not in avoid and nm not in collected:
                    collected.append(nm)
            if len(collected) >= num_needed:
                return collected
    return collected

def fetch_names_namefake(num_needed: int, timeout_s: float = 5.0, max_attempts: int = 10) -> list[str]:
    """Fetch ~num_needed Vietnamese names from namefake API, de-duplicated."""
    url = "https://api.namefake.com/vietnamese-vietnam/random"
    got: set[str] = set()
    attempts = 0
    def fetch_once() -> str:
        if requests is not None:
            r = requests.get(url, timeout=timeout_s)
            if r.ok:
                try:
                    data = r.json()
                except Exception:
                    return ""
                return str(data.get("name", "")).strip()
            return ""
        # urllib fallback
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=timeout_s) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(content)
            return str(data.get("name", "")).strip()
        except Exception:
            return ""

    while len(got) < num_needed and attempts < max_attempts * max(1, num_needed):
        name = fetch_once()
        if name:
            got.add(name)
        else:
            try:
                import time as _t
                _t.sleep(0.3)
            except Exception:
                pass
        attempts += 1
    return list(got)

def make_unique_names_offline(n: int, avoid: set[str]) -> list[str]:
    seen = set()
    names: list[str] = []
    attempts = 0
    while len(names) < n and attempts < n * 30:
        full = f"{random.choice(FAMILY_NAMES)} {random.choice(MIDDLE_NAMES)} {random.choice(GIVEN_NAMES)}"
        if full not in seen and full not in avoid and full not in names:
            seen.add(full)
            names.append(full)
        attempts += 1
    return names

def generate_names_with_gemini(num_needed: int, avoid: set[str], api_key: str) -> list[str]:
    """Generate Vietnamese student names using Gemini API."""
    if not GEMINI_AVAILABLE:
        print("⚠️ google-generativeai not installed. Install with: pip install google-generativeai")
        return []
    
    if not api_key:
        print("⚠️ No Gemini API key provided. Use --gemini-key YOUR_KEY or set GEMINI_API_KEY env variable.")
        return []
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        collected_names = []
        attempts = 0
        max_attempts = num_needed * 3
        
        while len(collected_names) < num_needed and attempts < max_attempts:
            # Request more names than needed to account for duplicates
            batch_size = min(20, num_needed - len(collected_names) + 5)
            
            prompt = f"""Tạo {batch_size} tên sinh viên Việt Nam ngẫu nhiên, đa dạng.
Yêu cầu:
- Mỗi tên gồm họ, tên đệm và tên chính (ví dụ: Nguyễn Văn An)
- Sử dụng các họ phổ biến như: Nguyễn, Trần, Lê, Phạm, Hoàng, Huỳnh, Phan, Vũ, Võ, Đặng, Bùi, Đỗ, Hồ, Ngô, Dương
- Đảm bảo có dấu thanh đúng (á, à, ả, ã, ạ, â, ấ, ầ, ẩ, ẫ, ậ, ă, ắ, ằ, ẳ, ẵ, ặ, v.v.)
- Mỗi tên trên một dòng
- Không đánh số, không giải thích, chỉ liệt kê tên

Ví dụ format:
Nguyễn Thị Lan
Trần Văn Hùng
Lê Minh Anh"""

            response = model.generate_content(prompt)
            
            if response and response.text:
                # Parse names from response
                lines = response.text.strip().split('\n')
                for line in lines:
                    # Clean up the line
                    name = line.strip()
                    # Remove numbering if present (1. Name, 1) Name, etc.)
                    name = re.sub(r'^\d+[\.\)]\s*', '', name)
                    # Remove bullet points
                    name = re.sub(r'^[-*•]\s*', '', name)
                    name = name.strip()
                    
                    # Validate name format (should have 2-4 words)
                    if name and 2 <= len(name.split()) <= 4:
                        if name not in avoid and name not in collected_names:
                            collected_names.append(name)
                            if len(collected_names) >= num_needed:
                                break
            
            attempts += 1
        
        print(f"✅ Gemini API generated {len(collected_names)}/{num_needed} unique names")
        return collected_names[:num_needed]
        
    except Exception as e:
        print(f"❌ Error with Gemini API: {e}")
        return []

def load_names_from_file(path: str) -> list[str]:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except Exception:
        return []
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    # normalize whitespace
    names = [re.sub(r"\s+", " ", ln) for ln in lines]
    # preserve order while deduping
    seen = set()
    out: list[str] = []
    for nm in names:
        if nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out

def sanitize_filename(name: str) -> str:
    # Replace characters not safe for Windows filenames
    safe = "".join(c for c in name if c not in "\\/:*?\"<>|\n\r\t")
    safe = safe.strip()
    # Fallback if empty after sanitization
    return safe or "student"

def autowrap_and_fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, box_w: int, box_h: int):
    """Shrink font until text height fits; no multi-line needed for short names."""
    size = font.size
    while size > 12:
        f = pick_font(size)
        bbox = draw.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        if tw <= box_w and th <= box_h:
            return f
        size -= 2
    return pick_font(12)

def place_name_on_image(template_path: str, out_path: str, name_text: str):
    im = Image.open(template_path).convert("RGBA")
    W, H = im.size

    # Compute placement rectangle
    box_x = int(W * R_X)
    box_y = int(H * R_Y)
    box_w = int(W * R_W)
    box_h = int(H * R_H)

    # Draw
    draw = ImageDraw.Draw(im)

    # Prepare font that fits
    font = autowrap_and_fit(draw, name_text, pick_font(BASE_FONT_SIZE), box_w, box_h)

    # Left align, vertically centered within the box
    text_bbox = draw.textbbox((0,0), name_text, font=font)
    text_h = text_bbox[3] - text_bbox[1]
    y = box_y + (box_h - text_h)//2
    x = box_x + 10  # small left padding so it's neatly after "Họ và tên:" label

    # Optional: white 'stroke' to improve contrast on the patterned background
    draw.text((x, y), name_text, font=font, fill=(0,0,0), stroke_width=2, stroke_fill=(255,255,255))

    im.save(out_path)

def main():
    parser = argparse.ArgumentParser(description="Generate Vietnamese student ID photos with names")
    parser.add_argument("--num", type=int, default=None, help="Number of images to generate")
    parser.add_argument("--api-url", type=str, default="", help="API endpoint that returns Vietnamese names (required unless --auto-api or --namefake)")
    parser.add_argument("--auto-api", action="store_true", help="Automatically try candidate API endpoints from api_sources.txt")
    parser.add_argument("--namefake", action="store_true", help="Use namefake.com Vietnamese API as the online source")
    parser.add_argument("--gemini", action="store_true", help="Use Gemini API to generate names automatically")
    parser.add_argument("--gemini-key", type=str, default="", help="Gemini API key (or set GEMINI_API_KEY env variable)")
    parser.add_argument("--pad-local", action="store_true", help="If online source returns insufficient names, pad with offline names to reach --num")
    parser.add_argument("--template", type=str, default=TEMPLATE_PATH, help="Path to template image")
    parser.add_argument("--out", type=str, default=OUTPUT_DIR, help="Output directory for generated images")
    parser.add_argument("--seed", type=int, default=SEED if SEED is not None else None, help="Random seed")
    parser.add_argument("--names-file", type=str, default="", help="Path to a local file with one full name per line (preferred over API)")
    args = parser.parse_args()

    num_images = args.num if args.num is not None else NUM_IMAGES
    template_path = args.template
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.seed is not None:
        random.seed(args.seed)

    previous = load_previous_names(NAMES_LOG)
    names: list[str]
    
    # Priority 1: Use Gemini API if specified
    if args.gemini:
        gemini_key = args.gemini_key or os.environ.get('GEMINI_API_KEY', '')
        print(f"🤖 Using Gemini API to generate {num_images} Vietnamese student names...")
        names = generate_names_with_gemini(num_images, previous, gemini_key)
        if len(names) < num_images:
            if args.pad_local:
                need = num_images - len(names)
                print(f"📝 Padding with {need} offline-generated names...")
                names += make_unique_names_offline(need, set(previous).union(names))
            else:
                raise SystemExit(f"Gemini API did not return enough unique names ({len(names)}/{num_images}). Use --pad-local to fill remaining.")
    # Priority 2: Use names file if exists
    elif args.names_file or Path(DEFAULT_NAMES_FILE).exists():
        chosen_path = args.names_file or DEFAULT_NAMES_FILE
        file_names = load_names_from_file(chosen_path)
        # filter against previous
        filtered = [nm for nm in file_names if nm not in previous]
        # randomize to diversify picks
        random.shuffle(filtered)
        names = filtered[:num_images]
        if len(names) < num_images:
            # pad from remaining in file (including previously used if necessary?)
            # keep strict: do not reuse previous across runs
            pass
        if len(names) < num_images:
            if args.pad_local:
                need = num_images - len(names)
                names += make_unique_names_offline(need, set(previous).union(names))
            else:
                raise SystemExit(f"Names file did not provide enough unique names ({len(names)}/{num_images}).")
    elif args.api_url:
        names = generate_names_api_only(num_images, args.api_url, previous)
        if len(names) < num_images:
            if args.pad_local:
                need = num_images - len(names)
                names += make_unique_names_offline(need, set(previous).union(names))
            else:
                raise SystemExit(f"API did not return enough unique names ({len(names)}/{num_images}).")
    elif args.auto_api:
        names = try_auto_api(num_images, previous, API_SOURCES_FILE)
        if len(names) < num_images:
            if args.pad_local:
                need = num_images - len(names)
                names += make_unique_names_offline(need, set(previous).union(names))
            else:
                raise SystemExit(f"Auto-API did not return enough unique names ({len(names)}/{num_images}).")
    elif args.namefake:
        names = [nm for nm in fetch_names_namefake(num_images * 2) if nm not in previous]
        names = names[:num_images]
        if len(names) < num_images:
            if args.pad_local:
                need = num_images - len(names)
                names += make_unique_names_offline(need, set(previous).union(names))
            else:
                raise SystemExit(f"Namefake did not return enough unique names ({len(names)}/{num_images}).")
    # Default: Use offline generation
    else:
        print(f"📝 Using offline name generation (no API or file specified)...")
        names = make_unique_names_offline(num_images, previous)

    used_filenames = set()
    for i, full_name in enumerate(names, start=1):
        base = sanitize_filename(full_name)
        candidate = base
        suffix = 1
        while candidate.lower() in used_filenames or (out_dir / f"{candidate}.png").exists():
            suffix += 1
            candidate = f"{base}_{suffix}"
        used_filenames.add(candidate.lower())
        out_file = out_dir / f"{candidate}.png"
        place_name_on_image(template_path, str(out_file), full_name)
        print(f"[OK] {out_file} -> {full_name}")

    append_names_to_log(NAMES_LOG, names)

if __name__ == "__main__":
    main()
