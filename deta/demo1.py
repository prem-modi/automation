import os
import re
import time
import json
import random
import logging
import requests

from typing import Any, List, Dict
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup
from moviepy import VideoFileClip

from dotenv import load_dotenv
load_dotenv()

ERROR_LOG = os.getenv('COMMON_ERROR_LOG')

# ——— Logging setup ———
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s] [Payngo Product Details] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
ch.setFormatter(formatter)
logger.addHandler(ch)

fh = logging.FileHandler(ERROR_LOG, encoding='utf-8')
fh.setLevel(logging.ERROR)
fh.setFormatter(formatter)
logger.addHandler(fh)

# === Configuration ===
DOMAIN                      = os.getenv('PAYNGO_DOMAIN')
PAYNGO_HOME_PAGE            = os.getenv('PAYNGO_HOME_PAGE')
BASE_DIRECTORY              = os.getenv('PAYNGO_BASE_DIRECTORY')
SAVE_NEW_SERVER_TASK_PATH   = os.getenv('PAYNGO_SAVE_NEW_SERVER_TASK_PATH')
STORE_NAME                  = os.getenv('PAYNGO_STORE_NAME')
IMAGE_DIR                   = os.getenv('COMMON_SAVE_IMAGE_DIRECTORY_PATH')
VIDEO_DIR                   = os.getenv('COMMON_SAVE_VIDEO_DIRECTORY_PATH')

IMAGE_NAME_PREFIX      = os.getenv('PAYNGO_IMAGE_NAME_PREFIX')
MORE_IMAGE_NAME_PREFIX = os.getenv('PAYNGO_MORE_IMAGE_NAME_PREFIX')
VIDEO_NAME_PREFIX      = os.getenv('PAYNGO_VIDEO_NAME_PREFIX')

IMAGE_PREFIX_PATH      = os.getenv('COMMON_SAVE_IMAGE_DIRECTORY_PUBLIC_PATH_PREFIX')
VIDEO_PREFIX_PATH      = os.getenv('COMMON_SAVE_VIDEO_DIRECTORY_PUBLIC_PATH_PREFIX')

EMAIL                  = os.getenv('COMMON_EMAIL')
PASSWORD               = os.getenv('COMMON_PASSWORD')
AUTH_URL               = os.getenv('COMMON_AUTH_URL')
CHECK_VIDEO_EXISTS_URL = os.getenv('COMMON_CHECK_VIDEO_EXISTS_URL')
SAVE_NEW_SERVER_TASK_FOR_SAVE_PRODUCT_URL = os.getenv('COMMON_SAVE_NEW_SERVER_TASK_FOR_SAVE_PRODUCT_URL')
COMPLETE_TASK_URL = os.getenv('COMMON_COMPLETE_TASK_URL')

USER_AGENTS = json.loads(os.getenv('COMMON_USER_AGENTS'))

WAIT_MIN          = int(os.getenv('PAYNGO_WAIT_MIN'))
WAIT_MAX          = int(os.getenv('PAYNGO_WAIT_MAX')) 
DETAIL_RETRIES    = int(os.getenv('PAYNGO_DETAIL_RETRIES'))
TIMEOUT_CALL      = int(os.getenv('PAYNGO_TIMEOUT_CALL'))
RETRY_DELAY       = int(os.getenv('PAYNGO_RETRY_DELAY'))
PRODUCT_DETAILS_FILE_NAME = os.getenv('PAYNGO_PRODUCT_DETAILS_FILE_NAME')


def random_wait():
    delay = random.uniform(WAIT_MIN, WAIT_MAX)
    logger.info(f"Delaying for {delay:.2f}s")
    time.sleep(delay)


def get_headers(referer: str = None) -> Dict[str, str]:
    h = {"User-Agent": random.choice(USER_AGENTS)}
    if referer:
        h["Referer"] = referer
    return h


def normalize_link(base: str, href: str) -> str:
    href = href.split("?", 1)[0]
    return urljoin(base, href)


def normalize_url(src: str) -> str:
    if not src:
        return src
    src = src.strip()
    return src if src.startswith("http") else DOMAIN + (src if src.startswith("/") else "/" + src)


def extract_all_product_links(category_url: str) -> List[str]:
    logger.info(f"Extracting product links from category: {category_url}")
    seen, all_links = set(), []
    page = 1

    while True:
        url = category_url if page == 1 else f"{category_url}?p={page}"
        logger.info(f"[Page {page}] GET {url}")

        try:
            r = requests.get(url, headers=get_headers(referer=DOMAIN), timeout=TIMEOUT_CALL)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            logger.exception("Failed to fetch or parse page %s (page %d). Returning collected links so far.", url, page)
            return all_links

        # collect product links
        try:
            new_on_page = 0
            for a in soup.select("a.product-item-link"):
                href = a.get("href")
                if href:
                    link = normalize_link(url, href)
                    if link not in seen:
                        seen.add(link)
                        all_links.append(link)
                        new_on_page += 1

            logger.info(f"  → Found {new_on_page} new links on page {page}")
        except Exception:
            logger.exception("Error while parsing product links on %s — returning collected links so far", url)
            return all_links

        random_wait()
        if new_on_page == 0:
            break
        page += 1

    logger.info(f"Extracted {len(all_links)} unique product URLs")
    return all_links


def get_product_details(url: str) -> Dict[str, Any]:
    logger.info(f"Scraping details: {url}")
    product_url = url
    r = requests.get(url, headers=get_headers(referer=DOMAIN), timeout=TIMEOUT_CALL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    random_wait()

    # Title
    title_el = soup.select_one("h1.page-title .base")
    title    = title_el.get_text(strip=True) if title_el else ""

    price = ""
    oldPrice = ""

    # Final Price
    final_el = soup.select_one("div.final-price span.price")
    if final_el:
        raw = final_el.get_text(strip=True).replace("\u202f", "").replace("\xa0", "").replace("‏", "")
        m = re.search(r"([\d.,]+)", raw)
        if m:
            price = m.group(1).replace(",", "").replace(" ", "")

    # Old Price
    old_el = soup.select_one("div.old-price span.price")
    if old_el:
        raw = old_el.get_text(strip=True).replace("\u202f", "").replace("\xa0", "").replace("‏", "")
        m = re.search(r"([\d.,]+)", raw)
        if m:
            oldPrice = m.group(1).replace(",", "").replace(" ", "")

    # Images
    images = []
    gallery = soup.find("div", attrs={"aria-live": "polite"}, class_="relative")
    if gallery:
        seen = set()
        for img in gallery.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy")
            if not src:
                srcset = img.get("srcset")
                if srcset:
                    src = srcset.split(",")[0].strip().split(" ")[0]
            if not src:
                continue
            if not (src.startswith("http") or src.startswith("/")):
                continue
            nurl = normalize_url(src)
            if nurl and nurl not in seen:
                seen.add(nurl)
                images.append(nurl)

    # Description panel (used for more_images + short_desc)
    desc_panel = (
        soup.find("div", attrs={"x-show": re.compile(r"activeTab\s*===\s*'description'")})
        or soup.find("div", id="product-description")
        or soup.select_one("div.product.attribute.overview .value")
        or soup.find("div", class_="prose")
    )

    # more_images — prefer description tab images
    more_images, seen_more = [], set()
    if desc_panel:
        prose = desc_panel.find("div", class_="prose") or desc_panel
        for img in prose.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy")
            if not src:
                srcset = img.get("srcset")
                if srcset:
                    src = srcset.split(",")[0].strip().split(" ")[0]
            if not src:
                continue
            if isinstance(src, str) and (src.startswith(":") or src.strip().startswith("image.") or "imageSource" in src):
                continue
            if not (isinstance(src, str) and (src.startswith("http") or src.startswith("/"))):
                continue
            nurl = normalize_url(src)
            if nurl and nurl not in seen_more:
                seen_more.add(nurl)
                more_images.append(nurl)

    # Short description (paragraph texts)
    short_desc = []
    if desc_panel:
        prose = desc_panel.find("div", class_="prose") or desc_panel
        short_desc = [p.get_text(" ", strip=True) for p in prose.find_all("p")]

    # Videos
    videos, desc = [], soup.find("div", {"x-show": "activeTab === 'description'"})
    if desc:
        for tag in desc.find_all(["video", "source", "iframe"], src=True):
            videos.append(normalize_url(tag["src"]))

    # Raw specs
    raw_specs = []
    for row in soup.select("div#product-attributes table.additional-attributes tr"):
        k_el, v_el = row.select_one("th"), row.select_one("td")
        if not (k_el and v_el):
            continue
        raw_key = k_el.get_text(" ", strip=True)
        raw_key = re.sub(r'[:\uFE55\uFF1A]+\s*$', '', raw_key).strip()
        raw_val = v_el.get_text(" ", strip=True)
        raw_specs.append({"key": raw_key, "value": raw_val})

    # skuNumber
    skuNumber, model = "", ""
    sku_div = soup.select_one("div.product-sku")
    if sku_div:
        for span in sku_div.find_all("span"):
            text = span.get_text(strip=True)
            if text.startswith("מק"):
                skuNumber = re.sub(r"\D", "", text)
                break
        dspan = sku_div.find("span", string=re.compile(r"^דגם"))
        if dspan:
            model = re.sub(r"^דגם\s*", "", dspan.get_text(strip=True))

    # Brand
    brand = next((sp["value"] for sp in raw_specs if sp["key"].startswith("מותג")), "")

    # Filtered specifications
    specifications = [
        sp for sp in raw_specs
        if not any(sp["key"].startswith(pref) for pref in ('מק"ט', 'דגם', 'מותג'))
    ]

    # Logo
    logo_el = soup.select_one("div.m-logo img")
    logo_url = normalize_url(logo_el["src"]) if logo_el and logo_el.has_attr("src") else ""

    # Information tab
    information = []
    info_panel = soup.find(
        "div",
        attrs={"x-show": re.compile(r"activeTab\s*===\s*'product\.info\.tab_important_information'")}
    )
    if info_panel:
        for el in info_panel.find_all(["p", "li"]):
            txt = el.get_text(" ", strip=True)
            if txt:
                information.append(txt)

    # Terms & conditions
    terms = []
    panel = soup.find(
        "div",
        attrs={"x-show": re.compile(r"activeTab\s*===\s*'product\.info\.tab_additional_conditions'")}
    )
    if panel:
        for el in panel.find_all(["p", "div"]):
            t = el.get_text(" ", strip=True)
            if t:
                terms.append(t)
        if not terms:
            all_t = panel.get_text(" ", strip=True)
            if all_t:
                terms = [all_t]

    # Convert lists to strings
    description_str = ", ".join(short_desc) if short_desc else ""
    information_str = ", ".join(information) if information else ""
    terms_str       = ", ".join(terms) if terms else ""

    # Product number
    productNumber = ""
    try:
        path = unquote(urlparse(product_url).path or "")
        m = re.search(r'/(\d+)(?:\.html)?$', path) or re.search(r'(\d+)(?:\.html)?', path)
        if m:
            productNumber = m.group(1)
    except Exception:
        productNumber = ""

    return {
        "productNumber": productNumber,
        "url":           product_url,
        "shortDescription": title,
        "brand":         brand,
        "model":         model,
        "skuNumber":     skuNumber,
        "price":         price,
        "images":        images,
        "moreImages":    more_images,
        "videos":        videos,
        "specifications": specifications,
        "logoUrl":       logo_url,
        "description":   description_str,
        "information":   information_str,
        "termsAndConditions": terms_str,
        "currency":      "NIS"
    }



def scrape_with_retries(url: str) -> Dict[str, Any]:
    last_exc = None
    for i in range(1, DETAIL_RETRIES + 1):
        try:
            return get_product_details(url)
        except Exception as e:
            logger.error(f"Attempt {i} failed: {e}")
            last_exc = e
            time.sleep(RETRY_DELAY)
    raise last_exc


def get_auth_token() -> str:
    while True:
        try:
            r = requests.post(
                AUTH_URL,
                json={"email": EMAIL, "password": PASSWORD},
                timeout=TIMEOUT_CALL
            )
            r.raise_for_status()
            token = r.json()["data"]["accessToken"]
            logger.info("Obtained auth token.")
            return token
        except Exception as e:
            logger.error(f"Auth error: {e}, retrying in 2 minutes...")
            time.sleep(120)


def check_video_exists(token: str, url: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        try:
            r = requests.get(
                CHECK_VIDEO_EXISTS_URL,
                headers=headers,
                params={"url": url},
                timeout=TIMEOUT_CALL
            )
            r.raise_for_status()
            d = r.json()
            return {"exists": bool(d.get("exists")), "salezVideo": d.get("salezVideo")}
        except Exception as e:
            logger.error(f"Check exists error: {e}, retrying in 2 minutes...")
            time.sleep(120)


def download_images(product_url: str, image_urls: List[str], prefix: str, output_dir: str) -> List[Dict[str, str]]:
    os.makedirs(output_dir, exist_ok=True)
    pid = re.search(r"/(\d+)\.html", product_url).group(1)
    out = []
    for idx, src in enumerate(image_urls, 1):
        ext = os.path.splitext(src.split("?", 1)[0])[1] or ".jpg"
        name = f"{prefix}{pid}_{idx}{ext}"
        path = os.path.join(output_dir, name)
        logger.info(f"→ Download image {idx}/{len(image_urls)}: {name}")
        try:
            r = requests.get(src, headers=get_headers(referer=product_url), timeout=TIMEOUT_CALL, stream=True)
            r.raise_for_status()
            with open(path, "wb") as f:
                for c in r.iter_content(1024):
                    f.write(c)
            out.append({"sourceImage": src, "salezImage": IMAGE_PREFIX_PATH + name})
        except Exception as e:
            logger.error(f"Image failed: {e}")
        random_wait()
    return out


def download_videos(product_url: str, video_urls: List[str]) -> List[Dict[str, str]]:
    os.makedirs(VIDEO_DIR, exist_ok=True)
    pid = re.search(r"/(\d+)\.html", product_url).group(1)
    token = get_auth_token()
    payload = []

    for idx, src in enumerate(video_urls, 1):
        logger.info(f"→ Processing video {idx}/{len(video_urls)}: {src}")
        chk = check_video_exists(token, src)
        if chk["exists"]:
            logger.info(f"→ Exists on server, using {chk['salezVideo']}")
            payload.append({"sourceVideo": src, "salezVideo": chk["salezVideo"]})
            random_wait()
            continue

        ext = os.path.splitext(src.split("?", 1)[0])[1].lower() or ".mp4"
        raw = f"{VIDEO_NAME_PREFIX}{pid}_{idx}{ext}"
        rawpath = os.path.join(VIDEO_DIR, raw)
        try:
            logger.info(f"→ Downloading {src} → {raw}")
            r = requests.get(src, headers=get_headers(referer=product_url), timeout=TIMEOUT_CALL, stream=True)
            r.raise_for_status()
            with open(rawpath, "wb") as f:
                for c in r.iter_content(8192):
                    f.write(c)

            final_name = raw
            if ext == ".webm":
                mp4 = raw.replace(".webm", ".mp4")
                mp4path = os.path.join(VIDEO_DIR, mp4)
                logger.info(f"→ Converting {raw} → {mp4}")
                clip = VideoFileClip(rawpath)
                clip.write_videofile(mp4path, codec="libx264", audio_codec="aac")
                clip.close()
                os.remove(rawpath)
                final_name = mp4

            payload.append({"sourceVideo": src, "salezVideo": VIDEO_PREFIX_PATH + final_name})
            logger.info(f"✔ Video saved and payload entry created: {final_name}")
        except Exception as e:
            logger.error(f"→ Video download/convert failed for {src}: {e}")
            raise
        finally:
            random_wait()

    return payload


def flatten_media(item: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in item.items() if k not in ("images", "moreImages", "videos")}
    salez_imgs = [d["salezImage"] for d in item.get("images", [])]
    out["images"] = ", ".join(salez_imgs)
    src_imgs = [d["sourceImage"] for d in item.get("images", [])]
    out["sourceImages"] = ", ".join(src_imgs)
    salez_more = [d["salezImage"] for d in item.get("moreImages", [])]
    out["moreImages"] = ", ".join(salez_more)
    src_more = [d["sourceImage"] for d in item.get("moreImages", [])]
    out["sourceMoreImages"] = ", ".join(src_more)
    salez_vids = [d["salezVideo"] for d in item.get("videos", [])]
    out["videos"] = ", ".join(salez_vids)
    src_vids = [d["sourceVideo"] for d in item.get("videos", [])]
    out["sourceVideos"] = ", ".join(src_vids)
    return out


def flatten_specs(item: Dict[str, Any]) -> Dict[str, Any]:
    out = item.copy()
    specs = item.get("specifications", [])
    for idx, spec in enumerate(specs, start=1):
        out[f"key{idx}"]   = spec["key"]
        out[f"value{idx}"] = spec["value"]
    out.pop("specifications", None)
    return out


def save_new_server_task_for_save_product_function(payload_dict: Dict[str, Any], timeout_seconds: int = TIMEOUT_CALL) -> Dict[str, Any]:
    reqs = payload_dict.get("requests", [])
    t    = payload_dict.get("type")
    if not reqs or not t:
        raise ValueError("Must supply 'requests' list and 'type'")

    token = get_auth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"requests": reqs, "type": t}

    while True:
        try:
            resp = requests.post(
                SAVE_NEW_SERVER_TASK_FOR_SAVE_PRODUCT_URL,
                json=body,
                headers=headers,
                timeout=timeout_seconds
            )
            resp.raise_for_status()
            logger.info("save new server task request succeeded: %s", resp.json())
            return resp.json()
        except Exception as e:
            logger.error("Error posting new server task request: %s — retrying in 2 minutes...", e)
            time.sleep(120)


def complete_task(task_id: str, failed_count: int, success_count: int, error_log: Any = None, files: List[str] = None, timeout_seconds: int = TIMEOUT_CALL) -> Dict[str, Any]:
    """
    1. Get a bearer token via get_auth_token()
    2. POST to COMPLETE_TASK_URL with payload:
       { task, failedCount, successCount, errorLog, files }
    3. Retry infinitely on error (2-minute delay).
    """
    while True:
        try:
            token = get_auth_token()
            logger.info("Access token obtained for complete_task.")

            payload = {
                "task": task_id,
                "failedCount": failed_count,
                "successCount": success_count,
                "errorLog": error_log or {},
                "files": files or []
            }
            logger.info(f"Complete Task payload: {json.dumps(payload, ensure_ascii=False)}")

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            resp = requests.post(
                COMPLETE_TASK_URL,
                json=payload,
                headers=headers,
                timeout=timeout_seconds
            )
            logger.info(f"Complete-task status: {resp.status_code}")
            logger.info(f"Complete-task response payload: {resp.json()}")
            resp.raise_for_status()
            logger.info("Complete-task API call succeeded.")
            return resp.json()

        except Exception as e:
            logger.error(f"Error in complete_task: {e}")
            logger.info(f"Retrying complete_task in 120s…")
            time.sleep(120)


def main(data):
    task_id = data.get("_id")
    scrapPrinciple = data.get("scrapPrinciple")
    task_categories = scrapPrinciple.get("categories")

    logger.info("Starting task: %s", task_id)
    logger.info("Categories to process: %s", [c.get("categorySlug") for c in (task_categories or [])])

    for category in task_categories:
        category_name = category["categorySlug"]
        category_url = category["categoryLink"]
        category_name_hebrue = category["categoryName"]

        logger.info("Processing category '%s' -> %s -> %s", category_name, category_url, category_name_hebrue)
      
        # 1) Prepare output directory & file
        output_dir = os.path.join(BASE_DIRECTORY, STORE_NAME, category_name)
        try:
            os.makedirs(output_dir, exist_ok=True)
            logger.debug("Ensured output directory exists: %s", output_dir)
        except Exception:
            logger.exception("Failed to ensure output directory: %s", output_dir)
            # continue to the next category (preserve original behaviour of not changing flow)
        
        output_file = os.path.join(output_dir, PRODUCT_DETAILS_FILE_NAME)
        logger.info("Output file for this category: %s", output_file)

        # 2) Clear old data
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            logger.info("Cleared old data in %s", output_file)
        except Exception:
            logger.exception("Failed to clear or create output file: %s", output_file)

        # 3) Scrape each product and append to JSON
        try:
            links = extract_all_product_links(category_url)
            logger.info("Extracted %d product links from category '%s'.", len(links) if links is not None else 0, category_name)
        except Exception:
            links = []
            logger.exception("Failed to extract product links from %s", category_url)

        for i, url in enumerate(links, 1):
            logger.info("=== [%d/%d] %s ===", i, len(links), url)
            try:
                details = scrape_with_retries(url)
                # logger.info("Raw Product details for %s:\n%s", url, json.dumps(details, ensure_ascii=False, indent=2))
                
                # Skip if productNumber is missing or empty
                if not details.get("productNumber"):
                    logger.warning("Skipping product at %s because productNumber is missing", url)
                    continue

                imgs = download_images(url, details["images"], IMAGE_NAME_PREFIX, IMAGE_DIR)
                more = download_images(url, details["moreImages"], MORE_IMAGE_NAME_PREFIX, IMAGE_DIR)
                vids = download_videos(url, details["videos"])

                # assemble & flatten
                final = {**details, "images": imgs, "moreImages": more, "videos": vids}
                flat = flatten_media(final)
                flat = flatten_specs(flat)

                 # 🔹 Add categorySlug + categoryName to each product object
                flat["categorySlug"] = category_name
                flat["categoryName"] = category_name_hebrue
                flat["categoryLink"] = category_url

                # logger.info("Formatted product details for %s:\n%s", url, json.dumps(flat, ensure_ascii=False, indent=2))

                # append to PRODUCT_DETAILS_FILE_NAME
                try:
                    with open(output_file, "r+", encoding="utf-8") as f:
                        arr = json.load(f)
                        arr.append(flat)
                        f.seek(0)
                        json.dump(arr, f, ensure_ascii=False, indent=2)
                        f.truncate()
                    logger.info("Saved product to %s (product %d/%d)", output_file, i, len(links))
                except Exception:
                    logger.exception("Failed to append product to %s for URL %s", output_file, url)

            except Exception:
                # preserve original behaviour: log error and continue
                logger.exception("Error processing %s", url)

            random_wait()

        logger.info("All products saved to %s", output_file)

        # 4) Build NFS-style path and fire one zap request
        nfs_path = output_file.replace(BASE_DIRECTORY, SAVE_NEW_SERVER_TASK_PATH).replace("\\", "/")
        save_new_server_task_payload = {
            "requests": [
                {"path": nfs_path, "websiteAddress": PAYNGO_HOME_PAGE}
            ],
            "type": "product"
        }
        logger.info("Prepared save_new_server_task_payload for %s", nfs_path)
        logger.info("save_new_server_task_payload content: %s", json.dumps(save_new_server_task_payload, ensure_ascii=False))
        
        if save_new_server_task_payload:
            try:
                save_new_server_task_for_save_product_function(save_new_server_task_payload)
                logger.info("New server task added for products.json at %s", nfs_path)
            except Exception:
                logger.exception("Failed to add new server task request for %s", nfs_path)

    # Call complete task API (preserving original success/failure logic)
    failed = 0
    success = len(task_categories)  # kept as original: number of categories
    logger.info("Reporting completion: task_id=%s failed=%d success=%d", task_id, failed, success)
    try:
        complete_resp = complete_task(task_id=task_id, failed_count=failed, success_count=success, error_log={}, files=[])
        logger.info("Task completion response: %s", complete_resp)
    except Exception:
        logger.exception("Failed to call complete_task for %s", task_id)
