"""Tayyor reel'ni Make.com webhook'iga yuboradi. Make uni @homzie.us'ga joylaydi.

Foydalanish: python3 scripts/post_make.py <ochiq video havolasi>
Kerak: MAKE_WEBHOOK_URL (secret). Bo'lmasa - hech narsa qilmaydi.
Make javobi (Instagram post ID'si yoki xato) logga va step summary'ga yoziladi.
"""
import json, os, pathlib, sys, time, urllib.request, urllib.error

URL = os.environ.get("MAKE_WEBHOOK_URL", "").strip()
OUT = pathlib.Path(__file__).resolve().parent.parent / "out"


def main():
    if not URL:
        print("MAKE_WEBHOOK_URL qo'yilmagan - Instagram'ga joylash o'tkazib yuborildi")
        return
    video = sys.argv[1]
    caption = (OUT / "caption.txt").read_text(encoding="utf-8")
    body = json.dumps({"video_url": video, "caption": caption}).encode()
    for attempt in range(3):
        req = urllib.request.Request(URL, data=body, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                answer = r.read().decode("utf-8", "replace")[:500]
            print(f"Make javobi: {answer}")
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with open(summary, "a", encoding="utf-8") as f:
                    f.write(f"\n## Instagram\nVideo: {video}\n\nMake javobi: `{answer}`\n")
            return
        except urllib.error.HTTPError as e:
            print(f"Make HTTP {e.code}: {e.read()[:300]!r}")
            if e.code < 500:
                sys.exit(1)
        except Exception as e:  # noqa: BLE001
            print(f"Make'ga ulanib bo'lmadi: {e}")
        time.sleep(30 * (attempt + 1))
    sys.exit("Make 3 marta javob bermadi")


if __name__ == "__main__":
    main()
