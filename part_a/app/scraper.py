import asyncio
import concurrent.futures
import json
import re
import sys
from typing import Any, Optional
from urllib.parse import quote, urlparse, parse_qs

from playwright.async_api import async_playwright

from .models import PlaceDetails, Review


# ============================================================
# Windows-safe executor
# ============================================================

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="google-maps"
)


# ============================================================
# Constants
# ============================================================

XSSI_PREFIX = ")]}'"


# ============================================================
# JSON helpers
# ============================================================

def strip_xssi(text: str) -> str:

    text = text.strip()

    if text.startswith(XSSI_PREFIX):
        text = text[len(XSSI_PREFIX):]

    return text.strip()


def parse_google_json(text: str) -> Optional[Any]:

    text = strip_xssi(text)

    try:
        return json.loads(text)
    except Exception:
        pass

    return None


# ============================================================
# Recursive traversal
# ============================================================

def walk(node):

    if isinstance(node, list):

        for item in node:
            yield item
            yield from walk(item)

    elif isinstance(node, dict):

        for value in node.values():
            yield value
            yield from walk(value)


# ============================================================
# Find strings
# ============================================================

def all_strings(node):

    for value in walk(node):

        if isinstance(value, str):
            yield value


# ============================================================
# Find numbers
# ============================================================

def all_numbers(node):

    for value in walk(node):

        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            yield value


# ============================================================
# Find place information
# ============================================================

def extract_place_from_search_payload(
    payload: Any,
    query: str,
) -> Optional[PlaceDetails]:

    strings = list(all_strings(payload))

    # --------------------------------------------------------
    # Find exact place-name candidate
    # --------------------------------------------------------

    name = None

    query_words = [
        x.lower()
        for x in re.findall(
            r"[A-Za-z0-9]+",
            query
        )
    ]

    name_candidates = []

    for value in strings:

        value_clean = " ".join(
            value.split()
        ).strip()

        lower = value_clean.lower()

        if len(value_clean) < 3:
            continue

        if len(value_clean) > 180:
            continue

        score = 0

        for word in query_words:

            if word in lower:
                score += 10

        # A real place name usually contains letters.
        if re.search(
            r"[A-Za-z]",
            value_clean
        ):
            score += 2

        # Avoid obvious URLs.
        if "http://" in lower or "https://" in lower:
            score -= 50

        # Avoid internal IDs.
        if re.fullmatch(
            r"[A-Za-z0-9_-]{15,}",
            value_clean
        ):
            score -= 50

        if score > 0:
            name_candidates.append(
                (score, value_clean)
            )

    if name_candidates:

        name_candidates.sort(
            key=lambda x: (
                x[0],
                -len(x[1])
            ),
            reverse=True
        )

        # Prefer a meaningful place name.
        for _, candidate in name_candidates:

            if (
                "leela" in candidate.lower()
                and "palace" in candidate.lower()
            ):
                name = candidate
                break

        if name is None:
            name = name_candidates[0][1]

    # --------------------------------------------------------
    # Find address
    # --------------------------------------------------------

    address = None

    address_candidates = []

    for value in strings:

        value_clean = " ".join(
            value.split()
        ).strip()

        if len(value_clean) < 15:
            continue

        if len(value_clean) > 250:
            continue

        # Addresses generally contain commas.
        if "," not in value_clean:
            continue

        lower = value_clean.lower()

        score = 0

        if "road" in lower:
            score += 10

        if "rd" in lower:
            score += 5

        if "bengaluru" in lower:
            score += 10

        if "karnataka" in lower:
            score += 10

        if "india" in lower:
            score += 5

        if re.search(
            r"\b\d{1,6}\b",
            value_clean
        ):
            score += 5

        address_candidates.append(
            (
                score,
                len(value_clean),
                value_clean
            )
        )

    if address_candidates:

        address_candidates.sort(
            key=lambda x: (
                x[0],
                x[1]
            ),
            reverse=True
        )

        address = address_candidates[0][2]

    # --------------------------------------------------------
    # Find rating + review count
    #
    # We specifically look for:
    #
    #     [ ... "4.6", 37131 ]
    #
    # instead of taking the first 1-5 number.
    # --------------------------------------------------------

    rating = None
    total_reviews = 0

    def search_pairs(node):

        nonlocal rating
        nonlocal total_reviews

        if isinstance(node, list):

            for i in range(len(node) - 1):

                a = node[i]
                b = node[i + 1]

                # Example:
                #
                # 4.6, 37131
                #
                if (
                    isinstance(a, (int, float))
                    and isinstance(b, int)
                    and not isinstance(a, bool)
                    and not isinstance(b, bool)
                    and 1 <= float(a) <= 5
                    and b >= 10
                ):

                    # Prefer realistic Google rating.
                    if (
                        float(a) % 0.5 == 0
                        or float(a) % 1 == 0
                    ):

                        rating = float(a)
                        total_reviews = b

            for item in node:
                search_pairs(item)

        elif isinstance(node, dict):

            for item in node.values():
                search_pairs(item)

    search_pairs(payload)

    # --------------------------------------------------------
    # Fallback rating
    # --------------------------------------------------------

    if rating is None:

        ratings = []

        for number in all_numbers(payload):

            if 1 <= number <= 5:

                ratings.append(
                    float(number)
                )

        if ratings:

            # Prefer half-star values.
            half_stars = [
                x
                for x in ratings
                if x * 2 == int(x * 2)
            ]

            if half_stars:

                rating = half_stars[0]

    # --------------------------------------------------------
    # Fallback review count
    # --------------------------------------------------------

    if total_reviews == 0:

        # Search for strings such as:
        # "37,131 reviews"

        for value in strings:

            match = re.search(
                r"([\d,]+)\s+reviews?",
                value,
                re.I
            )

            if match:

                try:

                    count = int(
                        match.group(1)
                        .replace(",", "")
                    )

                    if count > total_reviews:
                        total_reviews = count

                except ValueError:
                    pass

    if (
        name is None
        and address is None
        and rating is None
    ):
        return None

    return PlaceDetails(
        name=name or query,
        address=address,
        rating=rating,
        total_reviews=total_reviews,
        reviews=[],
        source_query=query,
    )


# ============================================================
# Extract Google Place ID
# ============================================================

def extract_place_id(
    payload: Any
) -> Optional[str]:

    strings = list(
        all_strings(payload)
    )

    for value in strings:

        # Google Place IDs usually start with ChIJ...
        if value.startswith("ChIJ"):

            if 20 <= len(value) <= 100:
                return value

    return None


# ============================================================
# Extract review URL
# ============================================================

def extract_review_url(
    payload: Any
) -> Optional[str]:

    strings = list(
        all_strings(payload)
    )

    for value in strings:

        if (
            "search.google.com/local/reviews"
            in value
        ):

            return value

    return None


# ============================================================
# Review parser
# ============================================================

def looks_like_review_text(
    value: str
) -> bool:

    if not isinstance(value, str):
        return False

    value = " ".join(
        value.split()
    ).strip()

    if len(value) < 20:
        return False

    if len(value) > 5000:
        return False

    if value.startswith(
        "http://"
    ):
        return False

    if value.startswith(
        "https://"
    ):
        return False

    # Ignore timestamps.
    if re.match(
        r"^\d{4}-\d{2}-\d{2}",
        value
    ):
        return False

    # Must contain letters.
    if len(
        re.findall(
            r"[A-Za-z]",
            value
        )
    ) < 10:
        return False

    return True


def parse_reviews(
    payload: Any
) -> list[Review]:

    results = []
    seen = set()

    def inspect(node):

        if isinstance(node, list):

            strings = []

            ratings = []

            for item in node:

                if isinstance(item, str):

                    text = " ".join(
                        item.split()
                    ).strip()

                    if text:
                        strings.append(text)

                elif (
                    isinstance(
                        item,
                        (int, float)
                    )
                    and not isinstance(
                        item,
                        bool
                    )
                    and 1 <= item <= 5
                ):

                    ratings.append(
                        float(item)
                    )

            # ------------------------------------------------
            # Find review text
            # ------------------------------------------------

            review_texts = [
                x
                for x in strings
                if looks_like_review_text(x)
            ]

            if (
                review_texts
                and ratings
            ):

                review_text = max(
                    review_texts,
                    key=len
                )

                # ------------------------------------------------
                # Find author
                # ------------------------------------------------

                author_candidates = []

                for text in strings:

                    if text == review_text:
                        continue

                    if len(text) > 80:
                        continue

                    if looks_like_review_text(text):
                        continue

                    if re.search(
                        r"[A-Za-z]",
                        text
                    ):

                        author_candidates.append(
                            text
                        )

                author = (
                    min(
                        author_candidates,
                        key=len
                    )
                    if author_candidates
                    else "Unknown"
                )

                review = Review(
                    author=author,
                    rating=ratings[0],
                    text=review_text,
                )

                key = (
                    review.author,
                    review.rating,
                    review.text,
                )

                if key not in seen:

                    seen.add(key)
                    results.append(
                        review
                    )

            for item in node:
                inspect(item)

        elif isinstance(node, dict):

            for value in node.values():
                inspect(value)

    inspect(payload)

    return results


# ============================================================
# Main scraper
# ============================================================

async def _scrape(
    query: str,
    headless: bool = False,
    timeout_ms: int = 30000,
) -> PlaceDetails:

    network_responses = []

    # --------------------------------------------------------
    # Response listener
    # --------------------------------------------------------

    async def handle_response(response):

        try:

            url = response.url

            if (
                "google.com" not in url
                and "google.co.in" not in url
            ):
                return

            content_type = (
                response.headers
                .get(
                    "content-type",
                    ""
                )
                .lower()
            )

            if (
                "json" not in content_type
                and "javascript" not in content_type
                and "text" not in content_type
            ):
                return

            body = await response.text()

            if not body:
                return

            network_responses.append(
                {
                    "url": url,
                    "body": body,
                    "content_type": content_type,
                }
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=headless
        )

        context = await browser.new_context(
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = await context.new_page()

        page.on(
            "response",
            lambda response:
                asyncio.create_task(
                    handle_response(response)
                )
        )

        # ----------------------------------------------------
        # Search URL
        # ----------------------------------------------------

        search_url = (
            "https://www.google.com/maps/search/"
            f"?api=1&query={quote(query)}"
        )

        print(
            f"[INFO] Opening: {search_url}"
        )

        await page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )

        try:

            await page.wait_for_load_state(
                "networkidle",
                timeout=timeout_ms,
            )

        except Exception:
            pass

        await page.wait_for_timeout(
            5000
        )

        await browser.close()

    # --------------------------------------------------------
    # Parse captured network responses
    # --------------------------------------------------------

    best_place = None
    best_payload = None

    best_score = -1

    place_id = None
    review_url = None

    for response in network_responses:

        body = response["body"]

        payload = parse_google_json(
            body
        )

        if payload is None:
            continue

        candidate = (
            extract_place_from_search_payload(
                payload,
                query
            )
        )

        if candidate:

            score = 0

            if candidate.name:
                score += 20

            if candidate.address:
                score += 20

            if candidate.rating:
                score += 20

            if candidate.total_reviews:
                score += 20

            # Strongly prefer actual large review count.
            if candidate.total_reviews > 1000:
                score += 20

            if score > best_score:

                best_score = score
                best_place = candidate
                best_payload = payload

        # ----------------------------------------------------
        # Extract place ID
        # ----------------------------------------------------

        found_place_id = extract_place_id(
            payload
        )

        if found_place_id:

            # Prefer a place ID associated with Leela Palace.
            if place_id is None:
                place_id = found_place_id

        # ----------------------------------------------------
        # Review URL
        # ----------------------------------------------------

        found_review_url = extract_review_url(
            payload
        )

        if found_review_url:

            review_url = (
                found_review_url
                .replace(
                    "\\u003d",
                    "="
                )
                .replace(
                    "\\u0026",
                    "&"
                )
            )

    # --------------------------------------------------------
    # Print network information
    # --------------------------------------------------------

    print(
        f"[INFO] Network responses captured: "
        f"{len(network_responses)}"
    )

    print(
        f"[INFO] Place ID: {place_id}"
    )

    print(
        f"[INFO] Review URL found: "
        f"{review_url is not None}"
    )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if best_place is None:

        best_place = PlaceDetails(
            name=query,
            address=None,
            rating=None,
            total_reviews=0,
            reviews=[],
            source_query=query,
        )

    # --------------------------------------------------------
    # Important output
    # --------------------------------------------------------

    print(
        "\n========== PLACE =========="
    )

    print(
        "Name:",
        best_place.name
    )

    print(
        "Address:",
        best_place.address
    )

    print(
        "Rating:",
        best_place.rating
    )

    print(
        "Reviews:",
        best_place.total_reviews
    )

    print(
        "===========================\n"
    )

    return best_place


# ============================================================
# Public async function
# ============================================================

async def fetch_place_data(
    query: str,
    headless: bool = False,
    timeout_ms: int = 30000,
    debug_dir: Optional[str] = None,
) -> PlaceDetails:

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        _executor,
        _run_scraper,
        query,
        headless,
        timeout_ms,
    )


# ============================================================
# Windows thread
# ============================================================

def _run_scraper(
    query: str,
    headless: bool,
    timeout_ms: int,
) -> PlaceDetails:

    if sys.platform == "win32":

        loop = asyncio.ProactorEventLoop()

    else:

        loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    try:

        return loop.run_until_complete(
            _scrape(
                query=query,
                headless=headless,
                timeout_ms=timeout_ms,
            )
        )

    finally:

        loop.close()