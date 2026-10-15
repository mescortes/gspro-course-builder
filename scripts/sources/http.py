"""Downloads shared by the providers: resumable to a .part file, retried, skipped when the file is complete."""
import time
import requests

UA = {"User-Agent": "gspro-course-builder/0.1 (personal research)"}


def download(url, dst, size=None):
    if dst.exists() and (size is None or dst.stat().st_size == size):
        return
    print("downloading", dst.name, round((size or 0) / 1e6), "MB", flush=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    for attempt in range(5):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=(60, 600)) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.rename(dst)
            return
        except requests.RequestException as ex:
            print("  retry", attempt + 1, ex.__class__.__name__, flush=True); time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}")


def size(url):
    """Content-Length from a HEAD request; None when the file is not there (404). Any other answer is retried, then
    raised: a proxy 403 or an S3 503 must not read as a missing tile."""
    for attempt in range(5):
        try:
            r = requests.head(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return int(r.headers.get("Content-Length", 0)) or None
            if r.status_code == 404:
                return None
            err = f"HTTP {r.status_code}"
        except requests.RequestException as ex:
            err = ex.__class__.__name__
        print("  retry HEAD", attempt + 1, err, flush=True); time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"HEAD failed ({err}): {url}")
