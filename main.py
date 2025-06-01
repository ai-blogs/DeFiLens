import os
import random
import time
import requests
import google.generativeai as genai
from google.api_core import exceptions
from dotenv import load_dotenv
import json

# --- IMPORTS FOR OAuth CLIENT ID (USER CREDENTIALS) ---
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
# --- END OAuth IMPORTS ---

# Original imports for Google Blogger API (build, HttpError)
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import re
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import base64
import logging
from datetime import datetime
import unicodedata
import platform

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('blog_creation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# IMPORTANT: How to run this script:
# 1. Ensure you have a .env file with API_KEYS (for local testing).
# 2. Before running main.py for the first time, run generate_token.py (from Part 2) to create token_blogger.json.
# 3. Install required libraries: pip install -r requirements.txt
# 4. Run from terminal: python crypto_blog_creator.py

# Load environment variables (for local testing)
load_dotenv()

# --- CONFIGURATION ---
# API Keys (from .env or GitHub Secrets)
NEWSAPI_API_KEY = os.getenv('NEWSAPI_API_KEY')
TOGETHER_API_KEY = os.getenv('TOGETHER_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Together AI Model Configuration
TOGETHER_DIFFUSION_MODEL = "black-forest-labs/FLUX.1-schnell-Free" # Specified by user

# Blog Content Configuration
CRYPTO_QUERY_TERM = "cryptocurrency" # The main topic for NewsAPI queries
BLOG_CATEGORY = "crypto" # The category for the blog posts (used for folder and labels)
NUM_SOURCE_ARTICLES_TO_FETCH = 100 # Increased to get a larger pool for multiple topics
NUM_BLOGS_TO_CREATE = 3
LANGUAGE = 'en' # For NewsAPI

# Image & Output Folders
BRANDING_LOGO_PATH = os.getenv('BRANDING_LOGO_PATH', None) # e.g., 'your_logo.png'
IMAGE_OUTPUT_FOLDER = "transformed_images"
BLOG_OUTPUT_FOLDER = "blog_drafts"

# --- BLOGGER AUTHENTICATION CONFIGURATION ---
BLOGGER_BLOG_ID = os.getenv('BLOGGER_BLOG_ID', '2306823784957718636') # Replace with your actual Blogger Blog ID, or set in .env/secrets.

# These will hold the JSON strings directly from GitHub Secrets OR be read from local files
GOOGLE_CLIENT_SECRETS_JSON = os.getenv('GOOGLE_CLIENT_SECRETS_JSON')
GOOGLE_OAUTH_TOKEN_JSON = os.getenv('GOOGLE_OAUTH_TOKEN_JSON')

# Define Blogger Scopes
BLOGGER_SCOPES = ['https://www.googleapis.com/auth/blogger']

# --- LLM Retry Configuration ---
LLM_MAX_RETRIES = 5
LLM_INITIAL_RETRY_DELAY_SECONDS = 5

# --- Enhanced font configuration with fallbacks ---
FONT_PATHS = {
    'mac': [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFProText-Regular.ttf"
    ],
    'windows': [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf"
    ],
    'linux': [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/arial.ttf", # Often present on Ubuntu
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    ]
}

def find_system_font():
    """Find the best available font for the current system"""
    system = platform.system().lower()

    if 'darwin' in system:
        font_list = FONT_PATHS['mac']
    elif 'windows' in system:
        font_list = FONT_PATHS['windows']
    else: # Assume Linux/Unix-like (GitHub Actions uses Ubuntu which is Linux)
        font_list = FONT_PATHS['linux']

    for font_path in font_list:
        if os.path.exists(font_path):
            logger.info(f"Using font: {font_path}")
            return font_path

    logger.warning("No suitable system fonts found, using PIL default. Text quality on images may be low.")
    return None

DEFAULT_FONT_PATH = find_system_font()

# Create necessary directories
for folder in [IMAGE_OUTPUT_FOLDER, BLOG_OUTPUT_FOLDER]:
    os.makedirs(folder, exist_ok=True)
    # For crypto blog, we'll just use one category folder
    os.makedirs(os.path.join(folder, BLOG_CATEGORY), exist_ok=True)

# Setup Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    RESEARCH_MODEL = genai.GenerativeModel('models/gemini-2.5-flash-preview-05-20')
    CONTENT_MODEL = genai.GenerativeModel('models/gemini-2.5-flash-preview-05-20')
else:
    logger.error("GEMINI_API_KEY not set. Gemini functions will not work.")
    RESEARCH_MODEL = None
    CONTENT_MODEL = None

# --- NEW/MODIFIED FUNCTION FOR OAuth CLIENT ID AUTHENTICATION ---
def get_blogger_oauth_credentials():
    """
    Obtains OAuth 2.0 credentials for Blogger API using client_secrets.json and token_blogger.json.
    Prioritizes environment variables (for CI/CD) then local files (for development).
    """
    creds = None
    CLIENT_SECRETS_FILE = 'client_secrets.json' # Local file name (for local testing)
    TOKEN_FILE = 'token_blogger.json' # Local file name (for local testing)

    # 1. Sabse pehle GitHub Secrets (Environment Variables) se load karne ki koshish karo
    if GOOGLE_OAUTH_TOKEN_JSON:
        try:
            token_info = json.loads(GOOGLE_OAUTH_TOKEN_JSON)
            creds = UserCredentials.from_authorized_user_info(token_info, BLOGGER_SCOPES)
            logger.info("INFO: Blogger OAuth token loaded from environment variable (GitHub Secret).")
        except json.JSONDecodeError as e:
            logger.error(f"ERROR: GOOGLE_OAUTH_TOKEN_JSON is not valid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"ERROR: Could not load Blogger OAuth token from env var: {e}")
            return None

    # Agar credentials valid hain lekin expired hain, toh refresh karne ki koshish karo
    if creds and creds.expired and creds.refresh_token:
        logger.info("INFO: Blogger OAuth token expired, attempting to refresh...")
        try:
            creds.refresh(Request())
            logger.info("INFO: Blogger OAuth token refreshed successfully.")
            # Important: If refreshed, the token_info might change (new expiry).
            # If running locally (not CI), you might want to save it back.
            if not os.getenv('CI'): # Check if not running in CI (e.g., GitHub Actions)
                with open(TOKEN_FILE, 'w') as token_file:
                    token_file.write(creds.to_json())
                logger.info(f"INFO: Refreshed Blogger OAuth token saved to '{TOKEN_FILE}'.")
        except Exception as e:
            logger.error(f"ERROR: Failed to refresh Blogger OAuth token: {e}. You might need to re-authenticate manually by deleting {TOKEN_FILE}.")
            creds = None

    # Agar koi valid credentials environment variable se nahi mile (ya refresh fail hua),
    # aur hum GitHub Actions (CI environment) mein nahi hain, toh local files aur interactive flow try karo.
    # 'CI' env var is usually 'true' in GitHub Actions. So, this block will be skipped in Actions.
    if not creds and not os.getenv('CI'):
        # Local token file se load karne ki koshish karo
        if os.path.exists(TOKEN_FILE):
            try:
                creds = UserCredentials.from_authorized_user_file(TOKEN_FILE, BLOGGER_SCOPES)
                logger.info(f"INFO: Blogger OAuth token loaded from local file '{TOKEN_FILE}'.")
            except Exception as e:
                logger.warning(f"WARNING: Could not load Blogger OAuth token from local file '{TOKEN_FILE}': {e}. Will re-authenticate.")
                creds = None

        # Agar ab bhi credentials nahi mile, toh local interactive OAuth flow initiate karo
        if not creds:
            # Client secrets ko environment variable se load karne ki koshish karo (agar .env mein set hain)
            # ya phir local client_secrets.json file se load karo.
            client_config_info = {}
            if GOOGLE_CLIENT_SECRETS_JSON: # Agar GOOGLE_CLIENT_SECRETS_JSON .env mein set hai
                try:
                    client_config_info = json.loads(GOOGLE_CLIENT_SECRETS_JSON)
                    logger.info("INFO: Client secrets loaded from environment variable (local .env).")
                except json.JSONDecodeError as e:
                    logger.critical(f"CRITICAL ERROR: GOOGLE_CLIENT_SECRETS_JSON in env is not valid JSON: {e}")
                    return None
            elif os.path.exists(CLIENT_SECRETS_FILE): # Agar .env mein nahi hai, toh local file try karo
                try:
                    with open(CLIENT_SECRETS_FILE, 'r') as f:
                        client_config_info = json.load(f)
                    logger.info(f"INFO: Client secrets loaded from local file '{CLIENT_SECRETS_FILE}'.")
                except Exception as e:
                    logger.critical(f"CRITICAL ERROR: Could not load client secrets from '{CLIENT_SECRETS_FILE}': {e}")
                    return None
            else:
                logger.critical(f"CRITICAL ERROR: No client secrets found (neither in GOOGLE_CLIENT_SECRETS_JSON env nor local '{CLIENT_SECRETS_FILE}'). Cannot perform OAuth flow.")
                return None


            logger.info(f"INFO: Initiating interactive OAuth flow for Blogger. Please follow browser instructions.")
            flow = InstalledAppFlow.from_client_config(client_config_info, BLOGGER_SCOPES)
            try:
                # Yeh browser kholega user interaction ke liye (GitHub Actions mein nahi chalega)
                creds = flow.run_local_server(port=0, prompt='consent', authorization_prompt_message='Please authorize this application to access your Blogger account.')
                with open(TOKEN_FILE, 'w') as token_file:
                    token_file.write(creds.to_json())
                logger.info(f"INFO: New token saved to '{TOKEN_FILE}'.")
            except Exception as e:
                logger.error(f"ERROR during local OAuth flow: {e}")
                return None

    if creds and creds.valid:
        logger.info("INFO: Valid Blogger OAuth credentials obtained successfully.")
    else:
        logger.error("ERROR: Could not obtain valid Blogger OAuth credentials. Posting to Blogger will likely fail.")
    return creds

def validate_environment():
    """Validate that all required environment variables and dependencies are set"""
    errors = []

    if not NEWSAPI_API_KEY:
        errors.append("NEWSAPI_API_KEY not found in environment variables.")

    if not TOGETHER_API_KEY:
        errors.append("TOGETHER_API_KEY not found in environment variables. Together AI functions will be skipped.")

    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY not found in environment variables. Gemini functions will be skipped.")

    if not BLOGGER_BLOG_ID or BLOGGER_BLOG_ID == 'YOUR_BLOG_ID_HERE':
        errors.append("BLOGGER_BLOG_ID not set or is placeholder. Cannot post to Blogger.")

    try:
        import PIL
        import google.generativeai
        from google.api_core import exceptions
        import requests
        import googleapiclient.discovery
        import google_auth_oauthlib.flow
        import google.oauth2.credentials
    except ImportError as e:
        errors.append(f"Missing required package: {e}. Please run 'pip install -r requirements.txt'.")

    if errors:
        for error in errors:
            logger.error(error)
        return False

    logger.info("Environment validation passed.")
    return True

def sanitize_filename(filename):
    """Create a safe filename from any string"""
    # Normalize unicode characters to their closest ASCII equivalents
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    # Replace invalid characters with underscore, then strip extra underscores/dashes at ends
    safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in filename).strip()
    safe_title = re.sub(r'[_ -]+', '_', safe_title).lower() # Ensure single underscores and lowercase
    return safe_title[:100] # Truncate to a reasonable length for file paths

def fetch_newsapi_articles(query, max_articles_to_fetch=50, max_retries=3):
    """Fetches articles from NewsAPI.org for a given query."""
    url = 'https://newsapi.org/v2/everything'
    params = {
        'q': query,
        'language': LANGUAGE,
        'sortBy': 'relevancy', # 'relevancy', 'popularity', 'publishedAt'
        'apiKey': NEWSAPI_API_KEY,
        'pageSize': max_articles_to_fetch
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"Fetching up to {max_articles_to_fetch} articles for '{query}' from NewsAPI (attempt {attempt + 1})...")
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            data = resp.json()
            articles = data.get('articles', [])

            if not articles:
                logger.warning(f"No articles found for query '{query}' from NewsAPI.org.")
                return []

            # NewsAPI articles often have 'content' ending with '[+N chars]'
            # We will rely on our aggregation/LLM to handle this.

            logger.info(f"Successfully fetched {len(articles)} articles for '{query}'.")
            return articles

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching articles for '{query}' (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"Failed to fetch articles for '{query}' after {max_retries} attempts")
                return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from NewsAPI.org: {e}")
            return []

def aggregate_articles(articles_list, category):
    """
    Aggregates data from multiple articles to create a consolidated view.
    For NewsAPI, 'content' field often truncated, so we focus on title/description.
    """
    if not articles_list:
        logger.warning(f"No articles provided for aggregation in category {category}.")
        return None

    consolidated_content = []
    consolidated_descriptions = []
    titles = []
    image_url = None # NewsAPI images not always reliable for featured image
    competitor_domains = set()
    primary_source_url_for_disclaimer = None

    # NewsAPI often truncates 'content', so prioritize titles and descriptions for AI input.
    # The image will be generated by HF, so `image_url` from source is less critical here.
    # We still want to get a `primary_source_url` for disclaimer purposes.

    for i, article in enumerate(articles_list):
        title = article.get('title', '')
        description = article.get('description', '')
        content = article.get('content', '') # This is often truncated
        source_url = article.get('url', '')
        article_image = article.get('urlToImage', '')
        source_name = article.get('source', {}).get('name', '')
        source_domain = source_url.replace('https://', '').replace('http://', '').split('/')[0] if source_url else ''

        if title and title != '[Removed]': titles.append(title)
        if description and description != '[Removed]': consolidated_descriptions.append(description)

        # Use title, description, and *if available and substantial* content for LLM input
        if title: consolidated_content.append(f"### Source: {title}\n\n")
        if description: consolidated_content.append(f"{description}\n")
        if content and content.strip() != '[Removed]' and len(content.strip()) > 50:
            consolidated_content.append(f"{content}\n")

        # Pick the first valid image URL for potential fallback or reference, though HF will generate the main one.
        if not image_url and article_image:
            image_url = article_image
            primary_source_url_for_disclaimer = source_url

        if source_domain:
            competitor_domains.add(source_domain)

    # Fallback if no primary source URL could be determined from articles with images
    if not primary_source_url_for_disclaimer and articles_list:
        primary_source_url_for_disclaimer = articles_list[0].get('url', 'https://news.example.com/source-unavailable')

    # A generic consolidated topic for the aggregator, which will be overridden by trending topic extraction
    consolidated_topic = titles[0] if titles else f"Recent Cryptocurrency News"
    if len(titles) > 1:
        consolidated_topic = f"Comprehensive Crypto: {titles[0]} and more..."
        if len(consolidated_topic) > 150:
            consolidated_topic = consolidated_topic[:150] + "..."

    if not consolidated_descriptions:
        consolidated_descriptions.append(f"A deep dive into recent developments in {category}.")

    return {
        "consolidated_topic": consolidated_topic,
        "combined_content": "\n\n---\n\n".join(consolidated_content) if consolidated_content else "No substantial content found from sources. AI will generate based on topic.",
        "combined_description": " ".join(consolidated_descriptions)[:300].strip(),
        "image_url": image_url, # This will be ignored in main workflow as HF generates
        "competitors": list(competitor_domains),
        "primary_source_url": primary_source_url_for_disclaimer
    }

def _gemini_generate_content_with_retry(model, prompt, max_retries=LLM_MAX_RETRIES, initial_delay=LLM_INITIAL_RETRY_DELAY_SECONDS):
    """
    Helper function to call Gemini's generate_content with retry logic for transient errors.
    """
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            # Check for empty response or issues from the model's side
            if not response.text or response.text.strip() == "":
                logger.warning(f"Attempt {attempt + 1}: Gemini returned empty response. Retrying...")
                raise ValueError("Empty response from Gemini model.")

            return response
        except (
            exceptions.InternalServerError,
            exceptions.ResourceExhausted,
            exceptions.DeadlineExceeded,
            requests.exceptions.RequestException,
            ValueError
        ) as e:
            logger.warning(f"Attempt {attempt + 1} failed with error: {e}")
            if attempt < max_retries - 1:
                sleep_time = initial_delay * (2 ** attempt) + random.uniform(0, 2)
                logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Gemini API call failed after {max_retries} attempts.")
                raise # Re-raise the last exception if all retries fail

def extract_multiple_trending_topics(articles_list, num_topics=NUM_BLOGS_TO_CREATE):
    """
    Analyzes article titles and descriptions to identify multiple trending crypto topics.
    Uses RESEARCH_MODEL for semantic extraction.
    """
    if not RESEARCH_MODEL:
        logger.error("Research model not initialized. Cannot extract trending topics.")
        return ["Latest Cryptocurrency News"] * num_topics

    if not articles_list:
        logger.warning("No articles provided for trending topic extraction. Using fallback.")
        return ["Latest Cryptocurrency News"] * num_topics

    # Combine titles and descriptions for the LLM input
    text_to_analyze = ""
    for i, article in enumerate(articles_list):
        if i >= 50:  # Limit input to LLM to prevent context window overflow
            break
        title = article.get('title', '')
        description = article.get('description', '')
        if title and title != '[Removed]':
            text_to_analyze += f"Title: {title}\n"
        if description and description != '[Removed]':
            text_to_analyze += f"Description: {description}\n\n"

    if not text_to_analyze:
        logger.warning("No usable text for trending topic extraction. Using fallback.")
        return ["Latest Cryptocurrency News"] * num_topics

    prompt = (
        f"You are an expert crypto analyst. Given the following news headlines and summaries "
        f"from recent cryptocurrency news, identify the {num_topics} most distinct and trending "
        f"topics or themes. Each topic should be specific enough for a blog post but broad enough "
        f"to be trending. Return ONLY a JSON array of {num_topics} strings, each being a distinct topic.\n\n"
        f"Example format: [\"Bitcoin Halving Impact\", \"Ethereum ETF Developments\", \"DeFi Innovations\"]\n\n"
        f"News Articles:\n{text_to_analyze.strip()}\n\n"
        f"Topics:"
    )

    try:
        logger.info(f"Attempting to extract {num_topics} trending topics using RESEARCH_MODEL...")
        response = _gemini_generate_content_with_retry(RESEARCH_MODEL, prompt)
        
        # Try to parse the response as JSON
        try:
            topics = json.loads(response.text.strip())
            if isinstance(topics, list) and len(topics) >= num_topics:
                return topics[:num_topics]
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract topics from text
            topics = re.findall(r'"([^"]+)"', response.text)
            if len(topics) >= num_topics:
                return topics[:num_topics]
        
        logger.warning("Could not parse topics as expected. Using fallback topics.")
        return ["Latest Cryptocurrency News"] * num_topics

    except Exception as e:
        logger.error(f"Failed to extract trending topics using RESEARCH_MODEL: {e}. Falling back to generic topics.")
        return ["Latest Cryptocurrency News"] * num_topics

def filter_articles_by_topic(articles, topic):
    """
    Filters articles to find those most relevant to a specific topic.
    Returns a list of articles sorted by relevance to the topic.
    """
    if not RESEARCH_MODEL:
        return articles[:10]  # Fallback to first 10 articles if no model available

    # Create a prompt to score article relevance
    prompt = (
        f"Given the topic '{topic}', analyze these articles and return a JSON array of indices "
        f"of the most relevant articles (0-based), sorted by relevance. Return ONLY the array.\n\n"
        f"Articles:\n" + "\n".join([f"{i}. {a.get('title', '')}" for i, a in enumerate(articles)])
    )

    try:
        response = _gemini_generate_content_with_retry(RESEARCH_MODEL, prompt)
        relevant_indices = json.loads(response.text.strip())
        if isinstance(relevant_indices, list):
            return [articles[i] for i in relevant_indices if i < len(articles)]
    except Exception as e:
        logger.error(f"Failed to filter articles for topic '{topic}': {e}")

    return articles[:10]  # Fallback to first 10 articles

def generate_image_from_hf(prompt_text, max_retries=3, initial_delay=5):
    """
    Generates an image using Together AI's FLUX model via its API.
    Returns raw image bytes.
    """
    if not TOGETHER_API_KEY:
        logger.error("TOGETHER_API_KEY is not set. Cannot generate image.")
        return None

    api_url = "https://api.together.xyz/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Format the prompt for FLUX model
    formatted_prompt = f"{prompt_text} --ar 16:9"
    
    payload = {
        "model": TOGETHER_DIFFUSION_MODEL,
        "prompt": formatted_prompt,
        "n": 1,
        "size": "1024x576"  # 16:9 aspect ratio
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"Generating image from Together AI model '{TOGETHER_DIFFUSION_MODEL}' (attempt {attempt + 1})...")
            response = requests.post(api_url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()

            # Parse the response
            result = response.json()
            if 'data' in result and len(result['data']) > 0:
                image_url = result['data'][0]['url']
                
                # Download the image
                image_response = requests.get(image_url, timeout=30)
                image_response.raise_for_status()
                
                logger.info("Image successfully generated by Together AI.")
                return image_response.content
            else:
                logger.error(f"Together AI API returned unexpected response format: {result}")
                raise ValueError("Together AI API did not return a valid image URL.")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1} failed during Together AI image generation: {e}")
            if attempt < max_retries - 1:
                sleep_time = initial_delay * (2 ** attempt) + random.uniform(0, 2)
                logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Failed to generate image from Together AI after {max_retries} attempts.")
                return None
        except Exception as e:
            logger.error(f"Unexpected error during Together AI image generation: {e}", exc_info=True)
            return None

def enhance_image_quality(img):
    """Apply advanced image enhancement techniques."""
    # Convert to RGB if not already, to ensure consistent processing for JPEG saving
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Apply subtle enhancements
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(1.2) # Sharpen slightly

    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.1) # Increase contrast slightly

    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.05) # Boost color saturation a bit

    # Apply a subtle unsharp mask effect for perceived sharpness
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=150, threshold=3))

    return img

def create_text_with_shadow(draw, position, text, font, text_color, shadow_color, shadow_offset):
    """Draw text with shadow for better visibility."""
    x, y = position
    shadow_x, shadow_y = shadow_offset

    # Draw shadow
    draw.text((x + shadow_x, y + shadow_y), text, font=font, fill=shadow_color)
    # Draw main text
    draw.text((x, y), text, font=font, fill=text_color)

def find_content_bbox_and_trim(img, tolerance=20, border_colors_to_trim=((0,0,0), (255,255,255))):
    """
    Attempts to find the bounding box of non-border content pixels and trims the image.
    Considers black and white as potential uniform border colors.
    Increased tolerance for slight variations in border color.
    """
    if img.mode != 'RGB':
        img = img.convert('RGB')

    width, height = img.size
    pixels = img.load() # Get pixel access for speed

    def is_similar(pixel1, pixel2, tol):
        """Checks if two pixels are similar within a given tolerance."""
        return all(abs(c1 - c2) <= tol for c1, c2 in zip(pixel1, pixel2))

    def is_border_pixel_group(pixel):
        """Checks if a pixel is similar to any of the specified border colors."""
        return any(is_similar(pixel, bc, tolerance) for bc in border_colors_to_trim)

    # Find top
    top = 0
    for y in range(height):
        if not all(is_border_pixel_group(pixels[x, y]) for x in range(width)):
            top = y
            break

    # Find bottom
    bottom = height
    for y in range(height - 1, top, -1):
        if not all(is_border_pixel_group(pixels[x, y]) for x in range(width)):
            bottom = y + 1
            break

    # Find left
    left = 0
    for x in range(width):
        if not all(is_border_pixel_group(pixels[x, y]) for y in range(height)):
            left = x
            break

    # Find right
    right = width
    for x in range(width - 1, left, -1):
        if not all(is_border_pixel_group(pixels[x, y]) for y in range(height)):
            right = x + 1
            break

    if (left, top, right, bottom) != (0, 0, width, height):
        # Ensure that after trimming, a reasonable amount of content remains
        min_content_ratio = 0.75 # Ensure at least 75% of original width/height remains after trim
        trimmed_width = right - left
        trimmed_height = bottom - top
        if trimmed_width > (width * min_content_ratio) and \
           trimmed_height > (height * min_content_ratio):
            logger.info(f"Automatically trimmed detected uniform borders from original image. BBox: ({left}, {top}, {right}, {bottom})")
            return img.crop((left, top, right, bottom))
        else:
            logger.debug(f"Trimming borders would remove too much content ({trimmed_width}/{width} or {trimmed_height}/{height}). Skipping trim.")

    logger.debug("No significant uniform color borders detected in original image for trimming.")
    return img

def transform_image(image_input_bytes, title_text, category_text, output_category_folder, safe_filename):
    """
    Processes, and adds branding/text to an image provided as bytes.
    Saves the image to disk and returns its file path and Base64 encoded string.
    Returns (relative_file_path, base64_data_uri) or (None, None) on failure.
    """
    if not image_input_bytes:
        logger.info("No image bytes provided for transformation. Skipping image processing.")
        return None, None

    output_full_path = None
    base64_data_uri = None

    try:
        logger.info(f"Processing image bytes for title: {title_text[:70]}...")

        # Load image directly from bytes
        img = Image.open(BytesIO(image_input_bytes))

        # Convert to RGB for consistent processing and JPEG saving. If there's an alpha channel,
        # create a white background, otherwise just convert.
        if img.mode in ('RGBA', 'LA', 'P'):
            alpha = img.split()[-1] if img.mode in ('RGBA', 'LA') else None
            background = Image.new('RGB', img.size, (255, 255, 255))
            if alpha: # Paste with alpha mask
                background.paste(img, mask=alpha)
            else: # Just paste if no alpha or if 'P' mode without alpha
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # --- STEP 1: Automatically trim uniform borders (letterboxing/pillarboxing) from the source image ---
        img = find_content_bbox_and_trim(img)

        # Target dimensions for the *visual content* of the blog featured image (16:9 aspect ratio)
        target_content_width = 1200
        target_content_height = 675
        target_aspect = target_content_width / target_content_height

        # --- STEP 2: Resize and Crop to fill 16:9 (Object-Fit: Cover equivalent) ---
        original_width, original_height = img.size
        original_aspect = original_width / original_height

        if original_aspect > target_aspect:
            resize_height = target_content_height
            resize_width = int(target_content_height * original_aspect)
        else:
            resize_width = target_content_width
            resize_height = int(target_content_width / original_aspect)

        img = img.resize((resize_width, resize_height), Image.Resampling.LANCZOS)

        left_crop = (resize_width - target_content_width) // 2
        top_crop = (resize_height - target_content_height) // 2
        img = img.crop((left_crop, top_crop, left_crop + target_content_width, top_crop + target_content_height))

        # --- STEP 3: Apply image enhancements to the 16:9 content ---
        img = enhance_image_quality(img)

        # Convert to RGBA for drawing elements
        img = img.convert('RGBA')

        # --- STEP 4: Create a clean, dynamically-extended bottom area for text with gradient ---
        extended_area_height = int(target_content_height * 0.25)
        final_canvas_height = target_content_height + extended_area_height
        final_canvas_width = target_content_width

        new_combined_img = Image.new('RGBA', (final_canvas_width, final_canvas_height), (0, 0, 0, 255))
        new_combined_img.paste(img, (0, 0))

        strip_from_original_height = int(target_content_height * 0.05)
        if strip_from_original_height > 0:
            bottom_strip_for_extension = img.crop((0, target_content_height - strip_from_original_height, target_content_width, target_content_height))
            stretched_strip = bottom_strip_for_extension.resize((target_content_width, extended_area_height), Image.Resampling.BICUBIC)
            new_combined_img.paste(stretched_strip, (0, target_content_height))
            logger.info("Extended bottom of image with stretched content for seamless look.")

        gradient_overlay_image = Image.new('RGBA', new_combined_img.size, (0, 0, 0, 0))
        draw_gradient = ImageDraw.Draw(gradient_overlay_image)
        gradient_top_y_on_canvas = target_content_height
        for y_relative_to_extended_area in range(extended_area_height):
            alpha = int(255 * (y_relative_to_extended_area / extended_area_height) * 0.95)
            absolute_y_on_canvas = gradient_top_y_on_canvas + y_relative_to_extended_area
            draw_gradient.line([(0, absolute_y_on_canvas), (final_canvas_width, absolute_y_on_canvas)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(new_combined_img, gradient_overlay_image)
        draw = ImageDraw.Draw(img)


        # --- STEP 5: Add Custom Branding (Logo) - Positioned in TOP-RIGHT ---
        if BRANDING_LOGO_PATH and os.path.exists(BRANDING_LOGO_PATH):
            try:
                logo = Image.open(BRANDING_LOGO_PATH).convert("RGBA")
                logo_height = int(target_content_height * 0.08)
                logo_width = int(logo.width * (logo_height / logo.height))
                logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

                padding = int(target_content_width * 0.02)
                logo_x = target_content_width - logo_width - padding
                logo_y = padding

                logo_overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                logo_overlay.paste(logo, (logo_x, logo_y), logo)
                img = Image.alpha_composite(img, logo_overlay)
                logger.info("Branding logo applied successfully.")
            except Exception as e:
                logger.error(f"Error applying branding logo: {e}")

        # --- STEP 6: Add Title Text (bottom right corner, on extended area) ---
        selected_font = ImageFont.load_default()
        title_font_size = max(int(target_content_height * 0.035), 20)

        if DEFAULT_FONT_PATH:
            try:
                selected_font = ImageFont.truetype(DEFAULT_FONT_PATH, title_font_size)
            except (IOError, OSError) as e:
                logger.warning(f"Could not load specified font '{DEFAULT_FONT_PATH}': {e}. Falling back to PIL default.")
        else:
            logger.warning("No default font path specified. Using PIL default font. Text quality on images may be basic.")

        draw = ImageDraw.Draw(img)

        max_text_width_for_title = int(target_content_width * 0.45)
        horizontal_padding_text = int(target_content_width * 0.02)

        def get_wrapped_text_lines(text, font, max_width):
            """Wraps text to fit within a given maximum width."""
            lines = []
            if not text: return lines
            words = text.split()
            if not words: return lines

            current_line = words[0]
            for word in words[1:]:
                test_line = f"{current_line} {word}".strip()
                try:
                    bbox = font.getbbox(test_line)
                    text_width = bbox[2] - bbox[0]
                except AttributeError:
                    text_width = font.getsize(test_line)[0]

                if text_width <= max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
            return lines

        wrapped_title_lines = get_wrapped_text_lines(title_text, selected_font, max_text_width_for_title)

        total_text_height_for_placement = 0
        line_height_list = []
        for line in wrapped_title_lines:
            try:
                bbox = selected_font.getbbox(line)
                line_height = bbox[3] - bbox[1]
                line_height_list.append(line_height + int(title_font_size * 0.2))
            except AttributeError:
                line_height_list.append(title_font_size + 3)

        total_text_height_for_placement = sum(line_height_list)

        bottom_align_y_coord = final_canvas_height - horizontal_padding_text
        current_y_text_draw = bottom_align_y_coord - total_text_height_for_placement

        min_y_for_text = target_content_height + horizontal_padding_text
        if current_y_text_draw < min_y_for_text:
            current_y_text_draw = min_y_for_text

        for i, line in enumerate(wrapped_title_lines):
            try:
                bbox = selected_font.getbbox(line)
                line_width = bbox[2] - bbox[0]
            except AttributeError:
                line_width = selected_font.getsize(line)[0]

            x_text_draw = target_content_width - horizontal_padding_text - line_width

            create_text_with_shadow(
                draw, (x_text_draw, current_y_text_draw), line, selected_font,
                (255, 255, 255, 255), (0, 0, 0, 180), (2, 2)
            )
            current_y_text_draw += line_height_list[i]

        output_filename = f"{safe_filename}_{int(time.time())}.jpg"
        output_full_path = os.path.join(IMAGE_OUTPUT_FOLDER, output_category_folder, output_filename)

        final_img_for_save = img.convert('RGB')

        buffer = BytesIO()
        final_img_for_save.save(buffer, format='JPEG', quality=85, optimize=True)
        image_bytes_output = buffer.getvalue() # Renamed to avoid clash with input `image_input_bytes`

        base64_encoded_image = base64.b64encode(image_bytes_output).decode('utf-8')
        base64_data_uri = f"data:image/jpeg;base64,{base64_encoded_image}"

        with open(output_full_path, 'wb') as f:
            f.write(image_bytes_output)

        logger.info(f"Transformed image saved to disk: {output_full_path}")
        logger.info(f"Transformed image Base64 encoded.")
        return output_full_path, base64_data_uri

    except IOError as e:
        logger.error(f"Error processing image bytes: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error during image transformation: {e}", exc_info=True)
        return None, None

def perform_research_agent(target_topic, competitors):
    """
    Acts as the 'Research Agent'. Uses Gemini to find SEO keywords and outline suggestions.
    Outputs a JSON string.
    """
    if not RESEARCH_MODEL:
        logger.error("Research model not initialized. Skipping research agent.")
        return None

    prompt = (
        f"You are an expert SEO Keyword Research Agent specializing in crypto market analysis and content strategy. "
        f"Your task is to perform comprehensive SEO keyword research and outline generation for the trending crypto topic: '{target_topic}'.\n\n"
        f"Analyze content from top crypto competitors (e.g., {', '.join(competitors[:5])}) to identify relevant SEO keywords, content gaps, and structural insights "
        f"specifically tailored for the cryptocurrency, blockchain, DeFi, NFT, and Web3 space.\n\n"
        f"**Crucial:** Based on the topic, original source information, and keyword research, generate a **unique, catchy, and SEO-optimized blog post title (H1)** that will attract crypto enthusiasts and rank well. This title should be distinct from the original source titles and reflect a consolidated, in-depth perspective on the crypto topic.\n\n"
        "## Process Flow:\n"
        "1.  **Initial Keyword Discovery:** Identify primary (high search volume, high relevance), secondary (long-tail, specific), and diverse keyword clusters related to the target crypto topic. Think about various user intents (informational, commercial, navigational) within the crypto domain.\n"
        "2.  **Competitive Analysis:** Provide 2-3 key insights into competitor strategies and content gaps in relation to the crypto topic.\n"
        "3.  **Keyword Evaluation:** Assess search volume and competition levels for identified keywords. Prioritize high-value, relevant crypto keywords for SEO optimization. Identify important related entities and concepts within the crypto sphere.\n"
        "4.  **Outline Creation:** Generate a detailed, hierarchical blog post outline (using markdown headings `##`, `###`) that strategically incorporates the high-value keywords. Ensure the outline flows logically and covers comprehensive aspects of the crypto topic. Suggest potential sub-sections for FAQs, case studies, or data points where appropriate.\n\n"
        "## Output Specifications:\n"
        "Generate a JSON object (as a string) with the following structure. Ensure the `blog_outline` is a valid markdown string.\n"
        "```json\n"
        "{{\n"
        "  \"suggested_blog_title\": \"Your Unique and Catchy Crypto Blog Post Title Here\",\n"
        "  \"primary_keywords\": [\"crypto keyword1\", \"crypto keyword2\", \"crypto keyword3\"],\n"
        "  \"secondary_keywords\": {{\"sub_topic1_crypto\": [\"long-tail A\", \"long-tail B\"], \"sub_topic2_crypto\": [\"specific C\", \"specific D\"]}},\n"
        "  \"competitor_insights\": \"Summary of competitor strategies and content gaps in the crypto niche.\",\n"
        "  \"blog_outline\": \"## Introduction to Crypto Topic\\n\\n### The Rise of [Specific Crypto Niche]\\n\\n## Main Section 1: [Crypto Section Title]\\n\\n### Sub-section 1.1: [Specific Crypto Aspect]\\n\\n## Conclusion\\n\"\n"
        "}}\n"
        "```\n"
        "**Constraints:** Focus on commercially relevant crypto terms. Exclude branded competitor terms. The entire output must be a single, valid JSON string. The `blog_outline` must contain at least 8 distinct markdown headings (H2 or H3) and be structured for user engagement and SEO. The `suggested_blog_title` should be concise, impactful, and ideally under 70 characters. Do NOT include any introductory or concluding remarks outside the JSON block."
    )
    try:
        logger.info(f"Generating research for: '{target_topic[:70]}...'")
        response = _gemini_generate_content_with_retry(RESEARCH_MODEL, prompt)

        json_match = re.search(r'```json\s*(.*?)\s*```', response.text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            research_data = json.loads(json_str)
            logger.info("Research generation successful.")
            return research_data
        else:
            logger.warning(f"Could not find valid JSON in markdown block for '{target_topic}'. Attempting to parse raw response.")
            try:
                research_data = json.loads(response.text.strip())
                logger.info("Research generation successful (parsed raw response).")
                return research_data
            except json.JSONDecodeError:
                logger.error(f"Failed to parse research response as JSON for '{target_topic}'. Raw response:\n{response.text[:500]}...")
                return None

    except (json.JSONDecodeError, ValueError, requests.exceptions.RequestException, exceptions.InternalServerError, exceptions.ResourceExhausted, exceptions.DeadlineExceeded) as e:
        logger.error(f"Research Agent generation failed or JSON parsing/content validation failed for '{target_topic}': {e}.")
        return None
    except Exception as e:
        logger.error(f"Research Agent generation failed for '{target_topic}': {e}", exc_info=True)
        return None

def generate_content_agent(consolidated_article_data, research_output, transformed_image_filepath):
    """
    Acts as the 'Content Generator Agent'. Uses Gemini to write the blog post
    based on aggregated source data and research output.
    """
    if not CONTENT_MODEL:
        logger.error("Content model not initialized. Skipping content generation.")
        return None

    image_path_for_prompt = transformed_image_filepath if transformed_image_filepath else "None"

    primary_keywords_str = ', '.join(research_output.get('primary_keywords', []))
    secondary_keywords_str = ', '.join([kw for sub_list in research_output.get('secondary_keywords', {}).values() for kw in sub_list])

    new_blog_title = research_output.get('suggested_blog_title', consolidated_article_data.get('consolidated_topic', 'Default Consolidated Crypto Blog Title'))

    logger.info(f"Using primary keywords for content generation: {primary_keywords_str}")
    logger.info(f"Using secondary keywords for content generation: {secondary_keywords_str}")

    category = consolidated_article_data.get('category', BLOG_CATEGORY)
    primary_keywords = research_output.get('primary_keywords', [])
    secondary_keywords = []
    if research_output.get('secondary_keywords'):
        for sub_list in research_output.get('secondary_keywords', {}).values():
            secondary_keywords.extend(sub_list)

    logger.info("Preparing metadata for blog post:")
    logger.info(f"Title: {new_blog_title}")
    logger.info(f"Category: {category}")
    logger.info(f"Primary Keywords: {primary_keywords}")
    logger.info(f"Secondary Keywords: {secondary_keywords}")

    combined_content_for_prompt = consolidated_article_data.get('combined_content', '')
    if len(combined_content_for_prompt) > 4000:
        combined_content_for_prompt = combined_content_for_prompt[:4000] + "\n\n[...Content truncated for prompt brevity...]"
        logger.info(f"Truncated combined_content for prompt: {len(consolidated_article_data['combined_content'])} -> {len(combined_content_for_prompt)} characters.")

    consolidated_article_data_for_prompt = consolidated_article_data.copy()
    consolidated_article_data_for_prompt['combined_content'] = combined_content_for_prompt

    raw_description_for_prompt = consolidated_article_data.get(
        'combined_description',
        f'A comprehensive and insightful look at the latest news and trends in {BLOG_CATEGORY} related to {new_blog_title}.'
    )
    blog_description_for_prompt = raw_description_for_prompt.replace('"', '').replace('\n', ' ').replace('\r', ' ').strip()[:155]

    prompt = (
        f"You are a specialized Crypto Blog Writing Agent that transforms SEO research and aggregated article data "
        f"into comprehensive, publication-ready, SEO-optimized blog posts. You excel at creating in-depth, "
        f"authoritative content by synthesizing information from multiple sources, while maintaining reader engagement and SEO best practices "
        f"specifically for the cryptocurrency and blockchain industry.\n\n"
        f"## Input Requirements:\n"
        f"1.  `aggregated_source_data`: {json.dumps(consolidated_article_data_for_prompt, indent=2)}\n"
        f"2.  `research_output`: {json.dumps(research_output, indent=2)}\n"
        f"3.  `transformed_image_path_info`: '{image_path_for_prompt}' (This is the file path to the main featured image. Do NOT embed this image again within the content body. It will be handled separately in the HTML template.)\n\n"
        f"## Content Specifications:\n"
        f"-   **Word Count:** Aim for 2500-3000 words. Synthesize and expand thoughtfully on the `aggregated_source_data['combined_content']`, adding depth, specific (even if fabricated plausible) details, and related information from your training data relevant to crypto. Do NOT simply copy-paste content from the input. Rewrite and integrate.\n"
        f"-   **Heading Structure:** Use the provided outline (`research_output['blog_outline']`). Ensure a minimum of 25 headings (`##` and `###` only, except for the main H1 title), covering various aspects of the trending crypto topic.\n"
        f"-   **Paragraph Length:** Each paragraph should contain at least 5 sentences for comprehensive coverage, unless it's a short intro/outro or a bullet point explanation.\n"
        f"-   **Writing Style:** Professional yet conversational, engaging, and human-like for a crypto audience. Avoid jargon where simpler terms suffice. Do NOT mention that you are an AI or generated the content. Ensure a clear, authoritative, and trustworthy tone that positions the content as highly credible.\n"
        f"-   **Target Audience:** Broad audience interested in cryptocurrency, blockchain, DeFi, NFTs, and Web3.\n"
        f"-   **Keyword Integration:** Naturally weave `primary_keywords` ({primary_keywords_str}) and `secondary_keywords` ({secondary_keywords_str}) throughout the text without keyword stuffing. Integrate them into headings, subheadings, and body paragraphs.\n"
        f"-   **Content Expansion:** Elaborate significantly on the `aggregated_source_data['combined_content']` by adding specific details, explanations, and context, drawing from your extensive knowledge base. Emphasize synthesizing information from *all provided sources* to create a unique and comprehensive article.\n"
        f"-   **Data & Examples:** Incorporate relevant data, statistics, and real-world examples (even if not in original article, create plausible ones). Invent realistic numbers, dates, names, organizations, and project names where appropriate to enhance credibility within the crypto context. Ensure these details *support* the main points derived from the aggregated content. When inventing details or examples, ensure they are realistic and enhance the article's depth and plausibility.\n"
        f"-   **Linking:** Generate relevant external links where appropriate (e.g., `[CoinDesk Article](https://www.coindesk.com/article-about-topic)`). **Crucially, ensure these are actual, plausible URLs from reputable crypto domains related to the topic (e.g., 'cointelegraph.com/news', 'decrypt.co/defi', 'theblockcrypto.com/analysis', 'ethereum.org/roadmap', 'bitcoin.org/learn', 'opensea.io/blog'). Invent these URLs realistically and embed them naturally within the surrounding sentences. Do NOT use the `@` symbol or any other prefix before links or raw URLs. Do NOT include `example.com` or similar placeholder domains.** Also, generate **2-3 contextually relevant internal links** within the content, pointing to hypothetical related blog posts on your own crypto blog (e.g., `[Understanding DeFi Yield Farming](https://yourcryptoblog.com/2024/07/defi-yield-farming-explained.html)`, `[The Future of NFTs](https://yourcryptoblog.com/2024/07/future-of-nfts.html)`). These internal links should be naturally embedded within sentences and promote exploration of related content on your site.\n"
        f"-   **Image Inclusion:** Do NOT include any markdown `![alt text](image_path)` syntax for the featured image within the generated content body. The featured image is handled separately. Crucially, do NOT generate any `![alt text](image_path)` markdown for additional images within the content body. The single `featuredImage` is handled separately by the HTML template and should not be re-included.\n"
        f"## Output Structure:\n"
        f"Generate the complete blog post in markdown format. It must start with a metadata block followed by the blog content.\n\n"
        f"**Metadata Block (exact key-value pairs, no --- delimiters, newline separated):**\n"
        f"title: {new_blog_title}\n"
        f"description: {blog_description_for_prompt}\n"
        f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"categories: [{category}, {', '.join(primary_keywords[:2])}]\n"
        f"tags: [{', '.join(primary_keywords + secondary_keywords[:5])}]\n"
        f"featuredImage: {transformed_image_filepath if transformed_image_filepath else 'None'}\n\n"
        f"**Blog Content (following the metadata block):**\n"
        f"1.  **Main Title (H1):** Start with an H1 heading based on the provided `suggested_blog_title`. Example: `# {new_blog_title}`.\n"
        f"2.  **Introduction (2-3 paragraphs):** Hook the reader. Clearly state the problem or topic and your blog's value proposition.\n"
        f"3.  **Main Sections:** Follow the `blog_outline` from `research_output`. Expand each section (`##`) and sub-section (`###`). Ensure each section provides substantial information.\n"
        f"4.  **FAQ Section:** Include 5-7 frequently asked questions with detailed, comprehensive answers, related to the topic and incorporating keywords.\n"
        f"5.  **Conclusion:** Summarize key takeaways, provide a forward-looking statement, and a clear call-to-action.\n"
        f"Do NOT include any introductory or concluding remarks outside the blog content itself (e.g., 'Here is your blog post'). **Do NOT include any bracketed instructions (like `[mention this]`), placeholders (like `example.com`), or any comments intended for me within the output markdown. The entire output must be polished, final content, ready for publication.**"
    )

    try:
        logger.info(f"Generating full blog content for: '{new_blog_title[:70]}...'")
        response = _gemini_generate_content_with_retry(CONTENT_MODEL, prompt)

        content = response.text.strip()

        logger.info(f"--- Raw AI-generated Markdown Content (first 500 chars): ---\n{content[:500]}\n--- End Raw AI Markdown ---")
        logger.info(f"Full raw AI-generated Markdown content length: {len(content)} characters.")

        if not re.search(r"title:\s*.*\n.*?tags:\s*\[.*\]", content, re.DOTALL):
            logger.warning("Generated content appears to be missing the required metadata block!")
            content = (
                f"title: {new_blog_title}\n"
                f"description: {blog_description_for_prompt}\n"
                f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"categories: [{category}, {', '.join(primary_keywords[:2])}]\n"
                f"tags: [{', '.join(primary_keywords + secondary_keywords[:5])}]\n"
                f"featuredImage: {transformed_image_filepath if transformed_image_filepath else 'None'}\n\n"
                f"{content}"
            )
            logger.info("Added missing metadata block to content")

        content = clean_ai_artifacts(content)

        logger.info(f"--- Cleaned AI-generated Markdown Content (first 500 chars): ---\n{content[:500]}\n--- End Cleaned AI Markdown ---")

        logger.info("Content generation successful.")
        return content

    except Exception as e:
        logger.error(f"Content Agent generation failed for '{new_blog_title}': {e}", exc_info=True)
        return None

def clean_ai_artifacts(content):
    """Enhanced cleaning of AI-generated artifacts and placeholders."""
    # Remove any bracketed instructions/placeholders like [Some Text Here] or [Insert Link Here]
    content = re.sub(r'\[.*?\]', '', content)

    # Remove any stray @ symbols followed by words (e.g., @https, @email), likely from malformed links
    content = re.sub(r'\s*@\S+', '', content)

    # Remove example.com or similar placeholder URLs, both in markdown and raw URLs
    placeholder_domains = [
        'example.com', 'example.org', 'placeholder.com', 'yoursite.com',
        'website.com', 'domain.com', 'site.com', 'yourblogname.com', 'ai-generated.com',
        'yourcryptoblog.com', # Specific to crypto theme
        'example.org'
    ]
    for domain in placeholder_domains:
        # Markdown links like [text](https://www.example.com/path)
        content = re.sub(rf'\[[^\]]*\]\(https?://(?:www\.)?{re.escape(domain)}[^\)]*\)', '', content, flags=re.IGNORECASE)
        # Raw URLs like https://www.example.com/path
        content = re.sub(rf'https?://(?:www\.)?{re.escape(domain)}\S*', '', content, flags=re.IGNORECASE)

    # Remove any remaining AI comments or instructions that might slip through
    ai_patterns = [
        r'(?i)note:.*?(?=\n|$)',
        r'(?i)important:.*?(?=\n|$)',
        r'(?i)remember to.*?(?=\n|$)',
        r'(?i)please.*?(?=\n|$)',
        r'(?i)you should.*?(?=\n|$)',
        r'<!--.*?-->', # HTML comments
        r'/\*.*?\*/',   # CSS/JS comments
    ]
    for pattern in ai_patterns:
        content = re.sub(pattern, '', content, flags=re.DOTALL)

    # Clean up multiple consecutive blank lines to just two (for paragraph separation)
    content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)

    # Remove leading/trailing whitespace from each line
    content = '\n'.join([line.strip() for line in content.split('\n')])

    # Ensure consistent line endings
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    return content.strip()

def parse_markdown_metadata(markdown_content):
    """
    Parses metadata from the top of a markdown string.
    Expected format: key: value\nkey2: value2\n\n# Blog Title...
    Returns a dictionary of metadata and the remaining blog content.
    """
    metadata = {}
    lines = markdown_content.split('\n')
    content_start_index = 0

    logger.debug("Starting metadata parsing...")
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            content_start_index = i + 1
            logger.debug(f"Blank line found, metadata ends at line {i}. Content starts at {content_start_index}.")
            break
        if ':' in stripped_line:
            key, value = stripped_line.split(':', 1)
            metadata[key.strip()] = value.strip()
            logger.debug(f"Parsed metadata line: {key.strip()}: {value.strip()}")
        else:
            content_start_index = i
            logger.warning(f"Metadata block ended unexpectedly at line {i} with: '{stripped_line}'")
            break
    else:
        content_start_index = len(lines)
        logger.debug("No blank line found, assuming all content is metadata or empty after checking.")

    blog_content_only = '\n'.join(lines[content_start_index:]).strip()

    if blog_content_only.startswith('# '):
        h1_line_end = blog_content_only.find('\n')
        if h1_line_end != -1:
            h1_title = blog_content_only[2:h1_line_end].strip()
            if 'title' not in metadata:
                metadata['title'] = h1_title
            blog_content_only = blog_content_only[h1_line_end:].strip()
            logger.debug(f"Extracted H1 title: '{h1_title}'. Remaining content starts after H1.")
        else:
            h1_title = blog_content_only[2:].strip()
            if 'title' not in metadata:
                metadata['title'] = h1_title
            blog_content_only = ""
            logger.debug(f"Extracted H1 title (only line): '{h1_title}'. Content became empty.")

    logger.info(f"Final parsed metadata: {metadata}")
    logger.info(f"Blog content starts with: {blog_content_only[:100]}...")

    return metadata, blog_content_only

def markdown_to_html(markdown_text, main_featured_image_filepath=None, main_featured_image_b64_data_uri=None):
    """
    Converts a subset of Markdown to HTML.
    If main_featured_image_filepath and main_featured_image_b64_data_uri are provided,
    it will replace img src that matches main_featured_image_filepath with the Base64 URI.
    Includes cleanup for malformed example links and AI instructions.
    """
    html_text = markdown_text

    html_text = clean_ai_artifacts(html_text)

    html_text = re.sub(r'###\s*(.*)', r'<h3>\1</h3>', html_text)
    html_text = re.sub(r'##\s*(.*)', r'<h2>\1</h2>', html_text)
    html_text = re.sub(r'#\s*(.*)', r'<h1>\1</h1>', html_text)

    html_text = re.sub(r'\*\*\*(.*?)\*\*\*', r'<strong><em>\1</em></strong>', html_text)
    html_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_text)
    html_text = re.sub(r'_(.*?)_', r'<em>\1</em>', html_text)
    html_text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html_text)

    html_text = re.sub(r'^\s*([-*]|\d+\.)\s+(.*)$', r'<li>\2</li>', html_text, flags=re.MULTILINE)

    def wrap_lists(match):
        list_items_html = match.group(0)
        if re.search(r'<li>\s*\d+\.', list_items_html):
            return f'<ol>{list_items_html}</ol>'
        else:
            return f'<ul>{list_items_html}</ul>'

    html_text = re.sub(r'(<li>.*?</li>\s*)+', wrap_lists, html_text, flags=re.DOTALL)

    def image_replacer(match):
        alt_text = match.group(1)
        src_url = match.group(2)

        if main_featured_image_filepath and os.path.basename(src_url) == os.path.basename(main_featured_image_filepath):
            logger.info(f"Replacing markdown image link '{src_url}' with Base64 data URI for in-content display.")
            return f'<img src="{main_featured_image_b64_data_uri}" alt="{alt_text}" class="in-content-image">'
        else:
            escaped_alt_text = alt_text.replace('"', '"')
            return f'<img src="{src_url}" alt="{escaped_alt_text}" class="in-content-image">'

    html_text = re.sub(r'!\[(.*?)\]\((.*?)\)', image_replacer, html_text)

    html_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', html_text)

    lines = html_text.split('\n')
    parsed_lines = []
    current_paragraph_lines = []

    block_tags_re = re.compile(r'^\s*<(h\d|ul|ol|li|img|a|div|p|blockquote|pre|table|script|style|br)', re.IGNORECASE)

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            if current_paragraph_lines:
                para_content = ' '.join(current_paragraph_lines).strip()
                if para_content:
                    parsed_lines.append(f"<p>{para_content}</p>")
                current_paragraph_lines = []
            parsed_lines.append('')
        elif block_tags_re.match(stripped_line):
            if current_paragraph_lines:
                para_content = ' '.join(current_paragraph_lines).strip()
                if para_content:
                    parsed_lines.append(f"<p>{para_content}</p>")
                current_paragraph_lines = []
            parsed_lines.append(line)
        else:
            current_paragraph_lines.append(line)

    if current_paragraph_lines:
        para_content = ' '.join(current_paragraph_lines).strip()
        if para_content:
            parsed_lines.append(f"<p>{para_content}</p>")

    final_html_content = '\n'.join(parsed_lines)

    final_html_content = re.sub(r'<p>\s*</p>', '', final_html_content)
    final_html_content = re.sub(r'<p><br\s*/?></p>', '', final_html_content)
    final_html_content = re.sub(r'<h1>(.*?)</h1>', r'<h2>\1</h2>', final_html_content) # Ensure no H1 from content

    return final_html_content

def generate_enhanced_html_template(title, description, keywords, image_src_for_html_body,
                                  html_blog_content, category, article_url_for_disclaimer, published_date):
    """Generate enhanced HTML template with better styling and comprehensive SEO elements."""

    # Correct HTML escaping for attributes:
    escaped_title_html = title.replace('&', '&amp;').replace('"', '&quot;').replace("'", '&apos;')
    # Use the already escaped description
    escaped_description_html = description  # description is already escaped

    json_safe_title = json.dumps(title)[1:-1]
    json_safe_description = json.dumps(description)[1:-1]

    # For image_url_for_seo, we'll use a placeholder or the base64 if no public URL is available.
    # It's best practice for this to be a publicly accessible URL for crawlers.
    # Since we're using Base64, a public URL isn't readily available.
    # We will leave it blank for now, or you can manually update it in Blogger.
    image_url_for_seo = '' # Placeholder as we don't have a public URL for HF generated images yet

    structured_data = f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "NewsArticle",
      "headline": "{json_safe_title}",
      "image": {json.dumps([image_url_for_seo]) if image_url_for_seo else "[]"},
      "datePublished": "{published_date}T00:00:00Z",
      "dateModified": "{published_date}T00:00:00Z",
      "articleSection": "{category.capitalize()}",
      "author": {{
        "@type": "Organization",
        "name": "AI Crypto Insights"
      }},
      "publisher": {{
        "@type": "Organization",
        "name": "Your Crypto Blog Name",
        "logo": {{
          "@type": "ImageObject",
          "url": "{image_url_for_seo}"
        }}
      }},
      "mainEntityOfPage": {{
        "@type": "WebPage",
        "@id": "{article_url_for_disclaimer}"
      }},
      "description": "{json_safe_description}"
    }}
    </script>
    """

    html_styles = """
    <style>
        :root {
            --primary-color: #F7931A; /* Bitcoin Orange */
            --secondary-color: #1A222C; /* Dark Crypto feel */
            --text-color: #333;
            --light-bg: #F5F7FA;
            --card-bg: #ffffff;
            --border-color: #e0e0e0;
            --shadow-light: 0 4px 15px rgba(0,0,0,0.08);
            --shadow-hover: 0 6px 20px rgba(0,0,0,0.12);
        }

        body {
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.7;
            color: var(--text-color);
            background: var(--light-bg);
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        .container {
            max-width: 850px;
            margin: 30px auto;
            padding: 25px;
            background: var(--card-bg);
            border-radius: 12px;
            box-shadow: var(--shadow-light);
            transition: all 0.3s ease-in-out;
        }
        .container:hover {
            box-shadow: var(--shadow-hover);
        }

        .article-header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }

        .category-tag {
            display: inline-block;
            background: var(--primary-color);
            color: white;
            padding: 8px 18px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            letter-spacing: 0.8px;
            margin-bottom: 15px;
            text-transform: uppercase;
        }

        h1 {
            font-size: 2.2em;
            color: var(--secondary-color);
            margin-bottom: 15px;
            line-height: 1.3;
        }
        h2 {
            font-size: 1.7em;
            color: var(--secondary-color);
            margin-top: 30px;
            margin-bottom: 15px;
            padding-bottom: 5px;
            border-bottom: 1px dashed var(--border-color);
        }
        h3 {
            font-size: 1.3em;
            color: var(--secondary-color);
            margin-top: 25px;
            margin-bottom: 10px;
        }

        p {
            margin-bottom: 1.2em;
        }

        .featured-image {
            width: 100%;
            height: auto;
            max-height: 843.75px;
            object-fit: cover;
            border-radius: 8px;
            margin-top: 25px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .in-content-image {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 2em auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        a {
            color: var(--primary-color);
            text-decoration: none;
            transition: color 0.2s ease-in-out;
        }
        a:hover {
            color: #C27600; /* Darker Bitcoin Orange */
            text-decoration: underline;
        }

        ul, ol {
            margin-left: 25px;
            margin-bottom: 1.5em;
        }
        li {
            margin-bottom: 0.6em;
        }

        .source-link {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            font-size: 0.95em;
            text-align: center;
            color: #666;
        }

        @media (max-width: 768px) {
            .container {
                margin: 15px;
                padding: 15px;
            }
            h1 { font-size: 1.8em; }
            h2 { font-size: 1.5em; }
            h3 { font-size: 1.2em; }
            .category-tag { font-size: 0.8em; padding: 6px 14px; }
        }
    </style>
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title_html}</title>
    <meta name="description" content="{escaped_description_html}">
    <meta name="keywords" content="{keywords}">
    <meta name="robots" content="index, follow">
    <meta name="author" content="AI Crypto Insights">

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="article">
    <meta property="og:url" content="{article_url_for_disclaimer}">
    <meta property="og:title" content="{escaped_title_html}">
    <meta property="og:description" content="{escaped_description_html}">
    <meta property="og:image" content="{image_url_for_seo}">

    <!-- Twitter -->
    <meta property="twitter:card" content="summary_large_image">
    <meta property="twitter:url" content="{article_url_for_disclaimer}">
    <meta property="twitter:title" content="{escaped_title_html}">
    <meta property="twitter:description" content="{escaped_description_html}">
    <meta property="twitter:image" content="{image_url_for_seo}">

    {structured_data}
    {html_styles}
</head>
<body>
    <div class="container">
        <div class="article-header">
            <span class="category-tag">{category.upper()}</span>
            <h1>{title}</h1>
            {f'<img src="{image_src_for_html_body}" alt="{escaped_title_html}" class="featured-image">' if image_src_for_html_body else ''}
        </div>
        <div class="article-content">
            {html_blog_content}
        </div>
        <div class="source-link">
            <p><strong>Disclaimer:</strong> This article was generated by an AI content creation system, synthesizing information from multiple sources. It may contain fictional details and external links for illustrative purposes.</p>
            <p>A primary source contributing to this content can be found here: <a href="{article_url_for_disclaimer}" target="_blank" rel="noopener noreferrer">{article_url_for_disclaimer}</a></p>
        </div>
    </div>
</body>
</html>"""

def post_to_blogger(html_file_path, blog_id, blogger_user_credentials):
    """
    Posts a generated HTML blog to Blogger.
    """
    if not blogger_user_credentials or not blogger_user_credentials.valid:
        logger.error("Blogger User Credentials are not valid. Cannot post to Blogger.")
        return False

    try:
        blogger_service = build('blogger', 'v3', credentials=blogger_user_credentials)

        with open(html_file_path, 'r', encoding='utf-8') as f:
            full_html_content = f.read()

        logger.info("Starting metadata parsing from HTML file for Blogger post...")

        metadata_match = re.search(r"title:\s*(.*?)\n.*?tags:\s*\[(.*?)\]", full_html_content, re.DOTALL | re.IGNORECASE)
        post_title = "Generated Crypto Blog Post"
        post_labels = []

        if metadata_match:
            post_title = metadata_match.group(1).strip()
            tags_str = metadata_match.group(2).strip()
            post_labels = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
            logger.info(f"Found title: {post_title}, Tags: {post_labels}")

            categories_match = re.search(r"categories:\s*\[(.*?)\]", full_html_content, re.DOTALL | re.IGNORECASE)
            if categories_match:
                categories_str = categories_match.group(1).strip()
                parsed_categories = [cat.strip() for cat in categories_str.split(',') if cat.strip()]
                post_labels.extend(parsed_categories)
                logger.info(f"Categories found: {parsed_categories}")
                logger.info(f"Combined labels after adding categories: {post_labels}")
        else:
            logger.warning("Could not find metadata block in HTML content. Attempting to extract from H1...")
            h1_match = re.search(r'<h1>(.*?)</h1>', full_html_content, re.IGNORECASE | re.DOTALL)
            if h1_match:
                post_title = h1_match.group(1).strip()
                logger.info(f"Extracted title from H1: {post_title}")
            else:
                logger.warning("Could not find H1 tag either. Using default title.")

        post_labels = list(set([label.strip().lower() for label in post_labels if label.strip()]))
        if not post_labels:
            logger.warning("No labels found in metadata. Adding default labels based on title...")
            default_labels = [word.lower() for word in re.findall(r'\w+', post_title) if len(word) > 3]
            post_labels.extend(default_labels[:5])
        # Ensure 'crypto' label is always present
        if BLOG_CATEGORY not in post_labels:
            post_labels.append(BLOG_CATEGORY)
        logger.info(f"Final cleaned labels to send to Blogger: {post_labels}")

        post_body = {
            'kind': 'blogger#post',
            'blog': {'id': blog_id},
            'title': post_title,
            'content': full_html_content,
            'labels': post_labels,
            'status': 'LIVE'
        }
        logger.info(f"Preparing Blogger post with:")
        logger.info(f"Title: {post_title}")
        logger.info(f"Labels: {post_labels}")
        logger.info(f"Content length: {len(full_html_content)} characters")

        logger.info(f"Attempting to insert blog post to Blogger: '{post_title}' with labels: {post_labels}...")
        request = blogger_service.posts().insert(blogId=blog_id, body=post_body)
        response = request.execute()

        logger.info(f"✅ Successfully posted '{post_title}' to Blogger! Post ID: {response.get('id')}")
        logger.info(f"View live at: {response.get('url')}")
        response_labels = response.get('labels', [])
        logger.info(f"Blogger API Response labels: {response_labels}")

        if not response_labels:
            logger.warning("No labels found in Blogger API response. Labels may not have been set correctly.")
        elif set(response_labels) != set(post_labels):
            logger.warning(f"Labels mismatch! Sent: {post_labels}, Received: {response_labels}")

        return True

    except HttpError as e:
        error_content = e.content.decode('utf-8')
        logger.error(f"Failed to post to Blogger due to API error: {e}")
        logger.error(f"Error details: {error_content}")
        if "rateLimitExceeded" in error_content:
            logger.error("Blogger API rate limit exceeded. Consider reducing posting frequency.")
        elif "User lacks permission" in str(e) or "insufficient permission" in str(e).lower():
            logger.error("Blogger: User lacks permission to post. Ensure the authenticated Google account has Author/Admin rights on the target blog.")
        return False
    except Exception as e:
        logger.critical(f"An unexpected error occurred during Blogger posting: {e}", exc_info=True)
        return False


def save_blog_post(consolidated_topic_for_fallback, generated_markdown_content, category, transformed_image_filepath, transformed_image_b64, primary_source_url):
    """
    Saves the generated blog post in an HTML file with SEO elements.
    Accepts the *transformed_image_filepath* for SEO metadata and *transformed_image_b64* for inline HTML.
    `primary_source_url` is used for the disclaimer link.
    Returns the file path of the saved HTML blog.
    """
    metadata, blog_content_only_markdown = parse_markdown_metadata(generated_markdown_content)

    title = metadata.get('title', consolidated_topic_for_fallback)
    description_fallback = f"A comprehensive look at the latest news in {category} related to '{title}'."
    description = metadata.get('description', description_fallback).replace('"', '&quot;').replace('\n', ' ').strip()[:155].replace("'", '&apos;')

    keywords_from_meta = metadata.get('tags', '').replace(', ', ',').replace(' ', '_')
    if not keywords_from_meta:
        keywords = ','.join([category, 'crypto news', 'latest crypto', sanitize_filename(title)[:30]])
    else:
        keywords = keywords_from_meta.lower()

    image_src_for_html_body = transformed_image_b64 if transformed_image_b64 else ''

    # For image_url_for_seo, we'll use a placeholder or the base64.
    # For Blogger, the image will be embedded via Base64. A public URL for crawlers
    # would ideally come from Blogger's image hosting *after* upload, which isn't covered by this script.
    # Set to blank or a generic placeholder for now for structured data/OG tags.
    image_url_for_seo = '' # Placeholder as we don't have a public URL for HF generated images yet
    if image_src_for_html_body and not image_url_for_seo:
        logger.warning("For optimal SEO (og:image, twitter:image, JSON-LD), 'image_url_for_seo' should be a publicly accessible URL. Currently it is left blank as the script doesn't upload images to a public host.")
        logger.warning("You may need to manually update the og:image, twitter:image, and JSON-LD image URL in Blogger after publishing if you want external image SEO.")


    published_date = metadata.get('date', datetime.now().strftime('%Y-%m-%d'))

    html_blog_content = markdown_to_html(
        blog_content_only_markdown,
        main_featured_image_filepath=transformed_image_filepath,
        main_featured_image_b64_data_uri=transformed_image_b64
    )

    safe_title_for_file = sanitize_filename(title)

    folder = os.path.join(BLOG_OUTPUT_FOLDER, category)
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, f"{safe_title_for_file}.html")

    final_html_output = generate_enhanced_html_template(
        title, description, keywords, image_src_for_html_body,
        html_blog_content,
        category, primary_source_url, published_date
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(final_html_output)
    logger.info(f"✅ Saved blog post: {file_path}")
    return file_path


def main():
    blogger_oauth_credentials = None

    if not validate_environment():
        logger.error("Environment validation failed. Exiting.")
        return

    if BLOGGER_BLOG_ID and BLOGGER_BLOG_ID != 'YOUR_BLOG_ID_HERE':
        logger.info("\n--- Authenticating with Blogger using OAuth 2.0 ---")
        blogger_oauth_credentials = get_blogger_oauth_credentials()
        if not blogger_oauth_credentials:
            logger.critical("CRITICAL: Failed to obtain Blogger OAuth credentials. Cannot post to Blogger. Exiting.")
            return
        logger.info("--- Blogger OAuth Authentication Successful ---\n")
    else:
        logger.warning("INFO: BLOGGER_BLOG_ID not configured or is placeholder. Blogger posting will be skipped.")

    global_competitors = [
        "cointelegraph.com", "coindesk.com", "decrypt.co", "theblockcrypto.com",
        "binance.com/blog", "ethereum.org", "bitcoin.org", "forbes.com/crypto",
        "bloomberg.com/crypto", "cryptoslate.com", "blockworks.co", "investopedia.com/cryptocurrency"
    ]

    logger.info(f"\n--- Starting processing for {NUM_BLOGS_TO_CREATE} CRYPTO blogs with query: [{CRYPTO_QUERY_TERM.upper()}] ---")

    # 1. News Aggregation (NewsAPI) - Fetch larger pool of articles
    raw_articles = fetch_newsapi_articles(CRYPTO_QUERY_TERM, max_articles_to_fetch=NUM_SOURCE_ARTICLES_TO_FETCH)

    if not raw_articles:
        logger.info(f"No raw articles fetched for '{CRYPTO_QUERY_TERM}'. Skipping blog generation.")
        return

    # 2. Extract Multiple Trending Topics
    trending_topics = extract_multiple_trending_topics(raw_articles, NUM_BLOGS_TO_CREATE)
    current_category = BLOG_CATEGORY

    # Process each topic
    for topic_index, trending_topic in enumerate(trending_topics, 1):
        logger.info(f"\n--- Processing Blog {topic_index}/{NUM_BLOGS_TO_CREATE}: '{trending_topic}' ---")
        
        # Filter articles for this specific topic
        topic_articles = filter_articles_by_topic(raw_articles, trending_topic)
        
        # Aggregate articles for this topic
        consolidated_data = aggregate_articles(topic_articles, current_category)
        
        if not consolidated_data:
            logger.error(f"Failed to aggregate articles for topic '{trending_topic}'. Skipping this blog.")
            continue

        consolidated_data['consolidated_topic'] = trending_topic
        consolidated_topic = consolidated_data['consolidated_topic']
        consolidated_description = consolidated_data['combined_description']
        consolidated_content_for_ai = consolidated_data['combined_content']
        primary_source_url_for_disclaimer = consolidated_data['primary_source_url']
        effective_competitors = list(set(global_competitors + consolidated_data['competitors']))

        transformed_image_filepath = None
        transformed_image_b64 = None

        # 3. AI-Generated Image (Together AI FLUX Model)
        if TOGETHER_API_KEY:
            together_image_prompt = (
                f"A futuristic representation of {trending_topic} in the world of cryptocurrency, "
                f"digital art style, high contrast, vibrant colors, blockchain background, intricate details, "
                f"concept art, 8k"
            )
            together_image_bytes = generate_image_from_hf(together_image_prompt)

            if together_image_bytes:
                safe_image_filename = sanitize_filename(consolidated_topic)
                transformed_image_filepath, transformed_image_b64 = transform_image(
                    together_image_bytes,
                    consolidated_topic,
                    current_category,
                    current_category,
                    safe_image_filename
                )
            else:
                logger.warning(f"  Together AI image generation failed for topic '{trending_topic}'. Proceeding without a featured image.")
        else:
            logger.warning("  TOGETHER_API_KEY not set. Skipping Together AI image generation.")

        try:
            consolidated_article_data_for_ai = {
                "consolidated_topic": consolidated_topic,
                "combined_description": consolidated_description,
                "combined_content": consolidated_content_for_ai,
                "category": current_category,
                "original_image_source": "Together AI Generated"
            }

            # 4. Research Agent (Gemini Call 1)
            if GEMINI_API_KEY and RESEARCH_MODEL:
                research_output = perform_research_agent(consolidated_topic, effective_competitors)
                if not research_output:
                    logger.error(f"Failed to get research output for: '{consolidated_topic}'. Skipping this blog.")
                    continue

                logger.info(f"  Research successful. Suggested Title: '{research_output.get('suggested_blog_title', 'N/A')}'")
                logger.info(f"  Primary Keywords: {research_output.get('primary_keywords', [])}")

                # 5. Content Generator Agent (Gemini Call 2)
                generated_blog_markdown = generate_content_agent(
                    consolidated_article_data_for_ai,
                    research_output,
                    transformed_image_filepath
                )

                if not generated_blog_markdown:
                    logger.error(f"Failed to generate blog content for: '{consolidated_topic}'. Skipping this blog.")
                    continue
            else:
                logger.warning("GEMINI_API_KEY or RESEARCH_MODEL/CONTENT_MODEL is not initialized. Skipping AI content generation.")
                generated_blog_markdown = f"""title: {consolidated_topic}
description: {consolidated_description.replace('"', '&quot;').replace('\\n', ' ').strip()[:155].replace("'", '&apos;')}
date: {datetime.now().strftime('%Y-%m-%d')}
categories: [{current_category}]
tags: [{current_category}, news]
featuredImage: {transformed_image_filepath or 'None'}

# {consolidated_topic}

<p>This is a placeholder blog post because AI generation was skipped due to missing API key.</p>
<p>Original aggregated content details (first 500 chars): {consolidated_content_for_ai[:500]}...</p>
"""
                research_output = {
                    "primary_keywords": [],
                    "secondary_keywords": {},
                    "competitor_insights": "",
                    "blog_outline": "",
                    "suggested_blog_title": consolidated_topic
                }

            # 6. Save the blog post
            saved_html_file_path = save_blog_post(
                consolidated_topic,
                generated_blog_markdown,
                current_category,
                transformed_image_filepath,
                transformed_image_b64,
                primary_source_url_for_disclaimer
            )

            # 7. Post to Blogger
            if saved_html_file_path and blogger_oauth_credentials and BLOGGER_BLOG_ID and BLOGGER_BLOG_ID != 'YOUR_BLOG_ID_HERE':
                post_to_blogger(
                    saved_html_file_path,
                    BLOGGER_BLOG_ID,
                    blogger_oauth_credentials
                )
            else:
                logger.warning("Skipping Blogger post due to missing HTML file or Blogger credentials/ID.")

            # Add delay between blogs to avoid rate limits
            if topic_index < NUM_BLOGS_TO_CREATE:
                logger.info(f"Waiting 30 seconds before processing next blog...")
                time.sleep(30)

        except Exception as e:
            logger.critical(f"An unexpected error occurred during blog generation workflow for '{consolidated_topic}': {e}", exc_info=True)
            continue

    logger.info(f"\n--- Completed processing {NUM_BLOGS_TO_CREATE} blogs ---")

if __name__ == '__main__':
    main()