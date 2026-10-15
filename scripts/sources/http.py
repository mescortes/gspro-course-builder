"""Downloads shared by the providers: retried, resumed from the .part file, renamed into place only once complete,
skipped when the file is already there."""
import os, re, time
import requests

UA = {"User-Agent": "gspro-course-builder/0.1 (personal research)"}


def permanent(code):
    """An HTTP status no retry changes: a 4xx other than 408 (request timeout) and 429 (too many requests)."""
    return 400 <= code < 500 and code not in (408, 429)


class PermanentError(RuntimeError):
    """A permanent HTTP error (see permanent()); `status` is its code. A caller can tell a wrong URL or asset id from
    a network failure with it: `missing` (404, 410) is the server saying the thing is not there; any other code (401,
    403, 451: a proxy, a firewall or a bot block refusing the request) says nothing about the URL."""
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status

    @property
    def missing(self):
        return self.status in (404, 410)


def _total(r, have):
    """Size of the whole file from a 200 / 206 reply (None when the reply does not say, or is content-encoded)."""
    if r.headers.get("Content-Encoding", "identity") != "identity":
        return None
    m = re.match(r"bytes (\d+)-\d+/(\d+)", r.headers.get("Content-Range", ""))
    if r.status_code == 206 and m:
        return int(m.group(2))
    n = r.headers.get("Content-Length")
    return int(n) + (have if r.status_code == 206 else 0) if n else None


def download(url, dst, size=None, attempts=5):
    """`url` into `dst` through <dst>.part, renamed into place only once it is complete (`size` bytes when given, else
    the Content-Length), so a killed or truncated transfer never leaves a `dst` a rerun trusts. A retry, or a rerun
    after a crash, resumes the .part file with a Range request; a server that ignores it sends the whole file again.
    A 416 to that request means the .part is already whole when its size is the one the server names (a crash before
    the rename): it is renamed, not fetched again. A permanent 4xx (a stale link, a proxy 403) fails at once with its
    status (PermanentError)."""
    if dst.exists() and (size is None or dst.stat().st_size == size):
        return
    print("downloading", dst.name, round((size or 0) / 1e6), "MB", flush=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    err = None
    for attempt in range(attempts):
        have = tmp.stat().st_size if tmp.exists() else 0
        if size is not None and have == size:   # complete before a crash, not yet renamed
            os.replace(tmp, dst)
            return
        if size is not None and have > size:
            tmp.unlink(); have = 0
        try:
            with requests.get(url, headers=dict(UA, Range=f"bytes={have}-") if have else UA, stream=True,
                              timeout=(60, 600)) as r:
                if r.status_code == 416:            # nothing left to send: the .part is whole, or stale
                    m = re.fullmatch(r"bytes \*/(\d+)", r.headers.get("Content-Range", "").strip())
                    if m and have and int(m.group(1)) == have and size in (None, have):
                        os.replace(tmp, dst)
                        return
                    tmp.unlink(missing_ok=True); err = "HTTP 416"   # start over
                    continue
                if permanent(r.status_code):
                    raise PermanentError(f"download failed (HTTP {r.status_code}): {url}", r.status_code)
                r.raise_for_status()
                resume = r.status_code == 206
                total = size if size is not None else _total(r, have)
                with open(tmp, "ab" if resume else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            got = tmp.stat().st_size
            if total is None or got == total:
                os.replace(tmp, dst)
                return
            err = f"{got} of {total} bytes"
        except requests.RequestException as ex:
            code = getattr(getattr(ex, "response", None), "status_code", None)
            err = ex.__class__.__name__ + (f" (HTTP {code})" if code else "")
        print("  retry", attempt + 1, err, flush=True); time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"download failed ({err}): {url} (rerun to resume from {tmp.name})")


def _head(url):
    """The HEAD reply (after redirects, as GDAL and a GET follow them) when it is 200 or 404. Any other answer is retried,
    then raised: a proxy 403 or an S3 503 must not read as a missing file."""
    for attempt in range(5):
        try:
            r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
            if r.status_code in (200, 404):
                return r
            err = f"HTTP {r.status_code}"
        except requests.RequestException as ex:
            err = ex.__class__.__name__
        print("  retry HEAD", attempt + 1, err, flush=True); time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"HEAD failed ({err}): {url}")


def size(url):
    """Content-Length from a HEAD request; None when the file is not there (404)."""
    r = _head(url)
    if r.status_code == 404:
        return None
    return int(r.headers.get("Content-Length", 0)) or None


def exists(url):
    """True when the file is there, False on a 404."""
    return _head(url).status_code == 200


def get_json(url, params=None, valid=lambda j: True, attempts=5, timeout=120):
    """The JSON reply to a GET, retried on network errors, 5xx / 408 / 429 and replies `valid` rejects (an error body,
    an HTML gateway page); a permanent 4xx fails at once (PermanentError). Raises RuntimeError naming the last error."""
    err = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                j = r.json()
                if valid(j):
                    return j
                err = f"unexpected reply {str(j)[:200]}"
            elif permanent(r.status_code):
                raise PermanentError(f"HTTP {r.status_code} from {url}: {getattr(r, 'text', '')[:200]}", r.status_code)
            else:
                err = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as ex:
            err = ex.__class__.__name__
        print("  retry", url.split("/")[2], attempt + 1, err, flush=True); time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"{url} failed ({err})")
