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
import base64, json, os, random, re, subprocess, time, sys, pathlib, shutil, textwrap, urllib.request, urllib.parse, urllib.error
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT, TMP, STATE = ROOT / "out", ROOT / "tmp", ROOT / "state" / "state.json"
FONT = str(ROOT / "assets" / "fredoka600.ttf")
LOGO = ROOT / "assets" / "logo.jpg"
TOPICS = json.loads((ROOT / "scripts" / "topics.json").read_text(encoding="utf-8"))

W, H, FPS = 1080, 1920, 30
CLIP_S, END_S = 4.0, 1.8
CREAM, INK = (250, 246, 238), (24, 38, 32)
HANDLE = "@homzie.us"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE_TAGS = ["#homehacks", "#homeorganization", "#cleaningmotivation", "#hometips", "#kitchenorganization"]
FALLBACK_Q = ["clean kitchen", "cozy home", "home organization", "kitchen counter", "tidy living room"]
# Odob va halol qoidasi: Pexels sahifa nomi bo'yicha chetlanadigan kliplar.
# Qo'llar ("hands") qoladi - uy ishlarini ko'rsatish uchun yetarli.
PEOPLE = re.compile(r"\b(woman|women|girl|girls|lady|ladies|female|model|man|men|boy|boys|guy|guys|couple|"
                    r"people|family|bikini|dress|skirt|legs|body|kid|kids|child|children|baby|teen|"
                    r"mother|father|wife|husband|bride|dancing|dance|swimsuit|lingerie|selfie|"
                    # halol qoidalari: diniy bayramlar, sehr/qo'rqinchli, spirtli ichimlik, cho'chqa go'shti
                    r"easter|christmas|xmas|santa|church|halloween|hanukkah|diwali|valentine|pumpkin carving|"
                    r"witch|ghost|spooky|wine|beer|alcohol|cocktail|champagne|whiskey|vodka|bar|pub|"
                    r"pork|bacon|ham|sausage|pig|piggy)\b")
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


# ---------- Gemini: kadr matnga mosmi va odobga to'g'rimi ----------
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_model = None


def gemini_model():
    """Bepul ishlaydigan eng yangi 'flash' modelni o'zi topadi (nomlar tez-tez yangilanadi)."""
    global _model
    if _model is not None:
        return _model
    _model = ""
    try:
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                     headers={"x-goog-api-key": GEMINI_KEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            models = json.load(r).get("models", [])
        names = [m["name"].split("/", 1)[1] for m in models
                 if "generateContent" in m.get("supportedGenerationMethods", [])
                 and re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-latest)?", m["name"].split("/", 1)[1])]
        ver = lambda n: float(re.search(r"gemini-(\d+(?:\.\d+)?)", n).group(1))
        names.sort(key=lambda n: (ver(n), not n.endswith("latest")), reverse=True)
        _model = names[0] if names else ""
    except Exception as e:  # noqa: BLE001
        print(f"  Gemini modellar ro'yxati olinmadi: {e}")
    print(f"  Gemini modeli: {_model or '-'}")
    return _model


def gemini_pick(caption, vids):
    """Nomzod kadrlar ichidan matnga eng mosini tanlaydi. Odobsiz/nomaqbul kadrlarni rad etadi.
    Qaytaradi: (video yoki None, ball). Gemini ishlamasa (None, -1)."""
    model = gemini_model() if GEMINI_KEY else ""
    if not model:
        return None, -1
    parts = [{"text": (
        "You pick a stock video clip for a short, wordless Instagram reel with home and kitchen tips. "
        f'The on-screen caption for this clip is: "{caption}".\n'
        f"Below are {len(vids)} candidate frames, numbered 1 to {len(vids)} in order.\n"
        "Reject a frame if it shows: a person in revealing clothing (shorts, short skirt, bare shoulders, swimwear), "
        "alcohol, pork, religious symbols or holiday decorations, anything spooky, or a messy or unappetizing scene. "
        "Hands doing a task are fine. Among the acceptable frames pick the one that best shows the caption "
        "literally, so a viewer understands the tip from the picture. "
        'Answer with JSON only: {"best": <number, 0 if none is acceptable>, "score": <0-10 how well it shows the caption>}')}]
    for v in vids:
        req = urllib.request.Request(v["image"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            img = r.read()
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
            text = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"] if not p.get("thought"))
            ans = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            best, score = int(ans.get("best", 0)), float(ans.get("score", 0))
            time.sleep(4)   # bepul limit: daqiqasiga bir necha so'rov
            return (vids[best - 1] if 1 <= best <= len(vids) else None), score
        except urllib.error.HTTPError as e:
            print(f"  Gemini {e.code}: {e.read()[:200]!r}")
            if e.code in (429, 500, 503):
                time.sleep(20 * (attempt + 1)); continue
            break
        except Exception as e:  # noqa: BLE001
            print(f"  Gemini javobi tushunilmadi: {e}")
            break
    return None, -1


def fetch_clip(query, used, dest, caption=""):
    first = None   # Gemini hammasini rad etsa - birinchi so'zdagi filtrdan o'tgan klip olinadi
    for q in [query] + random.sample(FALLBACK_Q, 2) + [None]:
        if q is None:
            if not first:
                break
            q, vids, caption = query, first, ""
        else:
            vids = [v for v in pexels_search(q) if v["id"] not in used and v.get("duration", 0) >= 5 and best_file(v)
                    and not PEOPLE.search((v.get("url") or "").lower().replace("-", " "))]
            first = first or vids
        if not vids:
            continue
        v, score = gemini_pick(caption, vids[:6]) if caption else (None, -1)
        if score == -1:            # Gemini yo'q yoki ishlamadi - avvalgidek tasodifiy
            v = random.choice(vids[:8])
        elif v is None or score < 5:
            print(f"  [{q}] mos kadr topilmadi (ball {score}), keyingi so'zga o'tiladi")
            continue
        else:
            print(f"  Gemini tanladi: ball {score}")
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
    size, width, cy = (84, 20, 560) if kind == "hook" else (70, 20, 1220)
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


# ---------- ovoz (musiqasiz, CC0 uy ovozlari) ----------
SOUNDS = json.loads((ROOT / "scripts" / "sounds.json").read_text(encoding="utf-8"))
SFX_MAP = [  # qidiruv so'zidagi kalit -> ovoz turi (tartib muhim)
    (("fridge", "refrigerator", "freezer", "eggs", "grocery"), "fridge"),
    (("jar", "pantry", "spice", "label"), "jar"),
    (("coffee table", "lamp", "window", "plants", "reading", "living room"), "click"),
    (("coffee",), "coffee"),
    (("dog", "pet", "paws"), "dog"),
    (("wiping", "clean", "mirror", "baking soda"), "clean"),
    (("sink", "washing", "dishwasher", "water", "herbs water"), "water"),
    (("chopping", "cooking", "meal prep", "pot", "vegetables", "herbs", "fruit", "bananas", "berries", "apples"), "cook"),
    (("bed", "duvet", "pillow", "blanket", "sofa", "laundry", "folding", "towel", "clothes"), "fabric"),
    (("keys", "entryway", "shoes", "door"), "keys"),
    (("drawer", "utensils", "organizer", "shelves", "counter", "kitchen", "appliances"), "drawer"),
]
SFX_CACHE = ROOT / ".sfx"


def sfx_kind(query):
    q = query.lower()
    for keys, kind in SFX_MAP:
        if any(k in q for k in keys):
            return kind
    return "drawer"


def sfx_file(kind, rng):
    sid, dur, path = rng.choice(SOUNDS[kind])
    SFX_CACHE.mkdir(exist_ok=True)
    dest = SFX_CACHE / f"{sid}.mp3"
    if not dest.exists():
        req = urllib.request.Request("https://cdn.freesound.org/previews/" + path, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
            shutil.copyfileobj(r, out)
    return dest, float(dur), sid


def build_audio(queries, total):
    """Xona foni (past) + har kadr boshida mos uy ovozi + yakunda pop. -16 LUFS."""
    out = TMP / "audio.m4a"
    if LOCAL and not os.environ.get("LOCAL_SFX"):
        run(["ffmpeg", "-y", "-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=44100:cl=stereo", "-c:a", "aac", str(out)])
        return out, []
    rng = random.Random()
    inputs, filters, labels, used = [], [], [], []
    amb, amb_d, amb_id = sfx_file("ambience", rng)
    off = rng.uniform(0, max(0.0, amb_d - total - 1))
    inputs += ["-ss", f"{off:.2f}", "-t", f"{total:.2f}", "-i", str(amb)]
    filters.append(f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,loudnorm=I=-34:TP=-9,aresample=44100,"
                   f"afade=t=in:d=0.6,afade=t=out:st={total - 0.8:.2f}:d=0.8[a0]")
    labels.append("[a0]"); used.append(["ambience", amb_id])
    for i, q in enumerate(queries):
        kind = sfx_kind(q)
        f, d, sid = sfx_file(kind, rng)
        n = len(labels)
        inputs += ["-i", str(f)]
        length = min(d, CLIP_S - 0.3)
        delay = int((i * CLIP_S + 0.25) * 1000)
        filters.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,atrim=0:{length:.2f},"
                       f"loudnorm=I=-17:TP=-3,aresample=44100,afade=t=out:st={max(0.0, length - 0.4):.2f}:d=0.4,adelay={delay}|{delay}[a{n}]")
        labels.append(f"[a{n}]"); used.append([kind, sid])
    f, d, sid = sfx_file("pop", rng)
    n = len(labels)
    inputs += ["-i", str(f)]
    delay = int((len(queries) * CLIP_S + 0.15) * 1000)
    filters.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,loudnorm=I=-20:TP=-4,aresample=44100,"
                   f"adelay={delay}|{delay}[a{n}]")
    labels.append(f"[a{n}]"); used.append(["pop", sid])
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,"
                   f"alimiter=limit=0.85:level=false,atrim=0:{total:.2f}[mix]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[mix]",
         "-ar", "44100", "-c:a", "aac", "-b:a", "128k", str(out)])
    return out, used


# ---------- yig'ish ----------
# Instagram talabi: H.264, yopiq GOP, 4:2:0, video bitreyti 5 Mbit/s dan oshmasin
VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "4500k", "-bufsize", "9000k",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def segment(src, dur, start, overlay_png, dest, animate=True):
    # 1-kadrda sarlavha darhol ko'rinadi (odam birinchi soniyada to'xtashi uchun), qolganlari chiqib keladi
    txt = ("[1:v]format=rgba,fade=t=in:st=0.1:d=0.35:alpha=1[t];[v][t]overlay=x=0:y='if(lt(t,0.5),45*(1-t/0.5),0)'"
           if animate else "[1:v]format=rgba[t];[v][t]overlay=0:0")
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{CLIP_S}", "-i", str(src),
         "-loop", "1", "-t", f"{CLIP_S}", "-i", str(overlay_png),
         "-filter_complex",
         f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,"
         f"eq=contrast=1.04:saturation=1.08:brightness=0.01,colorbalance=rs=0.04:gs=0.01:bs=-0.04[v];"
         f"{txt},format=yuv420p[o]",
         "-map", "[o]", "-an", *VENC, str(dest)])


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

    texts = [(topic["hook"], "hook")] + [(t, "tip") for t, _ in topic["tips"]]
    queries = [topic["hook_q"]] + [q for _, q in topic["tips"]]
    segs, clips = [], []
    for i, ((txt, kind), q) in enumerate(zip(texts, queries)):
        raw = TMP / f"raw{i}.mp4"
        info = fake_clip(i, raw) if LOCAL else fetch_clip(q, used, raw, caption=txt)
        used.add(info["id"]); clips.append(info)
        png = TMP / f"t{i}.png"
        text_layer(txt, kind).save(png)
        start = random.uniform(0.3, max(0.4, info["duration"] - CLIP_S - 0.5))
        seg = TMP / f"s{i}.mp4"
        segment(raw, info["duration"], start, png, seg, animate=(i > 0))
        segs.append(seg)

    end_png = TMP / "end.png"
    end_card(end_png)
    end_mp4 = TMP / "end.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{END_S}", "-i", str(end_png), "-vf", f"fps={FPS},format=yuv420p",
         *VENC, str(end_mp4)])
    segs.append(end_mp4)

    lst = TMP / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    joined = TMP / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    # Ovoz: musiqasiz - xona foni + har kadrga mos uy ovozi (ASMR) + oxirida yumshoq "pop"
    total = CLIP_S * len(segs[:-1]) + END_S
    audio, sfx_used = build_audio(queries, total)
    reel = OUT / "reel.mp4"
    run(["ffmpeg", "-y", "-i", str(joined), "-i", str(audio), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(reel)])
    run(["ffmpeg", "-y", "-ss", "1.2", "-i", str(reel), "-frames:v", "1", "-q:v", "3", str(OUT / "preview.jpg")])

    # Instagram 2025-12 dan beri 5 tadan ortiq heshtegni qabul qilmaydi - mavzuga oid 5 tasi yetarli
    tags = " ".join(list(dict.fromkeys(topic.get("tags", []) + BASE_TAGS))[:5])
    caption = (f"{topic['hook']}\n\n" + "\n".join(f"• {t}" for t, _ in topic["tips"]) +
               f"\n\nWhich tip will you try first? Save this for later 📌"
               f"\nFollow {HANDLE} for a little home idea every day.\n\n{tags}\n\nVideo: Pexels")
    (OUT / "caption.txt").write_text(caption, encoding="utf-8")
    (OUT / "info.json").write_text(json.dumps({"topic": idx + 1, "hook": topic["hook"], "clips": clips,
                                               "sounds": sfx_used}, indent=1))

    state["next_topic"] = (idx + 1) % len(TOPICS)
    state["used_videos"] = list(used)[-400:]
    if not LOCAL:
        STATE.write_text(json.dumps(state, indent=1))
    print(f"Tayyor: {reel} ({reel.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
