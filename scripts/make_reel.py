"""Homzie: bitta so'zsiz reel yasaydi (9:16, ~15 s, ovozsiz, musiqasiz).

Tuzilishi: 4 ta klip x 3.2 s + yakuniy karta 1.8 s
  1-klip  - katta sarlavha (hook)
  2-4 klip - har birida bitta qisqa maslahat
  oxiri   - logotip + "Follow for daily home finds"

Kadrlar Pexels'dan (PEXELS_API_KEY). Kalit bo'lmasa LOCAL_TEST=1 bilan
sun'iy kadrlar ishlatiladi - faqat dizaynni tekshirish uchun.

Natija: out/reel.mp4, out/caption.txt, out/preview.jpg, out/info.json
Navbat va ishlatilgan kliplar: state/state.json (workflow repoga qaytarib saqlaydi).
"""
import json, os, random, subprocess, sys, pathlib, shutil, textwrap, urllib.request, urllib.parse, urllib.error
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT, TMP, STATE = ROOT / "out", ROOT / "tmp", ROOT / "state" / "state.json"
FONT = str(ROOT / "assets" / "fredoka600.ttf")
LOGO = ROOT / "assets" / "logo.jpg"
TOPICS = json.loads((ROOT / "scripts" / "topics.json").read_text(encoding="utf-8"))

W, H, FPS = 1080, 1920, 30
CLIP_S, END_S = 3.2, 1.8
CREAM, INK = (250, 246, 238), (24, 38, 32)
HANDLE = "@homzie.us"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE_TAGS = ["#hometips", "#homeorganization", "#kitchenorganization", "#homehacks",
             "#organizedhome", "#cozyhome", "#cleaningmotivation"]
FALLBACK_Q = ["clean kitchen", "cozy home", "home organization", "kitchen counter", "tidy living room"]
LOCAL = os.environ.get("LOCAL_TEST") == "1"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg xatosi:\n" + " ".join(cmd) + "\n" + r.stderr[-2000:])
    return r


# ---------- Pexels ----------
def pexels_search(query):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "size": "medium", "per_page": 20})
    req = urllib.request.Request(url, headers={"Authorization": os.environ["PEXELS_API_KEY"], "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("videos", [])
    except urllib.error.HTTPError as e:
        print(f"  Pexels {e.code} ({query}): {e.read()[:200]!r}")
        return []


def best_file(video):
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")
             and f["height"] > f["width"] and f["width"] >= 720]
    files.sort(key=lambda f: abs(f["width"] - 1080))
    return files[0] if files else None


def fetch_clip(query, used, dest):
    for q in [query] + random.sample(FALLBACK_Q, len(FALLBACK_Q)):
        vids = [v for v in pexels_search(q) if v["id"] not in used and v.get("duration", 0) >= 5 and best_file(v)]
        if not vids:
            continue
        v = random.choice(vids[:8])
        f = best_file(v)
        req = urllib.request.Request(f["link"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as out:
            shutil.copyfileobj(r, out)
        print(f"  [{q}] video {v['id']} ({f['width']}x{f['height']}, {v['duration']} s) - {v.get('user', {}).get('name', '')}")
        return {"id": v["id"], "duration": v["duration"], "query": q, "url": v.get("url"),
                "author": v.get("user", {}).get("name", "")}
    sys.exit(f"Klip topilmadi: {query}")


def fake_clip(i, dest):
    hues = ["0x6b8f71", "0xc9a66b", "0x8aa1b1", "0xb5838d"]
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={hues[i % 4]}:s=1080x1920:d=6:r=30",
         "-f", "lavfi", "-i", "testsrc2=s=540x540:d=6:r=30",
         "-filter_complex", "[0][1]overlay=x='270+200*sin(t)':y=690", "-c:v", "libx264", "-preset", "ultrafast", str(dest)])
    return {"id": f"test{i}", "duration": 6, "query": "test", "url": "", "author": "test"}


# ---------- matn kartalari (PNG, shaffof) ----------
def balanced(text, width):
    """Qatorlarni teng uzunlikda bo'ladi ("On a shelf, / not the door", "...not the / door" emas)."""
    if len(text) <= width:
        return [text]
    words = text.split()
    n = len(textwrap.wrap(text, width=width))
    best = None
    for w in range(width, 7, -1):
        lines = textwrap.wrap(text, width=w)
        if len(lines) > n:
            break
        score = max(len(l) for l in lines)
        if best is None or score <= best[0]:
            best = (score, lines)
    return best[1] if best else textwrap.wrap(text, width=width)


def text_layer(lines_text, kind):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # kichik brend belgisi tepada
    small = ImageFont.truetype(FONT, 34)
    d.text((W // 2, 210), HANDLE, font=small, fill=CREAM + (210,), anchor="mm",
           stroke_width=2, stroke_fill=INK + (120,))
    size, width, cy = (84, 16, 560) if kind == "hook" else (70, 20, 1220)
    font = ImageFont.truetype(FONT, size)
    lines = balanced(lines_text, width)
    lh = int(size * 1.18)
    block_h = lh * len(lines)
    block_w = max(d.textlength(l, font=font) for l in lines)
    pad_x, pad_y = 44, 30
    x0, y0 = (W - block_w) / 2 - pad_x, cy - block_h / 2 - pad_y
    x1, y1 = (W + block_w) / 2 + pad_x, cy + block_h / 2 + pad_y
    d.rounded_rectangle([x0, y0, x1, y1], radius=36, fill=INK + (190,))
    for i, l in enumerate(lines):
        d.text((W // 2, cy - block_h / 2 + lh * i + lh / 2), l, font=font, fill=CREAM + (255,), anchor="mm")
    return img


def end_card(path):
    logo = Image.open(LOGO).convert("RGB")
    bg = logo.getpixel((8, 8))
    card = Image.new("RGB", (W, H), bg)
    card.paste(logo.resize((900, 900)), ((W - 900) // 2, 330))
    d = ImageDraw.Draw(card)
    d.text((W // 2, 1340), "Follow for daily home finds", font=ImageFont.truetype(FONT, 62), fill=CREAM, anchor="mm")
    d.text((W // 2, 1430), HANDLE, font=ImageFont.truetype(FONT, 50), fill=(232, 163, 61), anchor="mm")
    card.save(path)


# ---------- yig'ish ----------
def segment(src, dur, start, overlay_png, dest):
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{CLIP_S}", "-i", str(src),
         "-loop", "1", "-t", f"{CLIP_S}", "-i", str(overlay_png),
         "-filter_complex",
         f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1[v];"
         f"[1:v]format=rgba,fade=t=in:st=0.1:d=0.3:alpha=1[t];[v][t]overlay=0:0,format=yuv420p[o]",
         "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(dest)])


def main():
    OUT.mkdir(exist_ok=True)
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"next_topic": 0, "used_videos": []}
    want = os.environ.get("TOPIC", "").strip()
    idx = (int(want) - 1) if want.isdigit() else state["next_topic"] % len(TOPICS)
    topic = TOPICS[idx]
    print(f"Mavzu {idx + 1}/{len(TOPICS)}: {topic['hook']}")
    used = set(state.get("used_videos", []))

    texts = [(topic["hook"], "hook")] + [(t, "tip") for t in topic["tips"]]
    queries = [topic["queries"][0]] + topic["queries"]
    segs, clips = [], []
    for i, ((txt, kind), q) in enumerate(zip(texts, queries)):
        raw = TMP / f"raw{i}.mp4"
        info = fake_clip(i, raw) if LOCAL else fetch_clip(q, used, raw)
        used.add(info["id"]); clips.append(info)
        png = TMP / f"t{i}.png"
        text_layer(txt, kind).save(png)
        start = random.uniform(0.3, max(0.4, info["duration"] - CLIP_S - 0.5))
        seg = TMP / f"s{i}.mp4"
        segment(raw, info["duration"], start, png, seg)
        segs.append(seg)

    end_png = TMP / "end.png"
    end_card(end_png)
    end_mp4 = TMP / "end.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{END_S}", "-i", str(end_png), "-vf", f"fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(end_mp4)])
    segs.append(end_mp4)

    lst = TMP / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    joined = TMP / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    # Instagram ovoz yo'lini kutadi - jim (musiqasiz) audio qo'shamiz
    reel = OUT / "reel.mp4"
    run(["ffmpeg", "-y", "-i", str(joined), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(reel)])
    run(["ffmpeg", "-y", "-ss", "1.2", "-i", str(reel), "-frames:v", "1", "-q:v", "3", str(OUT / "preview.jpg")])

    tags = " ".join(dict.fromkeys(topic.get("tags", []) + BASE_TAGS))
    caption = (f"{topic['hook']}\n\n" + "\n".join(f"• {t}" for t in topic["tips"]) +
               f"\n\nFollow {HANDLE} for a little home idea every day.\n\n{tags}\n\nVideo: Pexels")
    (OUT / "caption.txt").write_text(caption, encoding="utf-8")
    (OUT / "info.json").write_text(json.dumps({"topic": idx + 1, "hook": topic["hook"], "clips": clips}, indent=1))

    state["next_topic"] = (idx + 1) % len(TOPICS)
    state["used_videos"] = list(used)[-400:]
    if not LOCAL:
        STATE.write_text(json.dumps(state, indent=1))
    print(f"Tayyor: {reel} ({reel.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
