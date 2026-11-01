"""Download a pinned HF snapshot once; check the local files on later starts."""

import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ValueError("HTTPS required")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def valid_snapshot(path, model_id, revision):
    try:
        marker = json.loads((path / ".complete.json").read_text())
        if marker["model_id"] != model_id or marker["revision"] != revision:
            return False
        files = marker["files"]
        if not files or "config.json" not in files:
            return False
        if not any(name.endswith(".safetensors") for name in files):
            return False
        for name, checksum in files.items():
            if not safe_name(name) or digest(path / name) != checksum:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def safe_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name


def download(root, model_id, revision, token=""):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", model_id):
        raise ValueError("Invalid model ID")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use a full commit SHA")
    root.mkdir(parents=True, exist_ok=True)
    target = root / revision
    with (root / ".download.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if valid_snapshot(target, model_id, revision):
            print('{"event":"model_cache_hit"}', flush=True)
            return target
        if os.environ.get("MODEL_ALLOW_DOWNLOAD", "1") != "1":
            raise RuntimeError("Downloads are disabled and the cache is invalid")
        opener = build_opener(SafeRedirect())

        def open_hf(url):
            headers = {"User-Agent": "cpu-model-downloader/1.0"}
            if token:
                headers["Authorization"] = "Bearer " + token
            return opener.open(Request(url, headers=headers), timeout=300)

        base = "https://huggingface.co"
        with open_hf(f"{base}/api/models/{model_id}/revision/{revision}") as response:
            info = json.load(response)
        if info["sha"] != revision:
            raise ValueError("Revision mismatch")
        names = [item["rfilename"] for item in info["siblings"]]
        # This service uses safetensors and does not run Python code from HF.
        names = sorted(name for name in names if safe_name(name) and name.endswith(
            (".safetensors", ".json", ".model", ".txt", ".tiktoken", ".jinja")
        ))
        if "config.json" not in names or not any(n.endswith(".safetensors") for n in names):
            raise ValueError("Missing config or safetensors weights")
        staging = root / (revision + ".partial")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        checksums = {}
        for name in names:
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"{base}/{model_id}/resolve/{revision}/{quote(name, safe='/')}?download=true"
            with open_hf(url) as response, path.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            checksums[name] = digest(path)
        (staging / ".complete.json").write_text(json.dumps({
            "model_id": model_id, "revision": revision, "files": checksums,
        }, indent=2) + "\n")
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
        print('{"event":"model_download_complete"}', flush=True)
        return target


def main():
    try:
        download(Path(os.environ.get("MODEL_ROOT", "/models")),
                 os.environ["MODEL_ID"], os.environ["MODEL_REVISION"],
                 os.environ.get("HF_TOKEN", ""))
    except Exception as error:
        # HTTP errors can contain signed URLs or credentials. Do not print them.
        print(json.dumps({"event": "model_download_failed", "error_type": type(error).__name__}),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
