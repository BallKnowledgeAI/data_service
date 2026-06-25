# Schema Design

This repository contains the core schema definitions and database interactions for the BallKnowledge project. It manages connections to Postgres (for structured relational data) and Redis (for fast, ephemeral state data like possession tracking), as well as in-memory buffers for rolling window positional features.

## Setup Instructions

### 1. Environment Configuration
Copy the sample environment file and adjust the variables if necessary. By default, it connects to local Docker instances.
```bash
cp .env.example .env
```

### 2. Start Data Stores   
Ensure your Postgres and Redis containers are running. If you are using Docker Compose:
```bash
docker-compose up -d
```

### 3. Install Dependencies
Install the required packages using pip. We recommend doing this inside your active virtual environment (`ballknowledge_venv`).
```bash
pip install -r requirements.txt
```

---

## Testing Functionality

You can verify that the schema, models, and ingestion pipeline work correctly by running the `ingestion_engine.py` script. This engine reads match data from the `data_ingestion` module and streams it into the configured Postgres and Redis stores.

### Running the Engine
Execute the engine from the **monorepo root** (i.e. one level above this `schema_design` folder).

If you are using the virtual environment:
```powershell
.\ballknowledge_venv\Scripts\python.exe schema_design/ingestion_engine.py --no-frames
```
*(The `--no-frames` flag suppresses heavy per-frame positional logs, showing only structural events and periodic progress).*

### Expected Output
When run successfully, you should see:
1. Connections established to Postgres and Redis.
2. The initialisation of the StatsBomb demo source.
3. Live streaming logs showing possession events and frames being processed.
4. A final "Replay Complete" summary showing total events and possession statistics for both teams.

If you encounter a `RuntimeError` regarding missing environment variables, verify that your `.env` file is properly populated and located in the `schema_design` root directory.
