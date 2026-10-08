# 🗺️ AI-Powered Landmark Intelligence & Travel Assistant

An AI-powered travel assistant that retrieves landmark information and visitor reviews from Google Maps using browser automation, exposes the data through a FastAPI backend, stores retrieved information in SQLite, and uses Google's Gemini 2.5 Flash model as a tool-using AI agent to provide natural-language responses.

---

## 🚀 Project Overview

The **AI-Powered Landmark Intelligence & Travel Assistant** combines web automation, REST APIs, database caching, and Generative AI to create an intelligent landmark information system.

The system is divided into two major components:

### Part A — Landmark Data API

A FastAPI-based backend that:

- Searches Google Maps for a requested landmark or place.
- Opens the corresponding Google Maps place page.
- Extracts:
  - Landmark name
  - Address
  - Overall rating
  - Total number of reviews
  - Visitor reviews
  - Reviewer names
  - Review ratings
  - Review text
- Uses Playwright to inspect the rendered Google Maps DOM.
- Stores retrieved landmark information and reviews in SQLite.
- Provides cached results to reduce repeated scraping.
- Exposes the data through REST API endpoints.

### Part B — Gemini AI Travel Assistant

A Gemini-powered AI agent that:

- Accepts natural-language user questions.
- Determines when landmark information is required.
- Automatically calls the Landmark Data API as a tool.
- Retrieves structured landmark information.
- Uses Gemini 2.5 Flash to generate a natural-language response.
- Summarizes visitor reviews instead of simply returning raw review text.
- Includes relevant information such as rating and address.

---

## 🏗️ System Architecture

```mermaid
flowchart TD

    A[User] --> B[Gemini AI Travel Assistant]

    B --> C{Landmark information required?}

    C -->|Yes| D[get_landmark_info Tool]

    D --> E[FastAPI Landmark Data API]

    E --> F{Cached Data Available?}

    F -->|Yes| G[SQLite Database]

    F -->|No| H[Playwright]

    H --> I[Google Maps]

    I --> J[Extract Landmark Details & Reviews]

    J --> G

    G --> E

    E --> D

    D --> B

    B --> K[Natural Language Response]

    C -->|No| K
