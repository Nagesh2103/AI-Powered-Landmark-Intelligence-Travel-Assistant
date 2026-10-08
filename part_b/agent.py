"""
Part B: Gemini tool-using agent.

Exposes the Part A FastAPI service (`/place`) to Gemini as a callable
tool. Gemini decides on its own when a user's question needs landmark
data, calls the tool, and writes a natural-language answer from the
result -- we never hand-parse the user's question ourselves.

Requires:
    pip install google-genai httpx
    export GEMINI_API_KEY=...        # from https://aistudio.google.com/apikey
    export LANDMARK_API_BASE=http://localhost:8000   # optional, this is the default

The Part A server must be running (see part_a/README) before you start
this agent.
"""

import os

import httpx
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

LANDMARK_API_BASE = os.environ.get("LANDMARK_API_BASE", "http://localhost:8000")


def get_landmark_info(name: str) -> dict:
    """Look up structured information about a monument or landmark.

    Calls the local Landmark Data API to retrieve the place's name,
    address, rating, and a set of visitor reviews.

    Args:
        name: The landmark or place name, e.g. "Mysore Palace".

    Returns:
        A dict with keys: name, address, rating, total_reviews, reviews.
    """
    resp = httpx.get(f"{LANDMARK_API_BASE}/place", params={"name": name}, timeout=30)
    resp.raise_for_status()
    return resp.json()


SYSTEM_INSTRUCTION = (
    "You are a helpful travel assistant. When a user asks about a monument "
    "or landmark, call the get_landmark_info tool to fetch real details and "
    "reviews before answering -- do not invent facts. Summarize the reviews "
    "in your own words rather than quoting them, and naturally mention the "
    "rating and address where relevant."
)


def build_chat():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[get_landmark_info],  # SDK auto-generates the schema and calls it for us
        ),
    )
    return chat


def ask(chat, question: str) -> str:
    response = chat.send_message(question)
    return response.text


if __name__ == "__main__":
    chat = build_chat()
    print("Landmark assistant. Ask about a monument or landmark ('quit' to exit).")
    while True:
        question = input("\nYou: ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        print("\nAssistant:", ask(chat, question))
