# Meta-Agent

Meta-Agent is a modular, **LangChain-powered** orchestration layer that turns natural-language goals into executable plans and actions across multiple platforms (Slack, JIRA, e-mail, calendars, …).  
The first release focuses on a local FastAPI service with a chat interface; connectors and auto-planning can be enabled incrementally without changing the core.

---

## Table of Contents
1. [Features](#features)
2. [Architecture](#architecture)
3. [Repository Layout](#repository-layout)
4. [Installation & Local Running](#installation--local-running)
5. [Configuration](#configuration)
6. [API Reference](#api-reference)
7. [Deployment](#deployment)
8. [Development Guide](#development-guide)
9. [Roadmap](#roadmap)
10. [License](#license)

---

## Features
* 🔌 **Provider-agnostic LLM** loading (OpenAI, Anthropic, Google Gemini, Hugging Face, Cohere, …).  
* 🗂️ Declarative **MemoryStore** (SQLite by default, Chroma + Postgres/Mongo/Redis ready).  
* 🧠 **NLU stack** (ParseGoalChain & FollowUpChain) to extract intents/slots and ask for missing info.  
* 📜 **Planner** that converts intents to executable steps and Jinja-renders sub-agent code.  
* 🕸️ **Connector framework** with a common `PlatformAdapter` and a fully-featured Slack connector.  
* ⏲️ **Scheduler** stubs (APScheduler) for periodic or delayed tasks.  
* 🐳 One-command **local Docker** image or plain `uvicorn` run.  
* ☁️ **Cloud-ready**: deploy.sh helper, sample Terraform for GCP Cloud Run.

---

## Architecture
```
┌────────────┐  HTTP/WS  ┌───────────────────┐
│   Client   │──────────►│  FastAPI Router   │
└────────────┘           └────────┬──────────┘
                                  │
                     ┌────────────▼───────────────┐
                     │        MetaAgent           │
                     │  (ConversationChain)       │
                     └────────┬────────┬──────────┘
                              │        │
                ┌─────────────▼───┐    │
                │  ParseGoalChain │    │
                └─────────────┬───┘    │
                              │        │
                ┌─────────────▼───┐    │
                │ FollowUpChain   │    │
                └─────────────┬───┘    │
                              │        │
                ┌─────────────▼────────▼────────┐
                │         PlanGenerator         │
                └────────┬────────────┬─────────┘
                         │            │
                ┌────────▼───┐   ┌────▼────────┐
                │ MemoryStore│   │Connectors   │
                └────────────┘   └─────────────┘
```
*The diagram omits the Scheduler and templates for brevity.*

---

## Repository Layout
```
meta-agent/
├── app/
│   ├── main.py            # FastAPI + LangChain entrypoint
│   ├── api/               # REST resources
│   ├── nlu/               # LLM chains
│   ├── planner/           # Plan generator
│   ├── memory/            # Persistence layer
│   ├── scheduler/         # APScheduler wrapper
│   ├── connectors/        # Slack, JIRA, ...
│   ├── templates/         # Jinja code templates
│   └── utils/             # logger, config
├── scripts/               # deploy.sh, terraform/
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Installation & Local Running

### 1. Clone & environment
```bash
git clone https://github.com/your-org/meta-agent.git
cd meta-agent
cp .env.example .env            # or let deploy.sh generate one
```

### 2. Quick start with Docker
```bash
docker build -t meta-agent .
docker run --rm -p 8000:8000 --env-file .env meta-agent
```
Browse `http://localhost:8000/docs` for the Swagger UI.

### 3. Without Docker
```bash
ythonp -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)      # load env vars
uvicorn app.main:app --reload
```

---

## Configuration

All runtime options are read from environment variables (prefix `META_AGENT_`).  
A `.env` file is the easiest way:

| Variable | Default | Description |
|----------|---------|-------------|
| `META_AGENT_ENVIRONMENT` | development | Mode: development / staging / production |
| `META_AGENT_LLM_PROVIDER` | openai | Provider slug (`openai`, `anthropic`, `google`, `huggingface`, `cohere`) |
| `META_AGENT_LLM_API_KEY` |  | API key for chosen provider |
| `META_AGENT_LLM_MODEL` | gpt-4 | Model name / id |
| `META_AGENT_DB_TYPE` | sqlite | `sqlite`, `postgres`, `mongodb` … |
| `META_AGENT_DB_CONNECTION_STRING` | sqlite:///./data/meta_agent.db | SQLAlchemy-style URI |
| `META_AGENT_SLACK_API_TOKEN` | | Bot OAuth token if Slack connector needed |
| `META_AGENT_SLACK_SIGNING_SECRET` | | Request signing secret |

See `app/utils/config.py` for the exhaustive list and validation rules.

---

## API Reference

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/chat` | Simple conversational endpoint |
| `POST` | `/goals` | Parse & store a new goal |
| `GET`  | `/goals` | List goals (`user_id`, `status`, paging) |
| `PUT`  | `/goals/{goal_id}` | Update goal, answer follow-ups |
| `GET`  | `/health` | Service health / uptime |

Swagger/OpenAPI docs are auto-generated at `/docs`.

---

## Deployment

### deploy.sh helper
```bash
./scripts/deploy.sh --env local                 # docker-compose style run
./scripts/deploy.sh --env local --no-docker     # bare metal
./scripts/deploy.sh --env gcp --gcp-project id  # builds image & Cloud Run
```

### Docker only
The provided `Dockerfile` is production-ready (non-root user, healthcheck, volume for `/app/data`). Push the image to the registry of your choice.

### GCP Cloud Run
* Prerequisites: `gcloud` cli, Artifact Registry or GCR, enabled APIs.
* Build & push:  
  `gcloud builds submit --tag gcr.io/$PROJECT/meta-agent`
* Deploy:  
  `gcloud run deploy meta-agent --image gcr.io/$PROJECT/meta-agent --region us-central1 --platform managed --allow-unauthenticated`

Terraform manifests under `scripts/terraform/` automate:
* Private VPC, Cloud Run service
* Cloud SQL Postgres instance
* Secret Manager secrets
Edit `terraform.tfvars` and run `terraform init && terraform apply`.

---

## Development Guide

### Tests & linting
```bash
pytest -q
black . && isort .
mypy .
```

### Extending with a new LLM provider
1. Set `META_AGENT_LLM_PROVIDER=custom` (or add a new enum in `config.py`).
2. Implement a small adapter in `app/main.get_llm_instance`.
3. No changes elsewhere; chains depend only on the `BaseLLM` interface.

### Adding a connector
Create `app/connectors/<platform>_connector/` with a subclass of `PlatformAdapter`, then register it in `app/connectors/__init__.py`.

---

## Roadmap
- ☑️ Core chat & goals API  
- ☐ Execution engine for generated plans  
- ☐ Vector memory default (Chroma)  
- ☐ JIRA connector & Google Calendar connector  
- ☐ Web UI dashboard  
- ☐ Benchmark & fine-tune prompt templates  

---

## License
Apache 2.0 © 2025 San Francisco AI Factory
