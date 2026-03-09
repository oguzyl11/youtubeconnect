#!/usr/bin/env python3
"""
Birden fazla YouTube video ID'sini sırayla işleyen batch script.
- Liste veya .txt dosyasından ID okur
- Her video için fetch_transcript.py'yi subprocess ile çağırır
- İstekler arası 3-10 sn rastgele bekleme
- Her 5 videoda bir 30 sn cool-off (insan molası simülasyonu)
- Başarılılar: success.log, hatalar: error.log
"""
import argparse
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCH_SCRIPT = ROOT / "scripts" / "fetch_transcript.py"
SUCCESS_LOG = ROOT / "success.log"
ERROR_LOG = ROOT / "error.log"


def load_video_ids(source: str) -> list:
    """Liste veya .txt dosyasından video ID'lerini yükler."""
    path = Path(source)
    if path.suffix.lower() == ".txt" and path.is_file():
        ids = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                vid = line.strip()
                if vid and not vid.startswith("#"):
                    ids.append(vid)
        return ids
    # Virgülle ayrılmış liste
    return [x.strip() for x in source.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Birden fazla YouTube ID'si için transkript çeker (batch)"
    )
    parser.add_argument(
        "source",
        help="Video ID listesi: virgülle ayrılmış (id1,id2,...) veya .txt dosya yolu",
    )
    parser.add_argument(
        "-c",
        "--cookies",
        default="cookies.txt",
        help="cookies.txt dosya yolu (varsayılan: cookies.txt)",
    )
    parser.add_argument(
        "--no-cookies",
        action="store_true",
        help="Cookies kullanma",
    )
    parser.add_argument(
        "-l",
        "--languages",
        default="tr,en",
        help="Dil kodları (virgülle, varsayılan: tr,en)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Transkript JSON dosyalarının kaydedileceği klasör (yoksa stdout)",
    )
    parser.add_argument(
        "--min-wait",
        type=float,
        default=3,
        help="Minimum bekleme süresi (sn, varsayılan: 3)",
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=10,
        help="Maksimum bekleme süresi (sn, varsayılan: 10)",
    )
    parser.add_argument(
        "--cooloff-every",
        type=int,
        default=5,
        help="Her N videoda cool-off (varsayılan: 5)",
    )
    parser.add_argument(
        "--cooloff-secs",
        type=float,
        default=30,
        help="Cool-off süresi (sn, varsayılan: 30)",
    )
    args = parser.parse_args()

    ids = load_video_ids(args.source)
    if not ids:
        print("Hata: Hiç video ID bulunamadı.", file=sys.stderr)
        return 1

    if not FETCH_SCRIPT.is_file():
        print(f"Hata: fetch_transcript.py bulunamadı: {FETCH_SCRIPT}", file=sys.stderr)
        return 1

    success_ids = []
    error_ids = []

    for i, vid in enumerate(ids):
        num = i + 1
        print(f"[{num}/{len(ids)}] İşleniyor: {vid}")

        cmd = [sys.executable, str(FETCH_SCRIPT), vid]
        if not args.no_cookies:
            cmd.extend(["-c", args.cookies])
        else:
            cmd.append("--no-cookies")
        cmd.extend(["-l", args.languages])
        if args.output_dir:
            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{vid}.json"
            cmd.extend(["-o", str(out_file)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                success_ids.append(vid)
                print(f"  -> Başarılı")
            else:
                error_ids.append(vid)
                err = (result.stderr or result.stdout or "").strip()[:200]
                print(f"  -> Hata: {err}")
        except subprocess.TimeoutExpired:
            error_ids.append(vid)
            print("  -> Zaman aşımı")
        except Exception as e:
            error_ids.append(vid)
            print(f"  -> Hata: {e}")

        # Cool-off: her N videoda uzun mola
        if (num % args.cooloff_every) == 0 and num < len(ids):
            print(f"  [Cool-off] {args.cooloff_secs:.0f} sn mola...")
            time.sleep(args.cooloff_secs)
            continue

        # Normal bekleme (son video hariç)
        if num < len(ids):
            wait = random.uniform(args.min_wait, args.max_wait)
            print(f"  [Bekleme] {wait:.1f} sn...")
            time.sleep(wait)

    # Log dosyalarına yaz
    with open(SUCCESS_LOG, "a", encoding="utf-8") as f:
        for vid in success_ids:
            f.write(f"{vid}\n")
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        for vid in error_ids:
            f.write(f"{vid}\n")

    print(f"\nÖzet: {len(success_ids)} başarılı, {len(error_ids)} hata")
    print(f"  success.log: {SUCCESS_LOG}")
    print(f"  error.log: {ERROR_LOG}")
    return 0 if not error_ids else 1


if __name__ == "__main__":
    sys.exit(main())
