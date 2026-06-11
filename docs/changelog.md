# Changelog

All notable changes to the Patient Journey Simulator are documented here.
Format: Date → What was built → Decisions made

---

## [Unreleased]

### Planning complete (pre-build)
- Architecture finalized: FastAPI backend + Streamlit frontend
- Tech stack decided: SQLite + SQLAlchemy, ChromaDB, NetworkX, structlog
- LLM strategy: Gemini 2.5 Flash-Lite (primary), Groq Llama 3.3 70B (fallback + judge)
- Per-agent LLM config pattern decided
- Provider abstraction layer pattern decided
- Layer-based file structure decided (AI system components as layers)
- RAG strategy: synthetic corpus first, real cases added post-MVP
- project_spec.md, CLAUDE.md, prompts, and status tracker created

---
*Entries will be added here as the project is built.*
