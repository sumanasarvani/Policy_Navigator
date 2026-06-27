# Development Notes — AI Policy Navigator

## Project Overview
This is a RAG-based Q&A system built on Snowflake Cortex that answers questions across the EU AI Act and US AI Executive Order using semantic search, hybrid retrieval, and LLM-as-a-judge evaluation.

---

## Retrieval Engineering Decisions

### Problem 1 — Semantic Search Misses Enumerated Lists
**Observation:** After querying "What are the prohibited AI practices under Article 5?", it returned only the section header (chunk 710) but not the actual required list items (chunks 711–724) for the answer. 

**Root cause:** Individual list items like "(a) the placing on the market..." do not semantically resemble the query "prohibited AI practices" strongly enough to be ranked highly by vector similarity alone.

**Attempts:**
- Increasing `limit` from 5 → 10 → 15: still missed the list items
- Direct chunk index fetch (`rag_query_with_context_window`): worked but required knowing the chunk range in advance, which is not practical for a real app

**Final solution — Hybrid Retrieval with Context Expansion:**
1. Semantic search via Cortex Search retrieves conceptually relevant chunks.
2. Keyword search via SQL `ILIKE` retrieves chunks containing query terms.
3. If any semantic anchor chunk is detected as a list/article header (via marker keywords), expand forward 15 chunks to capture the full list.
4. Cap total chunks at 20 before passing to LLM.

**Result:** Full Article 5 list (all 8 prohibited practices, a–h) retrieved and answered correctly.

---

### Problem 2 — Single-Document Bias in Cross-Document Queries
**Observation:** Asking "How do the EU AI Act and US AI Executive Order differ in their approach to AI safety?" returned only EU AI Act chunks, leaving the US EO unrepresented.

**Root cause:** Cortex Search ranks by relevance across the combined index. If one document dominates the top-k results, the other is excluded entirely.

**Solution — Balanced Retrieval (`rag_query_balanced`):**
- Retrieve top-k chunks from each document separately using `SOURCE_DOCUMENT` filter
- Combine results before building the prompt
- Guarantees both documents are always represented in cross-document queries

---

## Chunking Strategy
- **Chunk size:** 500 tokens
- **Overlap:** 50 tokens
- **Mode:** `markdown` — respects headers and paragraph boundaries
- **Result:** EU AI Act → 1,753 chunks | US AI EO → 410 chunks

The overlap ensures context is not lost at chunk boundaries, which is especially important for legal text where a sentence continuation in the next chunk may change the meaning.

---

## Evaluation Design
- **Method:** LLM-as-a-judge using `mistral-large2`
- **Dimensions:** Relevance, Faithfulness, Completeness (each scored 1–5)
- **Dataset:** It has 10 manually designed questions covering conceptual, definition, enumerated list, specific entity, specific role, and cross-document question types
- **Known limitation:** LLM-as-a-judge scores reflect quality of retrieved context, not ground truth. A judge cannot penalize an answer for missing content that was not retrieved
- 
