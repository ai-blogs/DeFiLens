
# 🚀 CryptoGnosis: Automated AI Crypto Blog Creator

## 🤔 What is CryptoGnosis?

CryptoGnosis is an advanced automation project designed to generate and publish in-depth blog posts on trending cryptocurrency topics. It leverages powerful AI models and various APIs to handle the entire content creation workflow, from news aggregation and topic identification to image generation and automated publishing to Google Blogger.

## ✨ Features

*   **📰 Latest Crypto News Aggregation:** Fetches real-time crypto headlines and summaries from NewsAPI.org.
*   **💡 AI-Powered Trending Topic Extraction:** Utilizes Google Gemini to analyze aggregated news and identify the most prominent and trending crypto themes for a new blog post.
*   **🎨 AI-Generated Featured Images:** Creates eye-catching, high-quality blog post images based on the trending topic using the `black-forest-labs/FLUX.1-dev` diffusion model from Hugging Face.
*   **🖼️ Smart Image Transformation & Branding:** Uses Pillow to automatically resize, crop (to a 16:9 ratio), enhance, and overlay branding (logo, title text) onto the generated images. Images are then Base64 encoded for direct embedding into HTML.
*   **✍️ Gemini-Powered Content Generation:** Generates comprehensive, SEO-optimized blog posts (2000-3000 words) with:
    *   Unique, SEO-friendly titles.
    *   Detailed hierarchical outlines.
    *   Rich, expanded content synthesized from sources, including plausible (even if fabricated) details, statistics, and examples.
    *   Contextually relevant external links (to reputable crypto sites) and internal links (to hypothetical blog posts on your site).
    *   Clean metadata block for publishing.
*   **🔗 Seamless Blogger Publishing:** Authenticates securely with the Google Blogger API (using OAuth 2.0 with GitHub Secrets) and automatically posts the generated HTML content live to your specified blog, complete with titles, labels, and embedded images.
*   **⚙️ Automated Workflow:** Configured to run on a schedule via GitHub Actions, allowing for fully autonomous content generation and publishing. Manual triggering is also supported.

## 🧱 Workflow Breakdown

1.  **News Aggregation:** Fetches latest crypto news from NewsAPI.org.
2.  **Trending Topic Extraction:** Gemini analyzes article titles and summaries to identify a single, specific trending crypto topic.
3.  **AI-Generated Image:** A prompt based on the trending topic is sent to the Hugging Face `FLUX.1-dev` diffusion model to generate a unique image.
4.  **Image Transformation & Branding:** The generated image is processed (resized, cropped, enhanced, branded, text overlay) using Pillow and converted to Base64.
5.  **AI Content Generation:** Gemini (as a Research Agent and Content Generator Agent) creates an SEO-optimized title, detailed outline, and the full 2000-3000 word blog post, incorporating keywords and relevant details.
6.  **Blog Post Saving & HTML Generation:** The AI-generated Markdown is cleaned, converted to styled HTML, and embedded with the Base64 featured image, along with SEO metadata (Open Graph, Twitter Cards, JSON-LD).
7.  **Posting to Blogger:** The final HTML content is published to your Google Blogger account.

## 🚀 Getting Started

### 1. Prerequisites

Before you begin, ensure you have:

*   **Python 3.8+** installed.
*   **Git** installed.
*   A **Google Account** with access to [Google Cloud Console](https://console.cloud.google.com/).
*   A **Google Blogger blog**.

### 2. Obtain Your API Keys & Tokens

You'll need the following API credentials:

*   **NewsAPI.org API Key:**
    *   Register or log in at [NewsAPI.org](https://newsapi.org/).
    *   Your API key will be displayed on your dashboard after registration.
*   **Hugging Face Access Token:**
    *   Go to [Hugging Face Settings -> Access Tokens](https://huggingface.co/settings/tokens).
    *   Click "New token" and create a token with **"Write" access** (required for the inference API).
*   **Google Gemini API Key:**
    *   Visit [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   Create a new API key.
*   **Google Blogger API Credentials (OAuth 2.0 Client ID):**
    *   Go to [Google Cloud Console](https://console.cloud.google.com/apis/dashboard).
    *   **Create a new project** (or select an existing one).
    *   Go to **APIs & Services > OAuth consent screen**:
        *   Set up your consent screen (Internal/External, add scopes if needed). Ensure it's in "Published" status for external use.
    *   Go to **APIs & Services > Credentials**:
        *   Click "CREATE CREDENTIALS" -> "OAuth client ID".
        *   Select "Desktop app". Give it a name.
        *   Download the generated `client_secrets.json` file. Save it in your project's root directory for initial local authentication.
    *   **Enable the Blogger API:** Go to **APIs & Services > Library**, search for "Blogger API v3" and enable it.
*   **Blogger Blog ID:**
    *   Log in to your Blogger account.
    *   Go to your desired blog.
    *   In the URL, you'll see `blogID=XXXXXXXXXXXX`. Copy this number.

### 3. Project Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/your-crypto-blog-repo.git
    cd your-crypto-blog-repo
    ```

2.  **Create `requirements.txt`:**
    Create a file named `requirements.txt` in the root of your project with the following content:
    ```
    python-dotenv
    requests
    Pillow
    google-generativeai
    google-api-python-client
    google-auth-httplib2
    google-auth-oauthlib
    ```

3.  **Create `.env` (for local testing):**
    Create a file named `.env` in your project's root directory. **Add `.env` to your `.gitignore` file** to prevent it from being committed to Git, as it contains sensitive API keys.
    ```
    # .env (DO NOT COMMIT THIS FILE TO GIT!)
    NEWSAPI_API_KEY=YOUR_NEWSAPI_KEY_HERE
    HUGGINGFACE_API_TOKEN=YOUR_HUGGINGFACE_TOKEN_HERE
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
    BLOGGER_BLOG_ID=YOUR_BLOGGER_BLOG_ID_HERE

    # If you want to test the GitHub Secrets method locally,
    # you can copy the content of your client_secrets.json and token_blogger.json here.
    # Otherwise, they will be loaded from local files if present during local run.
    # GOOGLE_CLIENT_SECRETS_JSON='{"web": {"client_id": "...", "project_id": "...", ...}}'
    # GOOGLE_OAUTH_TOKEN_JSON='{"token": "...", "refresh_token": "...", "token_uri": "...", ...}}'

    # Optional: Path to your branding logo if you have one in your local repo
    # BRANDING_LOGO_PATH='path/to/your/logo.png'
    ```

4.  **Initial Local Blogger OAuth Authentication:**
    *   Place your downloaded `client_secrets.json` file in the root of your project.
    *   You'll need a script (e.g., `generate_token.py` from your previous steps) to perform the initial OAuth flow and generate `token_blogger.json`.
        ```python
        # generate_token.py (Example content from your Part 2)
        import os
        import json
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        # If modifying these scopes, delete the file token_blogger.json.
        SCOPES = ['https://www.googleapis.com/auth/blogger']
        TOKEN_FILE = 'token_blogger.json'
        CLIENT_SECRETS_FILE = 'client_secrets.json'

        def generate_blogger_token():
            creds = None
            if os.path.exists(TOKEN_FILE):
                try:
                    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
                    print(f"Token found: {TOKEN_FILE}")
                except Exception as e:
                    print(f"Error loading token: {e}. Will re-authenticate.")
                    creds = None

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    print("Token expired, attempting to refresh...")
                    try:
                        creds.refresh(Request())
                    except Exception as e:
                        print(f"Failed to refresh token: {e}. Re-authenticating...")
                        creds = None
                if not creds:
                    print("Initiating new OAuth flow...")
                    if not os.path.exists(CLIENT_SECRETS_FILE):
                        print(f"Error: '{CLIENT_SECRETS_FILE}' not found. Please download from Google Cloud Console.")
                        return

                    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                    creds = flow.run_local_server(port=0, prompt='consent', authorization_prompt_message='Please authorize this application to access your Blogger account.')

                # Save the credentials for the next run
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                print(f"New token saved to '{TOKEN_FILE}'.")

            if creds and creds.valid:
                print("Blogger authentication successful!")
            else:
                print("Blogger authentication failed.")
            return creds

        if __name__ == '__main__':
            generate_blogger_token()
        ```
    *   Run `python generate_token.py` in your terminal. This will open a browser window for you to authorize the application. Once authorized, `token_blogger.json` will be created.
    *   **Add `token_blogger.json` and `client_secrets.json` to your `.gitignore` file.**

### 4. GitHub Repository Setup (Secrets)

For automated runs on GitHub Actions, you need to store your sensitive keys and credentials as GitHub Secrets.

1.  Go to your GitHub repository on `github.com`.
2.  Navigate to **Settings** (top right).
3.  In the left sidebar, click on **Secrets and variables** > **Actions**.
4.  Click **New repository secret**.

Add the following secrets with their respective values:

*   **`NEWSAPI_API_KEY`**: Your NewsAPI.org API Key.
*   **`HUGGINGFACE_API_TOKEN`**: Your Hugging Face access token.
*   **`GEMINI_API_KEY`**: Your Google Gemini API Key.
*   **`BLOGGER_BLOG_ID`**: Your Blogger Blog ID (e.g., `8169847264446388236`).
*   **`GOOGLE_CLIENT_SECRETS_JSON`**: The **entire content** of your `client_secrets.json` file. Open the file, copy the whole JSON string, and paste it here.
    *   *Example Value:* `{"web":{"client_id":"YOUR_CLIENT_ID.apps.googleusercontent.com","project_id":"your-project-id","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":"YOUR_CLIENT_SECRET","redirect_uris":["http://localhost"]}}`
*   **`GOOGLE_OAUTH_TOKEN_JSON`**: The **entire content** of your `token_blogger.json` file. Open the file, copy the whole JSON string, and paste it here.
    *   *Example Value:* `{"token":"ya29.a0ARmC7...", "refresh_token":"1//0e...", "token_uri":"https://oauth2.googleapis.com/token", "client_id":"YOUR_CLIENT_ID.apps.googleusercontent.com", "client_secret":"YOUR_CLIENT_SECRET", "scopes":["https://www.googleapis.com/auth/blogger"],"expiry":"2024-07-28T12:00:00Z"}`

### 5. `crypto_blog_creator.py` Script

Ensure your main script is saved as `crypto_blog_creator.py` (copy the code provided in the previous response).

### 6. GitHub Actions Workflow (`.github/workflows/main.yml`)

Create the directory `.github/workflows/` in your repository root, and save the following content as `main.yml` inside it:

```yaml
# .github/workflows/main.yml
name: Automated Crypto Blog Creator

on:
  schedule:
    # Runs every 2 hours at the 0-minute mark (e.g., 00:00, 02:00, 04:00 UTC)
    - cron: '0 */2 * * *'
  workflow_dispatch: # Allows manual triggering from the GitHub UI

jobs:
  create-and-post-blog:
    runs-on: ubuntu-latest # Uses the latest Ubuntu environment provided by GitHub Actions

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4 # Clones your repository to the runner

    - name: Set up Python 3.12
      uses: actions/setup-python@v5 # Configures a Python environment
      with:
        python-version: '3.12' # Specifies the Python version to use

    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip # Upgrade pip to the latest version
        pip install -r requirements.txt      # Install all dependencies listed in requirements.txt

    - name: Prepare Branding Logo (Optional)
      # If you have a branding logo file in your repo (e.g., at 'assets/logo.png'),
      # uncomment and adjust the path below to make it accessible to the script.
      # run: cp assets/logo.png logo.png # Copies the logo to the root if your script expects it there
      # env:
      #   BRANDING_LOGO_PATH: 'logo.png' # Sets the environment variable for your script
      run: echo "No branding logo specified in workflow config. Skipping logo preparation." # Placeholder if not used

    - name: Run Crypto Blog Creator Script
      # Sets environment variables for your Python script using GitHub Secrets
      env:
        NEWSAPI_API_KEY: ${{ secrets.NEWSAPI_API_KEY }}
        HUGGINGFACE_API_TOKEN: ${{ secrets.HUGGINGFACE_API_TOKEN }}
        GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        BLOGGER_BLOG_ID: ${{ secrets.BLOGGER_BLOG_ID }}
        GOOGLE_CLIENT_SECRETS_JSON: ${{ secrets.GOOGLE_CLIENT_SECRETS_JSON }}
        GOOGLE_OAUTH_TOKEN_JSON: ${{ secrets.GOOGLE_OAUTH_TOKEN_JSON }}
        CI: 'true' # This environment variable tells the script it's running in a CI/CD environment,
                   # which prevents it from trying to open a browser for interactive OAuth.

      run: |
        python crypto_blog_creator.py # Executes your main Python script

    - name: Upload Generated Blogs and Images
      # This step uploads the generated blog drafts and images as a workflow artifact.
      # You can download this artifact from the GitHub Actions run summary page.
      uses: actions/upload-artifact@v4
      with:
        name: generated-blogs-and-images-${{ github.run_id }} # Unique name for the artifact
        path: |
          blog_drafts/       # Path to the folder containing generated HTML drafts
          transformed_images/ # Path to the folder containing transformed images
        retention-days: 7 # Keep the artifact for 7 days (adjust as needed)
```

## 🏃 Usage

### Running Locally (for testing/development)

1.  Ensure you have all API keys/tokens set in your `.env` file.
2.  Ensure `client_secrets.json` is in your root, and `token_blogger.json` has been generated via `generate_token.py`.
3.  Install dependencies: `pip install -r requirements.txt`
4.  Run the script: `python crypto_blog_creator.py`

### Running via GitHub Actions (Automated)

1.  **Commit and Push:** After setting up all files and GitHub Secrets, commit your changes and push them to your GitHub repository.
2.  **Scheduled Runs:** The workflow will automatically trigger every 2 hours as per the `cron` schedule in `main.yml`.
3.  **Manual Trigger:**
    *   Go to your GitHub repository.
    *   Click on the **Actions** tab.
    *   In the left sidebar, click on "Automated Crypto Blog Creator".
    *   On the right, click the "Run workflow" dropdown button, then click "Run workflow" again.
4.  **Monitor Progress:** You can monitor the workflow's execution, view logs, and download generated artifacts (blog drafts and images) directly from the GitHub Actions interface.

## 🛠️ Customization

You can customize various aspects of the bot by modifying `crypto_blog_creator.py`:

*   **`CRYPTO_QUERY_TERM`**: Change the main query term for NewsAPI (e.g., `"Bitcoin"`, `"Ethereum DeFi"`).
*   **`BLOG_CATEGORY`**: Adjust the category label used for internal organization and Blogger tags.
*   **`NUM_SOURCE_ARTICLES_TO_FETCH`**: Increase or decrease the number of articles fetched from NewsAPI.
*   **`BRANDING_LOGO_PATH`**: Uncomment and set the path to your logo if you want custom branding on images.
*   **LLM Prompts**: Fine-tune the prompts within `perform_research_agent` and `generate_content_agent` to influence content style, tone, length, keyword integration, and specific details. This is crucial for managing the AI's output.
*   **Hugging Face Prompt**: Adjust the `hf_image_prompt` in `main()` for different image styles.
*   **HTML Styling**: Modify the CSS within `generate_enhanced_html_template` to change the look and feel of your blog posts.
*   **Blogger Post Status**: Change `'status': 'LIVE'` to `'status': 'DRAFT'` in `post_to_blogger` if you prefer to review posts before publishing them manually.
*   **GitHub Actions Schedule**: Adjust the `cron` expression in `.github/workflows/main.yml` to change how often the script runs.

## ⚠️ Important Considerations & Limitations

*   **Factual Accuracy:** While Gemini is powerful, the script instructs it to synthesize information and *invent plausible details and links*. This means the generated content, while sounding authoritative, **may not be entirely factually accurate or link to real, specific pages.** Always review the content for critical information before relying on it, especially for a public blog.
*   **AI "Hallucinations":** LLMs can sometimes generate incorrect or nonsensical information. Review is recommended.
*   **API Rate Limits:** Be mindful of rate limits for NewsAPI, Hugging Face, Gemini, and Blogger. The script includes basic retry logic and delays, but excessive usage may lead to temporary blocks.
*   **SEO for Images:** While the image is embedded as Base64 in the HTML, for optimal external SEO (e.g., `og:image`, `twitter:image`, JSON-LD), these meta tags ideally point to a publicly accessible URL for the image. This script does not currently upload images to a public host to get such a URL. You might need to manually update these in Blogger after publishing or implement a separate image hosting solution.
*   **Blogger API Permissions:** Ensure your Google account authorized for Blogger has sufficient permissions (Author/Admin) on the target blog.

## 🤝 Contributing

Feel free to fork this repository and adapt it to your needs. If you make improvements or fix bugs, consider opening a pull request!

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
```
