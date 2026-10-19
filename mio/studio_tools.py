"""Bounded live web snippets, local vision and optional local ComfyUI raster images."""
from __future__ import annotations

import asyncio
import base64
import html
import json
import os
import re
import secrets
import stat
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from xml.etree import ElementTree

import httpx

from mio.model_fleet import inference_lock, inventory
from mio.studio_files import StudioError

SEARCH_URL = "https://www.bing.com/search?format=rss&q="
IMAGE_URL = "http://127.0.0.1:8188"
OLLAMA_URL = "http://127.0.0.1:11434"
MAX_IMAGE = 8 * 1024 * 1024


def _valid_link(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname is not None
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443)
                and parsed.hostname not in ("localhost", "127.0.0.1")
                and not parsed.hostname.endswith((".local", ".internal")))
    except ValueError:
        return False


class _LiteResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self.snippets: list[str] = []
        self.current: str | None = None
        self.buf: list[str] = []
        self.href = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "")
        if tag == "a" and "result-link" in cls:
            self.current = "link"
            self.buf = []
            self.href = attr.get("href", "")
        elif tag == "td" and "result-snippet" in cls:
            self.current = "snippet"
            self.buf = []

    def handle_data(self, data):
        if self.current:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if self.current == "link" and tag == "a":
            url = self.href
            parsed = urlparse(url)
            if parsed.hostname in ("duckduckgo.com", "www.duckduckgo.com") and parsed.path == "/l/":
                url = parse_qs(parsed.query).get("uddg", [""])[0]
            if _valid_link(url):
                self.links.append({"title": " ".join(self.buf)[:160], "url": url})
            self.current = None
        elif self.current == "snippet" and tag == "td":
            self.snippets.append(" ".join(self.buf)[:450])
            self.current = None


async def _duckduckgo(query: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        response = await client.get("https://lite.duckduckgo.com/lite/?q=" + quote(query, safe=""))
        if response.status_code != 200 or len(response.content) > 900_000:
            return []
        parser = _LiteResults()
        parser.feed(response.text)
        results = []
        for i, item in enumerate(parser.links[:6]):
            if i < len(parser.snippets) and item["title"] and parser.snippets[i]:
                results.append({"ref": f"W{len(results)+1}", "title": item["title"],
                                "url": item["url"], "snippet": parser.snippets[i]})
        return results
    except (httpx.HTTPError, ValueError):
        return []


async def web_search(query: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Fetch search snippets only from a fixed public endpoint; no arbitrary URL fetching."""
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 350:
        raise StudioError("Search requires a question of 3–350 characters")
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(18, connect=6), follow_redirects=False,
                                   trust_env=False, headers={"User-Agent": "MioAgent/0.4H research"})
    try:
        results = []
        try:
            response = await client.get(SEARCH_URL + quote(query.strip(), safe=""))
            if (response.status_code == 200 and len(response.content) <= 900_000
                    and b"<!DOCTYPE" not in response.content.upper()
                    and b"<!ENTITY" not in response.content.upper()):
                tree = ElementTree.fromstring(response.content)
                for item in tree.findall(".//item")[:12]:
                    url = (item.findtext("link") or "").strip()
                    if not _valid_link(url):
                        continue
                    title = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("title") or ""))[:160]
                    snippet = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("description") or ""))[:450]
                    if title and snippet:
                        results.append({"ref": f"W{len(results)+1}", "title": title,
                                        "url": url, "snippet": snippet})
                    if len(results) >= 6:
                        break
        except (httpx.HTTPError, ValueError, ElementTree.ParseError):
            pass
        if not results:
            results = await _duckduckgo(query.strip(), client)
        if not results:
            raise StudioError("Both public web-search providers were unavailable; no evidence was collected")
        return results
    finally:
        if owned:
            await client.aclose()


async def vision_answer(prompt: str, images: list[bytes], model_names: list[str],
                        installed: dict | None = None,
                        client: httpx.AsyncClient | None = None) -> tuple[str, str]:
    """Use native Ollama image messages only after checking advertised vision capability."""
    installed = await inventory() if installed is None else installed
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=6),
                                   trust_env=False, follow_redirects=False)
    try:
        for model in model_names:
            if model not in installed:
                continue
            try:
                about = await client.post(f"{OLLAMA_URL}/api/show", json={"model": model})
                about.raise_for_status()
                if "vision" not in about.json().get("capabilities", []):
                    continue
                with inference_lock():
                    reply = await client.post(f"{OLLAMA_URL}/api/chat", json={
                        "model": model, "stream": False,
                        "messages": [{"role": "user", "content": prompt,
                                      "images": [base64.b64encode(i).decode() for i in images]}],
                        "options": {"num_predict": 1100, "temperature": 0.2}, "think": False,
                    })
                reply.raise_for_status()
                answer = reply.json().get("message", {}).get("content")
                if isinstance(answer, str) and answer.strip():
                    return answer.strip(), model
            except (httpx.HTTPError, ValueError, TypeError):
                continue
        raise StudioError("No approved local vision model produced an answer; confirm Ollama vision support")
    finally:
        if owned:
            await client.aclose()


def comfy_settings(root: Path) -> dict | None:
    path = root / "image-backend.json"
    if not path.exists():
        return None
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise StudioError("Unsafe image backend configuration")
    info = json.loads(path.read_text())
    if (not isinstance(info, dict) or set(info) != {"checkpoint"}
            or not isinstance(info["checkpoint"], str)
            or not re.fullmatch(r"[A-Za-z0-9_ ./-]{2,160}\.safetensors", info["checkpoint"])
            or ".." in info["checkpoint"]):
        raise StudioError("Invalid configured image checkpoint")
    return info


async def available_checkpoints(client: httpx.AsyncClient | None = None) -> list[str]:
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(f"{IMAGE_URL}/object_info/CheckpointLoaderSimple")
        response.raise_for_status()
        options = response.json()["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        if not isinstance(options, list):
            return []
        return [str(x) for x in options[:100] if isinstance(x, str)]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        return []
    finally:
        if owned:
            await client.aclose()


def image_workflow(checkpoint: str, prompt: str, seed: int) -> dict:
    """Standard built-in SD1.x/SDXL workflow; checkpoint compatibility remains operator's duty."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, watermark, low quality", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 22, "cfg": 7.0,
              "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
              "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "MioAgent", "images": ["8", 0]}},
    }


async def generate_raster(prompt: str, checkpoint: str, client: httpx.AsyncClient | None = None) -> bytes:
    if not isinstance(prompt, str) or not 4 <= len(prompt) <= 1200:
        raise StudioError("Image prompt must be 4–1200 characters")
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(25, connect=5),
                                   trust_env=False, follow_redirects=False)
    try:
        checkpoints = await available_checkpoints(client)
        if checkpoint not in checkpoints:
            raise StudioError("Configured checkpoint not found in local ComfyUI")
        # Prevent GPU contention with fleet-managed local inference.
        with inference_lock():
            response = await client.post(f"{IMAGE_URL}/prompt", json={
                "prompt": image_workflow(checkpoint, prompt, secrets.randbits(48)),
                "client_id": str(uuid.uuid4())})
            response.raise_for_status()
            task_id = response.json().get("prompt_id")
            if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", task_id):
                raise StudioError("ComfyUI rejected the image workflow")
            for _ in range(72):
                await asyncio.sleep(2)
                history = await client.get(f"{IMAGE_URL}/history/{task_id}")
                history.raise_for_status()
                item = history.json().get(task_id, {})
                if item.get("status", {}).get("status_str") == "error":
                    raise StudioError("Local image generation failed in ComfyUI")
                outputs = item.get("outputs", {})
                for node in outputs.values():
                    for image in node.get("images", []):
                        if image.get("type") != "output":
                            continue
                        response = await client.get(f"{IMAGE_URL}/view", params={
                            "filename": image["filename"], "subfolder": image.get("subfolder", ""),
                            "type": "output"})
                        response.raise_for_status()
                        raw = response.content
                        if len(raw) > MAX_IMAGE or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                            raise StudioError("Image output is not a bounded PNG")
                        return raw
            raise StudioError("Image generation timed out; inspect the local ComfyUI queue")
    except httpx.HTTPError as exc:
        raise StudioError(f"ComfyUI unavailable ({type(exc).__name__})") from exc
    finally:
        if owned:
            await client.aclose()
