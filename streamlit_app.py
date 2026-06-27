import streamlit as st
from snowflake.snowpark.context import get_active_session
import json

# --- Session Setup ---
session = get_active_session()

# --- Session State ---
if "query" not in st.session_state:
    st.session_state.query = ""
if "result" not in st.session_state:
    st.session_state.result = None

# --- Custom CSS ---
st.markdown("""
<style>
    .answer-card {
        background-color: #f8f9fa;
        border-left: 4px solid #2563eb;
        border-radius: 8px;
        padding: 20px 24px;
        margin: 16px 0;
        font-size: 15px;
        line-height: 1.7;
        color: #1e293b;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 600;
        margin-right: 8px;
    }
    .badge-eu {
        background-color: #dbeafe;
        color: #1d4ed8;
    }
    .badge-us {
        background-color: #ffedd5;
        color: #c2410c;
    }
    .how-it-works {
        background-color: #f8fafc;
        border-radius: 8px;
        padding: 16px;
        font-size: 14px;
        color: #475569;
    }
    div[data-testid="stButton"] button {
        border: 1px solid #e2e8f0 !important;
        border-radius: 8px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Retrieval Functions ---
def retrieve_chunks(query, source_filter=None, limit=5):
    filter_clause = ""
    if source_filter:
        filter_clause = f', "filter": {{"@eq": {{"SOURCE_DOCUMENT": "{source_filter}"}}}}'
    result = session.sql(f"""
        SELECT PARSE_JSON(
            SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
                'AI_POLICY_NAVIGATOR.RAG.POLICY_SEARCH_SERVICE',
                '{{"query": "{query}", "columns": ["chunk_text", "source_document", "chunk_index"], "limit": {limit}{filter_clause}}}'
            )
        )['results'] AS results
    """).collect()
    raw = result[0]["RESULTS"]
    if raw is None:
        return []
    return json.loads(raw)

def retrieve_chunks_hybrid(query, source_filter=None, limit=5):
    semantic_chunks = retrieve_chunks(query, source_filter, limit)
    semantic_ids = set([c["chunk_index"] for c in semantic_chunks])
    source_clause = f"AND source_document = '{source_filter}'" if source_filter else ""
    keywords = [w for w in query.split() if len(w) > 4]
    keyword_conditions = " OR ".join([
        f"LOWER(chunk_text) LIKE LOWER('%{kw}%')" for kw in keywords
    ])
    if keyword_conditions:
        ids_str = ','.join([f"'{i}'" for i in semantic_ids]) if semantic_ids else "''"
        keyword_rows = session.sql(f"""
            SELECT chunk_text, source_document, chunk_index
            FROM AI_POLICY_NAVIGATOR.RAG.CHUNKED_DOCUMENTS
            WHERE ({keyword_conditions})
            {source_clause}
            AND chunk_index NOT IN ({ids_str})
            LIMIT {limit}
        """).collect()
        keyword_chunks = [{"chunk_text": r["CHUNK_TEXT"],
                           "source_document": r["SOURCE_DOCUMENT"],
                           "chunk_index": r["CHUNK_INDEX"]} for r in keyword_rows]
    else:
        keyword_chunks = []
    return semantic_chunks + keyword_chunks

def retrieve_chunks_hybrid_expanded(query, source_filter=None, limit=5, max_chunks=20):
    semantic_chunks = retrieve_chunks(query, source_filter, limit)
    semantic_indices = set([int(c["chunk_index"]) for c in semantic_chunks])
    expanded_indices = set(semantic_indices)
    header_markers = ["shall be prohibited", "article 5", "chapter ii",
                      "the following", "prohibited ai practices"]
    for c in semantic_chunks:
        idx = int(c["chunk_index"])
        text = c["chunk_text"].lower()
        is_header = any(marker in text for marker in header_markers)
        forward = 15 if is_header else 2
        for offset in range(1, forward + 1):
            expanded_indices.add(idx + offset)
    hybrid_chunks = retrieve_chunks_hybrid(query, source_filter, limit)
    keyword_indices = set([int(c["chunk_index"]) for c in hybrid_chunks
                           if int(c["chunk_index"]) not in semantic_indices])
    all_indices = expanded_indices.union(keyword_indices)
    source_clause = f"AND source_document = '{source_filter}'" if source_filter else ""
    indices_str = ','.join([str(i) for i in sorted(all_indices)])
    rows = session.sql(f"""
        SELECT chunk_text, source_document, chunk_index
        FROM AI_POLICY_NAVIGATOR.RAG.CHUNKED_DOCUMENTS
        WHERE chunk_index IN ({indices_str})
        {source_clause}
        ORDER BY chunk_index
        LIMIT {max_chunks}
    """).collect()
    return [{"chunk_text": r["CHUNK_TEXT"],
             "source_document": r["SOURCE_DOCUMENT"],
             "chunk_index": r["CHUNK_INDEX"]} for r in rows]

def build_prompt(query, chunks):
    context = ""
    for i, chunk in enumerate(chunks):
        context += f"[Chunk {i+1} - {chunk['source_document']}]\n{chunk['chunk_text']}\n\n"
    return f"""You are an AI policy expert assistant. Answer the user's question based ONLY on the provided context from the EU AI Act and US AI Executive Order documents.

If the answer is not in the context, say "I could not find information about this in the provided documents."

Always mention which document your answer comes from.

Context:
{context}

Question: {query}

Answer:"""

def rag_query(query, source_filter=None):
    chunks = retrieve_chunks_hybrid_expanded(query, source_filter, limit=5, max_chunks=20)
    prompt = build_prompt(query, chunks)
    response = session.sql(f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            'mistral-large2',
            '{prompt.replace("'", "''")}'
        ) AS answer
    """).collect()
    return {
        "answer": response[0]["ANSWER"],
        "sources": list(set([c["source_document"] for c in chunks])),
        "chunks_used": len(chunks)
    }

def rag_query_balanced(query):
    eu_chunks = retrieve_chunks_hybrid_expanded(query, "EU_AI_ACT", limit=5, max_chunks=10)
    eo_chunks = retrieve_chunks_hybrid_expanded(query, "US_AI_EO", limit=5, max_chunks=10)
    all_chunks = eu_chunks + eo_chunks
    prompt = build_prompt(query, all_chunks)
    response = session.sql(f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            'mistral-large2',
            '{prompt.replace("'", "''")}'
        ) AS answer
    """).collect()
    return {
        "answer": response[0]["ANSWER"],
        "sources": list(set([c["source_document"] for c in all_chunks])),
        "chunks_used": len(all_chunks)
    }

def score_color(score):
    if score >= 4.5:
        return "background-color: #dcfce7; color: #166534"
    elif score >= 3.0:
        return "background-color: #fef9c3; color: #854d0e"
    else:
        return "background-color: #fee2e2; color: #991b1b"

# --- UI ---
st.set_page_config(page_title="AI Policy Navigator", layout="wide")

# Header
st.markdown("""
<div style='background: linear-gradient(90deg, #1e3a5f 0%, #2563eb 100%); 
     padding: 28px 32px; border-radius: 12px; margin-bottom: 16px;'>
    <h1 style='color: white; margin: 0; font-size: 2rem;'>AI Policy Navigator</h1>
    <p style='color: #bfdbfe; margin: 8px 0 0 0; font-size: 1rem;'>
        Ask questions across the <b>EU AI Act</b> and <b>US AI Executive Order</b> using Snowflake Cortex RAG.
    </p>
</div>
""", unsafe_allow_html=True)

# How it works expander
with st.expander("How does this work?"):
    st.markdown("""
    <div class='how-it-works'>
    This app uses a <b>Retrieval-Augmented Generation (RAG)</b> pipeline built entirely on Snowflake Cortex:
    <ol>
        <li><b>Hybrid Retrieval</b> — combines semantic vector search (Cortex Search) with keyword search to find the most relevant chunks from the policy documents</li>
        <li><b>Context Expansion</b> — automatically expands around article headers to capture full lists and structured content</li>
        <li><b>Generation</b> — passes retrieved chunks to <code>mistral-large2</code> via Cortex Complete to generate a grounded answer</li>
        <li><b>Evaluation</b> — answers are scored by an LLM judge on Relevance, Faithfulness, and Completeness</li>
    </ol>
    <b>Documents:</b> EU AI Act (2024/1689, 144 pages) · US AI Executive Order 14110 (30 pages)
    </div>
    """, unsafe_allow_html=True)

st.divider()

# Sidebar
with st.sidebar:
    st.header("Settings")
    doc_filter = st.radio(
        "Search in:",
        ["Both Documents", "EU AI Act only", "US AI EO only"]
    )
    st.divider()
    st.markdown("**Documents loaded:**")
    st.markdown("EU AI Act (2024/1689)")
    st.markdown("US AI Executive Order 14110")
    st.divider()
    st.markdown("**Retrieval method:**")
    st.markdown("Hybrid Semantic + Keyword with Context Expansion")
    st.divider()
    st.markdown("**LLM:** `mistral-large2`")
    st.markdown("**Embeddings:** `snowflake-arctic-embed-m-v1.5`")

source_map = {
    "Both Documents": None,
    "EU AI Act only": "EU_AI_ACT",
    "US AI EO only": "US_AI_EO"
}
selected_source = source_map[doc_filter]

# Sample questions
st.markdown("**Try a sample question:**")
samples = [
    "What are the prohibited AI practices under Article 5?",
    "What role does NIST play according to the US AI EO?",
    "How do both documents address transparency in AI?",
    "What are high-risk AI systems according to the EU AI Act?"
]

cols = st.columns(4)
for i, sample in enumerate(samples):
    with cols[i]:
        if st.button(sample, key=f"sample_{i}", use_container_width=True):
            st.session_state.query = sample
            st.session_state.result = None

st.divider()

# Query input
query = st.text_input(
    "Ask a question about AI policy:",
    value=st.session_state.query,
    placeholder="e.g. What are the prohibited AI practices under the EU AI Act?",
    key="query_input"
)

if st.button("Search", type="primary") and query:
    st.session_state.query = query
    with st.spinner("Retrieving relevant chunks and generating answer..."):
        if doc_filter == "Both Documents":
            st.session_state.result = rag_query_balanced(query)
        else:
            st.session_state.result = rag_query(query, source_filter=selected_source)

# Display result
if st.session_state.result:
    result = st.session_state.result
    badge_html = ""
    for source in result["sources"]:
        if source == "EU_AI_ACT":
            badge_html += "<span class='badge badge-eu'>EU AI Act</span>"
        elif source == "US_AI_EO":
            badge_html += "<span class='badge badge-us'>US AI EO</span>"

    st.markdown(f"**Sources:** {badge_html}", unsafe_allow_html=True)
    st.markdown(f"<div class='answer-card'>{result['answer']}</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Chunks Retrieved", result["chunks_used"])
    with col2:
        st.metric("Documents Searched", len(result["sources"]))

st.divider()

# Eval scores
st.subheader("Evaluation Scores")
st.caption("LLM-as-a-judge scores from 10 test questions (1–5 scale)")

eval_df = session.sql("""
    SELECT
        question_id AS "Q#",
        question_type AS "Type",
        expected_source AS "Expected Source",
        relevance AS "Relevance",
        faithfulness AS "Faithfulness",
        completeness AS "Completeness",
        ROUND((relevance + faithfulness + completeness) / 3.0, 2) AS "Avg Score"
    FROM AI_POLICY_NAVIGATOR.RAG.EVAL_RESULTS
    ORDER BY question_id
""").to_pandas()

eval_df["Avg Score"] = eval_df["Avg Score"].round(2)

styled_df = eval_df.style.applymap(
    lambda v: score_color(v) if isinstance(v, (int, float)) else "",
    subset=["Relevance", "Faithfulness", "Completeness", "Avg Score"]
)

st.dataframe(styled_df, use_container_width=True, hide_index=True)