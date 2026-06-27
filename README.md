# AI Policy Navigator

A Retrieval-Augmented Generation (RAG) application built on Snowflake Cortex that answers questions across two landmark AI policy documents — the EU AI Act and the US AI Executive Order 14110.

---

## Overview

Policy documents are dense, lengthy, and difficult to navigate. This project addresses that by building a conversational Q&A system that retrieves relevant sections from both documents and generates accurate, grounded answers using Snowflake's native AI capabilities — no external APIs or frameworks required.

---

## Documents

- **EU AI Act** (Regulation EU 2024/1689) — 144 pages
- **US AI Executive Order 14110** — 36 pages

---

## Pipeline

**1. Ingestion**
PDFs are uploaded to a Snowflake internal stage and parsed using `SNOWFLAKE.CORTEX.PARSE_DOCUMENT` with layout mode to preserve document structure.

**2. Chunking**
Parsed text is split into overlapping chunks (500 tokens, 50 token overlap) using `SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER` in markdown mode, producing 2,163 chunks across both documents.

**3. Cortex Search Service**
Chunks are indexed using a Cortex Search Service with `snowflake-arctic-embed-m-v1.5` embeddings for semantic retrieval.

**4. Hybrid Retrieval**
A custom retrieval pipeline combines:
- Semantic search via Cortex Search
- Keyword search via SQL pattern matching
- Context expansion around article headers to capture full enumerated lists

**5. Generation**
Retrieved chunks are passed to `mistral-large2` via `SNOWFLAKE.CORTEX.COMPLETE` to generate grounded answers with source citations.

**6. Evaluation**
A 10-question evaluation dataset tests the system across question types: conceptual, definition, enumerated list, specific entity, specific role, and cross-document. Each answer is scored on Relevance, Faithfulness, and Completeness (1–5) using LLM-as-a-judge.

**7. Streamlit App**
An interactive front-end built with Streamlit in Snowflake with document filtering, sample questions, source badges, and an evaluation scorecard.

---

## Project Structure

```
ai-policy-navigator/
├── Initial_Setup.sql              # Database, schema, and stage setup
├── AI_Policy_Navigator.ipynb      # Full pipeline: parsing, chunking, RAG, evaluation
├── streamlit_app.py               # Streamlit front-end
├── DEVELOPMENT_NOTES.md           # Engineering decisions and retrieval design
└── README.md
```


---

## Data Sources

- EU AI Act: [EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689)
- US AI Executive Order: [Federal Register](https://www.federalregister.gov/documents/2023/11/01/2023-24283/safe-secure-and-trustworthy-development-and-use-of-artificial-intelligence)
