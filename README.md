# UGC Studio AI — User Generated Content Video Generation Platform

UGC Studio AI is an advanced, immersive AI-powered platform designed to generate high-quality, customized, user-generated-content-style videos on demand. By leveraging collaborative AI agents and background video processing, the platform automates the creation of high-engaging video concepts, script-writing, background visual fetching, background music sourcing, meme integration, and final ffmpeg video assembly.

---

## 🎨 System Architecture

UGC Studio AI is divided into a lightweight, highly-visual web client and a decoupled, distributed asynchronous backend processing system.

```mermaid
graph TD
    User([User Client]) -->|1. Prompts / Chats| FastAPI[FastAPI Server]
    FastAPI -->|2. Multi-Agent Team Orchestration| Agno[Agno Multi-Agent System]
    Agno -->|3. Draft Concept & Fetch Assets| Pexels[Pexels API]
    Agno -->|3. Fetch Memes / GIFs| Giphy[Giphy / Tenor APIs]
    Agno -->|4. Push Render Job| Redis[(Redis Broker)]
    Redis -->|5. Consume Job| Worker[Celery Worker / Background Process]
    Worker -->|6. FFmpeg Compiling / Overlays| FinalVideo[(Generated UGC Video)]
    Worker -->|7. Persist Metadata| MongoDB[(MongoDB)]
    Worker -->|8. Upload Video Assets| UploadThing[UploadThing Cloud Storage]
    FastAPI -.->|9. Real-time Progress (SSE)| User
```

### 1. Frontend Client (`frontend/app`)
* **Framework**: React 19 + TypeScript + Vite.
* **Styling**: TailwindCSS 4.0 using premium glassmorphic cards and customized sleek overlays.
* **Animations**: GSAP for choreographed state transitions, progress bars, and high-fidelity number counters.
* **Visuals**: A full-viewport, interactive WebGL fluid-dynamics background powered by raw Three.js and custom raymarched shaders, with a hardware-concurrency Canvas 2D fallback for low-power devices.
* **Logic**: Event-driven states with Server-Sent Events (SSE) subscriptions for real-time video rendering logs.

### 2. Backend API & Workers (`backend/`)
* **API Framework**: FastAPI with full support for asynchronous routing and SSE streaming.
* **Agent Integration**: Powered by **Agno** (formerly Phidata) utilizing Google Gemini Pro models. Features cooperative multi-agent workflows:
  * **Video Concept Specialist Agent**: Outlines high-level visual narrative.
  * **UGC Scriptwriter Agent**: Crafts natural, highly engaging voiceovers and script text.
  * **Assets Curator Agent**: Queries Pexels, Tenor, and Giphy dynamically.
  * **Soundtrack Matcher Agent**: Selects and aligns the background music track.
* **Database**: **MongoDB** for user profiles, session trees, conversations, rendering metadata, and job queues.
* **Caching & Queueing**: **Redis** for distributed pub/sub messaging, SSE event caching, and Celery job distribution.
* **Video Rendering Engine**: Fully modular Python rendering pipelines compiling visual assets, subtitles, image overlays, audio levels, and memes using raw `ffmpeg` command assemblies.

---

## 🚀 Key Features

* **Multi-Agent Collaboration**: Transparent execution steps from visual agents, scriptwriting agents, asset curating agents, and music matchers.
* **Real-time Status Progression**: Live status feeds of rendering progress bar, active console logs, and agent quote popups during assembly.
* **High-Fidelity UI**: Dark-mode primary-glow aesthetic, responsive sidebar, fully-featured customized custom 16:9 video player with sound toggle, and overlay controls.
* **Meme & Asset Richness**: Dynamic integration of high-quality Tenor/Giphy memes matched contextual to the generated topic.
* **Optimized Rendering Pipelines**: Decoupled worker pipelines compiling multiple resolution assets securely.

---

## 🛠️ Getting Started

### Prerequisites
Make sure you have the following installed on your host system:
* **Node.js** (v18+ recommended)
* **Python** (v3.10+ recommended)
* **Redis Server** (listening on default port `6379`)
* **MongoDB** (listening on default port `27017`)
* **FFmpeg** (installed on system path for rendering)

---

### Setup & Installation

#### 1. Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the `backend` folder matching the configuration template below.

#### Backend `.env` Template
```ini
# Redis config
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# MongoDB config
MONGO_URI=mongodb://localhost:27017
MONGO_DB=ugc_video_platform

# API Keys
GOOGLE_API_KEY=your_gemini_api_key_here
PEXELS_API_KEY=your_pexels_key_here
TENOR_API_KEY=your_tenor_key_here
GIPHY_API_KEY=your_giphy_key_here
UPLOADTHING_API_KEY=your_uploadthing_api_key_here

# Local temporary storage for intermediate FFmpeg clips
TEMP_DIR=/tmp/ugc_platform
LOG_LEVEL=INFO
LOG_FILE=/tmp/ugc_platform/app.log
```

---

#### 2. Frontend Setup
1. Navigate to the frontend app directory:
   ```bash
   cd frontend/app
   ```
2. Install npm dependencies:
   ```bash
   npm install
   ```

---

## 🏃 Running the Application

For a fully operational system, you need to spin up **Redis**, **MongoDB**, the **FastAPI Server**, the **Asynchronous Rendering Worker**, and the **Vite Frontend Client**.

### Step 1: Start Services
Ensure Redis and MongoDB are running:
```bash
# Start Redis (standard mac command or brew service)
brew services start redis

# Start MongoDB
brew services start mongodb-community
```

### Step 2: Start FastAPI Server
From the activated backend environment:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 3: Start Asynchronous Rendering Worker
In a separate terminal shell within the activated backend environment:
```bash
python -m app.worker
```

### Step 4: Run Vite Frontend Client
From the `frontend/app` directory:
```bash
npm run dev
```
Open your browser and navigate to `http://localhost:5173`.

---

## 📂 Project Structure

```text
├── README.md               <-- You are here
├── backend/
│   ├── app/
│   │   ├── agents.py       <-- Agno LLM Multi-Agent definitions & tools
│   │   ├── assets.py       <-- Asset curators (Pexels, Tenor, Giphy helpers)
│   │   ├── config.py       <-- Environment variable loading
│   │   ├── main.py         <-- FastAPI entrypoints & SSE endpoints
│   │   ├── mongo_client.py <-- MongoDB operations & logging
│   │   ├── redis_client.py <-- Redis pub/sub and lock helpers
│   │   ├── renderer.py     <-- Video composition engine using FFmpeg
│   │   └── worker.py       <-- Background worker process
│   └── requirements.txt    <-- Backend Python packages
│
└── frontend/
    ├── tech-spec.md        <-- UI technical details
    └── app/
        ├── src/
        │   ├── components/ <-- Custom UI & visual player components
        │   ├── screens/    <-- State views (Welcome, Generating, Result)
        │   ├── hooks/      <-- Custom hooks (SSE tracking, counters, chat)
        │   ├── main.tsx    <-- React entrypoint
        │   └── index.css   <-- Core styles and design tokens
        └── package.json    <-- Frontend NPM packages
```

---

## 📝 License
This project is proprietary and for demonstration/use by the respective owner.
