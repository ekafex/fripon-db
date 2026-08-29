from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from PIL import Image


def download_capture_image(capture: dict, output_dir: str | Path, session: requests.Session | None = None, timeout: int = 30) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = capture["image_url"].rsplit("/", 1)[-1]
    path = output_dir / filename

    own_session = session is None
    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fireball.fripon.org/",
        })

    status = "exists"
    if not path.exists():
        r = session.get(capture["image_url"], timeout=timeout)
        r.raise_for_status()
        if not r.content.startswith(b"\xff\xd8"):
            raise ValueError(f"Response is not a JPEG for capture {capture['id']}")

        temp_path = path.with_suffix(path.suffix + ".part")
        temp_path.write_bytes(r.content)
        temp_path.replace(path)
        status = "downloaded"

    raw = path.read_bytes()
    if not raw.startswith(b"\xff\xd8"):
        raise ValueError(f"Existing file is not a JPEG: {path}")

    sha256 = hashlib.sha256(raw).hexdigest()
    with Image.open(path) as img:
        img.verify()
    with Image.open(path) as img:
        width, height = img.size
        image_format = img.format

    if image_format != "JPEG":
        raise ValueError(f"Expected JPEG, got {image_format}: {path}")

    result = dict(capture)
    result.update({
        "local_path": str(path),
        "file_size_bytes": len(raw),
        "sha256": sha256,
        "width": int(width),
        "height": int(height),
        "download_status": status,
    })

    if own_session:
        session.close()
    return result
