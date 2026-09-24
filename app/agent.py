# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import Client, types

from .a2ui_utils import a2ui_callback

FIRESTORE_PROJECT = "qwiklabs-gcp-03-b53a60a6c37d"
STATIC_ASSETS_BUCKET = "qwiklabs-gcp-03-b53a60a6c37d-static-assets-bucket"
MEMORY_BANK_ID = "7449158292833566720"


def _get_firestore_client() -> firestore.Client:
    """Returns a Firestore client configured with the hardcoded project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT)


def search_destinations(
    query: str = None,
    category: str = None,
    country: str = None,
    budget_tier: str = None,
) -> list[dict]:
    """Search for travel destinations in the VoyageAI database, filtering by query, country, category, or budget tier.

    Args:
        query: Optional search term to match in destination name, country, category, highlights, or description (e.g. 'Japan', 'Tokyo', 'beach').
        category: Optional category filter (e.g. 'cultural', 'beach', 'nature', 'luxury', 'adventure').
        country: Optional country filter (e.g. 'Japan', 'France', 'Canada', 'Italy', 'USA').
        budget_tier: Optional budget tier filter (e.g. 'budget', 'moderate', 'luxury', '$', '$$', '$$$', '$$$$').

    Returns:
        A list of matching destination records from Firestore.
    """
    db = _get_firestore_client()
    docs = db.collection("destinations").stream()
    all_destinations = []
    results = []

    q_str = query.lower().strip() if query else None
    cat_str = category.lower().strip() if category else None
    ctry_str = country.lower().strip() if country else None
    bud_str = budget_tier.lower().strip() if budget_tier else None

    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        all_destinations.append(d)

        name = str(d.get("name", "")).lower()
        d_country = str(d.get("country", "")).lower()
        d_category = str(d.get("category", "")).lower()
        d_budget = str(d.get("budget_tier", "")).lower()
        d_desc = str(d.get("description", "")).lower()
        d_highlights = " ".join([str(h).lower() for h in d.get("highlights", [])])

        full_text = f"{name} {d_country} {d_category} {d_budget} {d_desc} {d_highlights}"

        match_q = (not q_str) or (q_str in full_text)
        match_cat = (not cat_str) or (cat_str in d_category) or (cat_str in full_text)
        match_ctry = (not ctry_str) or (ctry_str in d_country) or (ctry_str in full_text)
        match_bud = (not bud_str) or (bud_str == d_budget) or (bud_str in d_budget)

        if match_q and match_cat and match_ctry and match_bud:
            results.append(d)

    if results:
        return results
    return all_destinations


def get_destination_details(destination_id: str) -> dict:
    """Retrieve full details for a specific travel destination by its document ID.

    Args:
        destination_id: The unique identifier of the destination (e.g. 'paris-france', 'tokyo-japan').

    Returns:
        A dictionary with destination details or an error message if not found.
    """
    db = _get_firestore_client()
    doc_ref = db.collection("destinations").document(destination_id.lower())
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return {"error": f"Destination '{destination_id}' not found."}


def add_destination(
    destination_id: str,
    name: str,
    country: str,
    category: str,
    budget_tier: str,
    description: str,
    best_time_to_visit: str = "",
) -> dict:
    """Add or update a travel destination in the VoyageAI database.

    Args:
        destination_id: Unique ID for the destination (slug format, e.g. 'kyoto-japan').
        name: Full name of the destination (e.g. 'Kyoto').
        country: Country name (e.g. 'Japan').
        category: Primary travel category (e.g. 'cultural', 'beach', 'nature', 'luxury').
        budget_tier: Budget tier ('$', '$$', '$$$', '$$$$').
        description: Engaging summary description of the destination.
        best_time_to_visit: Recommended season or months to visit.

    Returns:
        Confirmation dictionary with the added destination data.
    """
    db = _get_firestore_client()
    doc_ref = db.collection("destinations").document(destination_id.lower())
    data = {
        "name": name,
        "country": country,
        "category": category.lower(),
        "budget_tier": budget_tier,
        "description": description,
        "best_time_to_visit": best_time_to_visit,
    }
    doc_ref.set(data, merge=True)
    data["id"] = destination_id.lower()
    return {"status": "success", "destination": data}


def convert_currency_and_budget(amount: float, from_currency: str = "USD", to_currency: str = "EUR") -> dict:
    """Convert an amount or travel budget between currencies using live exchange rates.

    Args:
        amount: The budget or cost amount to convert.
        from_currency: 3-letter currency code for source currency (e.g. 'USD', 'EUR', 'GBP').
        to_currency: 3-letter currency code for target currency (e.g. 'EUR', 'JPY', 'CAD').

    Returns:
        A dictionary with converted amount, exchange rate, and target currency details.
    """
    url = f"https://open.er-api.com/v6/latest/{from_currency.upper()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VoyageAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            rate = data.get("rates", {}).get(to_currency.upper())
            if rate:
                converted = round(amount * rate, 2)
                return {
                    "original_amount": amount,
                    "from_currency": from_currency.upper(),
                    "converted_amount": converted,
                    "to_currency": to_currency.upper(),
                    "exchange_rate": rate,
                }
            return {"error": f"Currency code '{to_currency}' not found in exchange rates."}
    except Exception as e:
        return {"error": f"Failed to fetch exchange rates: {str(e)}"}


def fetch_destination_info(destination_name: str) -> dict:
    """Fetch real-world summary information, history, and description for a travel destination or landmark using Wikipedia REST API (public-apis).

    Args:
        destination_name: Name of the destination, city, or landmark (e.g. 'Kyoto', 'Eiffel Tower', 'Banff National Park').

    Returns:
        A dictionary containing title, description, summary, thumbnail URL, and article URL.
    """
    formatted_name = destination_name.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{formatted_name}"
    api_key = os.getenv("DESTINATION_API_KEY")
    headers = {"User-Agent": "VoyageAITravelConcierge/1.0 (contact@voyageai.example.com)"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return {
                "title": data.get("title"),
                "description": data.get("description"),
                "summary": data.get("extract"),
                "thumbnail_url": data.get("thumbnail", {}).get("source"),
                "article_url": data.get("content_urls", {}).get("desktop", {}).get("page"),
            }
    except Exception as e:
        return {"error": f"Failed to fetch information for '{destination_name}': {str(e)}"}


def generate_destination_image(
    prompt: str,
    tool_context: ToolContext,
) -> dict:
    """Generate a visual image/postcard for a travel destination or landmark using the gemini-3.1-flash-lite-image model in global region.

    Args:
        prompt: Detailed visual description of the destination, landmark, or scene to generate.

    Returns:
        A dictionary containing status, artifact filename, and public Cloud Storage https URL.
    """
    genai_client = Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")
    response = genai_client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    try:
        part = response.candidates[0].content.parts[0]
        image_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "image/jpeg"
    except Exception as e:
        return {"error": f"Failed to generate image: {str(e)}"}

    filename = f"postcard_{uuid.uuid4().hex[:8]}.jpg"

    # 1. Save artifact for Playground's Artifacts panel
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload image bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = storage_client.bucket(STATIC_ASSETS_BUCKET)
    blob_name = f"destinations/{filename}"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{STATIC_ASSETS_BUCKET}/{blob_name}"

    return {
        "status": "success",
        "artifact_filename": filename,
        "public_url": public_url,
    }


def generate_destination_video(
    prompt: str,
    tool_context: ToolContext,
) -> dict:
    """Generate a short video preview for a travel destination or attraction using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Args:
        prompt: Detailed description of the scene, destination, or attraction to generate video for.

    Returns:
        A dictionary containing status, artifact filename, and public Cloud Storage https URL.
    """
    genai_client = Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")
    response = genai_client.models.generate_content(
        model="gemini-omni-flash-preview",
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["VIDEO"]),
    )

    try:
        part = response.candidates[0].content.parts[0]
        video_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "video/mp4"
    except Exception as e:
        return {"error": f"Failed to generate video: {str(e)}"}

    filename = f"video_{uuid.uuid4().hex[:8]}.mp4"

    # 1. Save artifact for Playground's Artifacts panel
    artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
    tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload video bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = storage_client.bucket(STATIC_ASSETS_BUCKET)
    blob_name = f"destinations/{filename}"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{STATIC_ASSETS_BUCKET}/{blob_name}"

    return {
        "status": "success",
        "artifact_filename": filename,
        "public_url": public_url,
    }


def get_weather(query: str) -> dict:
    """Fetches real-time live weather and forecast information for any travel destination.

    Args:
        query: The city or destination name to get weather information for (e.g. 'Tokyo', 'Paris', 'San Francisco').

    Returns:
        A dictionary containing live weather details including temperature (°C), windspeed, and weather conditions.
    """
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(query)}&count=1&language=en&format=json"
        geo_req = urllib.request.Request(geo_url, headers={"User-Agent": "VoyageAI/1.0"})
        with urllib.request.urlopen(geo_req, timeout=10) as geo_res:
            geo_data = json.loads(geo_res.read().decode("utf-8"))
            results = geo_data.get("results")
            if not results:
                return {"error": f"Destination '{query}' not found."}

            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            city_name = loc.get("name", query)
            country = loc.get("country", "")

        api_key = os.environ.get("WEATHER_API_KEY")
        key_param = f"&apikey={api_key}" if api_key else ""
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true{key_param}"

        weather_req = urllib.request.Request(weather_url, headers={"User-Agent": "VoyageAI/1.0"})
        with urllib.request.urlopen(weather_req, timeout=10) as weather_res:
            w_data = json.loads(weather_res.read().decode("utf-8"))
            current = w_data.get("current_weather", {})
            return {
                "destination": f"{city_name}, {country}".strip(", "),
                "temperature_celsius": current.get("temperature"),
                "windspeed_kmh": current.get("windspeed"),
                "weather_code": current.get("weathercode"),
                "time": current.get("time"),
            }
    except Exception as e:
        return {"error": f"Error fetching weather for '{query}': {str(e)}"}


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


def get_live_currency_rates(base_currency: str = "USD") -> dict:
    """Fetches real-time foreign exchange rates for a base currency.

    Args:
        base_currency: The 3-letter currency code (e.g. 'USD', 'EUR', 'JPY', 'GBP').

    Returns:
        A dictionary containing exchange rates and timestamp information.
    """
    try:
        url = f"https://open.er-api.com/v6/latest/{base_currency.upper().strip()}"
        req = urllib.request.Request(url, headers={"User-Agent": "VoyageAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("result") == "success":
                return {
                    "base": data.get("base_code", base_currency.upper()),
                    "rates": data.get("rates", {}),
                    "last_update": data.get("time_last_update_utc"),
                }
        return {"error": "Failed to retrieve exchange rates."}
    except Exception as e:
        return {"error": f"Error fetching exchange rates: {str(e)}"}


# Memory Bank memory-generation callback (WRITE per turn)
async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        import logging
        logging.warning(f"Memory service not available or failed: {e}")
    return None


# Memory Bank service builder for future redeployments
def memory_bank_service_builder():
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


# Read Agent Engine resource name from deployment_metadata.json
metadata_file = Path(__file__).parent.parent / "deployment_metadata.json"
agent_engine_resource_name = None
if metadata_file.exists():
    try:
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id")
    except Exception:
        pass

if not agent_engine_resource_name:
    agent_engine_resource_name = f"projects/{FIRESTORE_PROJECT}/locations/us-east1/reasoningEngines/{MEMORY_BANK_ID}"

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)

a2ui_schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = a2ui_schema_manager.generate_system_prompt(
    role_description=(
        "You are VoyageAI Travel Concierge, an expert AI travel agent. "
        "Help users discover, plan, and curate personalized travel itineraries and destination recommendations."
    ),
    workflow_description=(
        "Analyze the request and return structured UI when appropriate. "
        "You MUST explicitly remember, track, and extract all travel destinations, cities, countries, landmarks, and places mentioned, discussed, visited, or planned by the user across all sessions and conversations. "
        "Whenever the user mentions, inquires about, or plans a destination, ensure it is remembered in long-term memory via Memory Bank. "
        "You remember stated user preferences, budget constraints, travel styles, and past trip facts across sessions. "
        "When asked about past travel, previous inquiries, or destination history, always recall and reference all preloaded memories from prior sessions. "
        "You have access to a Firestore database of travel destinations via your tools (search_destinations, "
        "get_destination_details, add_destination). You can also fetch real-world destination summaries via fetch_destination_info, "
        "generate visual postcards and images of destinations via generate_destination_image, "
        "convert travel budgets and currencies via convert_currency_and_budget, look up weather and local time, "
        "and execute Python code in a secure Agent Engine sandbox for complex calculations."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        search_destinations,
        get_destination_details,
        add_destination,
        fetch_destination_info,
        generate_destination_image,
        generate_destination_video,
        convert_currency_and_budget,
        get_live_currency_rates,
        get_weather,
        get_current_time,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)






