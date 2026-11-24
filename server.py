import json
import os
from typing import Optional
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AiTechApp-MCP")

BASE_URL = os.getenv("AITECHAPP_BASE_URL", "https://aitechapp.in").rstrip("/")
PROXY_URL = os.getenv("AITECHAPP_PROXY_URL", f"{BASE_URL}/proxy.php")
PLP_API_URL = os.getenv("AITECHAPP_PLP_API_URL", f"{BASE_URL}/api.php")
HUB_URL = os.getenv("AITECHAPP_HUB_URL", f"{BASE_URL}/ai-hub.php")
FONTS_API_URL = os.getenv("AITECHAPP_FONTS_API_URL", f"{BASE_URL}/scan_fonts.php")
DINBITS_API_URL = os.getenv("AITECHAPP_DINBITS_API_URL", f"{BASE_URL}/scan_anu_dinbits.php")
REVIEWS_API_URL = os.getenv("AITECHAPP_REVIEWS_API_URL", f"{BASE_URL}/reviews.php")
CACHE_JSON_PATH = os.getenv("AITECHAPP_CACHE_JSON", "cache.json")


def _load_local_cache() -> dict:
    if os.path.isfile(CACHE_JSON_PATH):
        try:
            with open(CACHE_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _local_convert(text: str, cache: dict) -> str:
    if not cache:
        return text
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in (" ", "\n"):
            out.append(ch)
            i += 1
            continue
        matched = False
        for length in range(min(20, n - i), 0, -1):
            sub = text[i : i + length]
            mapped = cache.get(sub)
            if mapped and mapped not in ("NO_MAPPING", "BROKEN_MAPPING"):
                out.append(str(mapped))
                i += length
                matched = True
                break
        if not matched:
            out.append(ch)
            i += 1
    return "".join(out)


@mcp.tool()
async def convert_telugu_to_anu(text: str, alt_ra: bool = False) -> dict:
    """Convert Telugu Unicode text to Non-Unicode Anu script using local cache first and proxy fallback."""
    cache = _load_local_cache()
    local_result = _local_convert(text, cache)

    if not alt_ra and local_result and local_result != text:
        return {"source": "local_cache", "alt_ra": False, "result": local_result}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                PROXY_URL,
                data={
                    "type": "convert",
                    "input": text,
                    "replaceSpaces": "false",
                    "altRa": "true" if alt_ra else "false",
                },
                headers={"Origin": BASE_URL},
            )
            body = resp.text.strip()
            if resp.status_code == 200 and "SECURITY_BLOCK" not in body and "<html" not in body.lower():
                return {"source": "proxy_api", "alt_ra": alt_ra, "result": body}
    except Exception as exc:
        return {"source": "local_fallback", "alt_ra": alt_ra, "result": local_result, "note": str(exc)}

    return {"source": "local_fallback", "alt_ra": alt_ra, "result": local_result}


@mcp.tool()
async def list_telugu_fonts(query: Optional[str] = None, limit: int = 30) -> dict:
    """Fetch available Telugu fonts and their like, share, and download statistics."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(FONTS_API_URL)
        resp.raise_for_status()
        fonts = resp.json()

    if not isinstance(fonts, list):
        return {"count": 0, "fonts": []}

    if query:
        q = query.strip().lower()
        fonts = [
            f for f in fonts
            if q in str(f.get("name", "")).lower() or q in str(f.get("id", "")).lower()
        ]

    trimmed = fonts[: max(1, min(limit, 250))]
    return {"count": len(trimmed), "total_matched": len(fonts), "fonts": trimmed}


@mcp.tool()
async def list_anu_dinbits(query: Optional[str] = None, limit: int = 30) -> dict:
    """Fetch Anu Dinbits font entries and per-glyph engagement stats."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(DINBITS_API_URL)
        resp.raise_for_status()
        items = resp.json()

    if not isinstance(items, list):
        return {"count": 0, "dinbits": []}

    if query:
        q = query.strip().lower()
        items = [
            d for d in items
            if q in str(d.get("name", "")).lower() or q in str(d.get("id", "")).lower()
        ]

    trimmed = items[: max(1, min(limit, 200))]
    return {"count": len(trimmed), "total_matched": len(items), "dinbits": trimmed}


@mcp.tool()
async def search_plp_templates(
    query: Optional[str] = None,
    category: Optional[str] = None,
    paid_only: Optional[bool] = None,
    limit: int = 20,
) -> dict:
    """Search PixelLab (PLP) templates from api.php."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(f"{PLP_API_URL}?action=fetch")
        resp.raise_for_status()
        templates = resp.json()

    if not isinstance(templates, list):
        return {"count": 0, "templates": []}

    if category and category.lower() != "all":
        c = category.strip().lower()
        templates = [t for t in templates if str(t.get("category", "")).lower() == c]

    if paid_only is not None:
        want_paid = 1 if paid_only else 0
        templates = [t for t in templates if int(t.get("is_paid") or 0) == want_paid]

    if query:
        q = query.strip().lower()
        templates = [
            t for t in templates
            if q in f"{t.get('name', '')} {t.get('tags', '')} {t.get('category', '')} {t.get('uploader_name', '')}".lower()
        ]

    trimmed = templates[: max(1, min(limit, 100))]
    return {"count": len(trimmed), "total_matched": len(templates), "templates": trimmed}


@mcp.tool()
async def get_hub_feed_summary(category: Optional[str] = None, limit: int = 15) -> dict:
    """Fetch AI Prompts Hub page summary and structured JSON-LD item list."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(HUB_URL)
        resp.raise_for_status()
        html = resp.text

    items = []
    marker = '<script type="application/ld+json">'
    idx = html.find(marker)
    if idx != -1:
        start = idx + len(marker)
        end = html.find("</script>", start)
        if end != -1:
            try:
                ld = json.loads(html[start:end])
                for node in ld.get("@graph", []):
                    if node.get("@type") == "ItemList":
                        for el in node.get("itemListElement", []):
                            items.append({
                                "position": el.get("position"),
                                "name": el.get("name"),
                                "url": el.get("url"),
                            })
            except Exception:
                pass

    if category and category.lower() != "all":
        c = category.strip().lower()
        items = [it for it in items if c in str(it.get("name", "")).lower()]

    trimmed = items[: max(1, min(limit, 50))]
    return {"hub_url": HUB_URL, "count": len(trimmed), "featured_prompts": trimmed}


@mcp.tool()
async def get_reviews_summary() -> dict:
    """Fetch ratings and review summary from reviews.php."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(f"{REVIEWS_API_URL}?action=get_summary")
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    mcp.run(transport="stdio")
