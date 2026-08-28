import os
import io
import sys
import time
import mimetypes
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from PIL import Image

BSKY_BASE = "https://bsky.social"
BSKY_PUBLIC_BASE = "https://public.api.bsky.app"
RSS_URL = os.environ["RSS_URL"]
BSKY_HANDLE = os.environ["BSKY_HANDLE"]
BSKY_APP_PASSWORD = os.environ["BSKY_APP_PASSWORD"]

MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
INITIAL_LOOKBACK_MINUTES = int(os.getenv("INITIAL_LOOKBACK_MINUTES", "45"))

session = requests.Session()
session.headers.update({"User-Agent": "Xboxygen-Bluesky-RSS-Bot/1.0"})


def api_post(endpoint, token=None, json_data=None, data=None, content_type=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    r = session.post(f"{BSKY_BASE}/xrpc/{endpoint}", headers=headers, json=json_data, data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def api_get(endpoint, params=None):
    r = session.get(f"{BSKY_PUBLIC_BASE}/xrpc/{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def login():
    return api_post(
        "com.atproto.server.createSession",
        json_data={"identifier": BSKY_HANDLE, "password": BSKY_APP_PASSWORD},
    )


def get_recent_post_urls(actor, limit=100):
    urls = set()
    cursor = None
    remaining = limit

    while remaining > 0:
        batch = min(100, remaining)
        params = {"actor": actor, "limit": batch, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor

        data = api_get("app.bsky.feed.getAuthorFeed", params=params)
        feed = data.get("feed", [])

        for item in feed:
            post = item.get("post", {})
            record = post.get("record", {})
            text = record.get("text", "")
            for token in text.split():
                if token.startswith("http://") or token.startswith("https://"):
                    urls.add(token.rstrip(".,);]"))

            embed = post.get("embed") or {}
            external = embed.get("external") or {}
            uri = external.get("uri")
            if uri:
                urls.add(uri)

        remaining -= len(feed)
        cursor = data.get("cursor")
        if not cursor or not feed:
            break

    return urls


def parse_entry_datetime(entry):
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def clean_text(value, max_len):
    value = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    value = " ".join(value.split())
    return value[:max_len]


def fetch_open_graph(url):
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        def meta(prop=None, name=None):
            attrs = {"property": prop} if prop else {"name": name}
            tag = soup.find("meta", attrs=attrs)
            return tag.get("content", "").strip() if tag else ""

        title = meta(prop="og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
        description = meta(prop="og:description") or meta(name="description")
        image = meta(prop="og:image")

        if image:
            image = urljoin(url, image)

        return {
            "title": clean_text(title, 300),
            "description": clean_text(description, 300),
            "image": image,
        }
    except Exception as exc:
        print(f"[WARN] OpenGraph impossible pour {url}: {exc}")
        return {"title": "", "description": "", "image": ""}


def prepare_image(url):
    if not url:
        return None, None

    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")

        # Bluesky limite les blobs : on réduit proprement pour rester léger.
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        quality = 88
        img.save(out, format="JPEG", quality=quality, optimize=True)

        while out.tell() > 900_000 and quality > 50:
            quality -= 8
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)

        return out.getvalue(), "image/jpeg"
    except Exception as exc:
        print(f"[WARN] Image impossible à préparer: {exc}")
        return None, None


def upload_blob(token, image_bytes, content_type):
    if not image_bytes:
        return None
    result = api_post(
        "com.atproto.repo.uploadBlob",
        token=token,
        data=image_bytes,
        content_type=content_type,
    )
    return result.get("blob")


def make_link_facet(text, url):
    start = text.rfind(url)
    if start < 0:
        return []

    before = text[:start].encode("utf-8")
    target = url.encode("utf-8")
    return [{
        "index": {
            "byteStart": len(before),
            "byteEnd": len(before) + len(target),
        },
        "features": [{
            "$type": "app.bsky.richtext.facet#link",
            "uri": url,
        }],
    }]


def publish_post(repo_did, token, title, url, description, thumb_blob=None):
    # 300 caractères max sur Bluesky. On garde le titre + lien.
    suffix = f"\n\n{url}"
    max_title = max(20, 300 - len(suffix))
    text = title[:max_title].rstrip() + suffix

    external = {
        "$type": "app.bsky.embed.external#external",
        "uri": url,
        "title": title[:300],
        "description": description[:300],
    }
    if thumb_blob:
        external["thumb"] = thumb_blob

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "facets": make_link_facet(text, url),
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "embed": {
            "$type": "app.bsky.embed.external",
            "external": external,
        },
    }

    return api_post(
        "com.atproto.repo.createRecord",
        token=token,
        json_data={
            "repo": repo_did,
            "collection": "app.bsky.feed.post",
            "record": record,
        },
    )


def main():
    auth = login()
    token = auth["accessJwt"]
    did = auth["did"]

    recent_urls = get_recent_post_urls(did, limit=100)
    print(f"[INFO] {len(recent_urls)} URL(s) déjà trouvée(s) dans les posts récents.")

    feed = feedparser.parse(RSS_URL)
    if feed.bozo:
        print(f"[WARN] Le flux RSS signale une erreur: {feed.bozo_exception}")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=INITIAL_LOOKBACK_MINUTES)

    candidates = []
    for entry in feed.entries:
        url = getattr(entry, "link", "").strip()
        if not url or url in recent_urls:
            continue

        published = parse_entry_datetime(entry)
        if published and published < cutoff:
            continue

        title = clean_text(getattr(entry, "title", ""), 300)
        if not title:
            continue

        candidates.append((published or now, title, url, entry))

    candidates.sort(key=lambda x: x[0])
    candidates = candidates[-MAX_POSTS_PER_RUN:]

    if not candidates:
        print("[INFO] Aucun nouvel article à publier.")
        return

    for _, rss_title, url, entry in candidates:
        og = fetch_open_graph(url)
        title = og["title"] or rss_title
        description = og["description"] or clean_text(getattr(entry, "summary", ""), 300)

        image_bytes, content_type = prepare_image(og["image"])
        thumb_blob = upload_blob(token, image_bytes, content_type) if image_bytes else None

        result = publish_post(did, token, title, url, description, thumb_blob)
        print(f"[OK] Publié : {title}")
        print(f"     {result.get('uri', '')}")
        recent_urls.add(url)
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
