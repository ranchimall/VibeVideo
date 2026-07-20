"""
chroma_store.py
---------------
ChromaDB backend for VibeVideo.

- Persistent storage under models/chroma_db/
- 4 logical collections: video_editing, audio_editing, ai_tools, web_tools
- seed_collections()   → populate from documents/*.txt (idempotent)
- load_all_chunks()    → returns list of {text, capability} dicts for FAISS
- search_collection()  → targeted search in one collection
- search_all_collections() → search all collections, return globally best result
"""

import os
from pathlib import Path

import chromadb
from chromadb.config import Settings

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "models" / "chroma_db"
DOCUMENTS_DIR = BASE_DIR / "documents"

# ---------------------------------------------------------------------------
# Collection → capability mapping
# Each capability name is assigned to exactly ONE collection.
# ---------------------------------------------------------------------------
COLLECTION_MAP = {
    "video_editing": [
        "video_clip",
        "video_merge",
        "video_layer",
        "resize_video",
        "take_screenshot",
        "screen_record",
        "screen_record_audio",
    ],
    "audio_editing": [
        "audio_trim",
        "audio_volume",
        "audio_fade",
        "audio_mix",
        "audio_speed",
        "audio_reverse",
        "audio_replace",
        "audio_visual",
        "extract_audio",
        "normalize_audio",
    ],
    "ai_tools": [
        "face_swap_video",
        "generate_subtitles",
        "burn_subtitles",
        "clip_by_keyword",
        "clip_by_semantic",
    ],
    "web_tools": [
        "download_youtube",
    ],
}

# Reverse lookup: capability → collection name
CAPABILITY_TO_COLLECTION = {
    cap: col for col, caps in COLLECTION_MAP.items() for cap in caps
}

# ---------------------------------------------------------------------------
# ChromaDB client (persistent)
# ---------------------------------------------------------------------------
_client = None

def _get_client():
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def _get_collection(name: str):
    """Get or create a named collection."""
    return _get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _parse_txt_files():
    """
    Read all documents/*.txt files and return a list of dicts:
        { "capability": str, "text": str }

    Each file is split on $$$||| and the first non-empty line of each section
    is the capability name.  The rest of the lines are example phrases.
    """
    entries = []
    for filepath in sorted(DOCUMENTS_DIR.glob("*.txt")):
        raw = filepath.read_text(encoding="utf-8")
        sections = raw.split("$$$|||")
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = [l.strip() for l in section.splitlines() if l.strip()]
            if not lines:
                continue
            capability = lines[0]
            # Full text stored in ChromaDB (capability name + all phrases)
            text = "\n".join(lines)
            entries.append({"capability": capability, "text": text})
    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def seed_collections(force: bool = False):
    """
    Populate ChromaDB collections from documents/*.txt files.

    Idempotent by default — skips seeding if a collection already has data.
    Pass force=True to wipe and re-seed every run.
    """
    client = _get_client()

    # Initialise all collections
    collections = {name: _get_collection(name) for name in COLLECTION_MAP}

    if not force:
        # Check if already seeded (any collection has documents)
        total = sum(col.count() for col in collections.values())
        if total > 0:
            return  # Already seeded

    if force:
        # Wipe existing data
        for name in COLLECTION_MAP:
            client.delete_collection(name)
        collections = {name: _get_collection(name) for name in COLLECTION_MAP}

    entries = _parse_txt_files()

    # Group by collection
    batches: dict[str, list] = {name: [] for name in COLLECTION_MAP}
    for entry in entries:
        col_name = CAPABILITY_TO_COLLECTION.get(entry["capability"])
        if col_name:
            batches[col_name].append(entry)
        else:
            # Unknown capability — put in video_editing as fallback
            batches["video_editing"].append(entry)

    # Add to ChromaDB (no external embeddings needed — chroma handles it)
    for col_name, items in batches.items():
        if not items:
            continue
        col = collections[col_name]
        col.add(
            ids=[f"{col_name}_{i}" for i in range(len(items))],
            documents=[item["text"] for item in items],
            metadatas=[{"capability": item["capability"]} for item in items],
        )

    print(f"ChromaDB seeded: {sum(len(v) for v in batches.values())} entries across {len(COLLECTION_MAP)} collections.")


def load_all_chunks():
    """
    Return all stored documents as a flat list of dicts:
        { "text": str, "capability": str }

    Used by vibevideo.py to populate the FAISS in-memory index.
    """
    chunks = []
    for col_name in COLLECTION_MAP:
        col = _get_collection(col_name)
        results = col.get(include=["documents", "metadatas"])
        for doc, meta in zip(results["documents"], results["metadatas"]):
            chunks.append({
                "text": doc,
                "capability": meta.get("capability", ""),
                "collection": col_name,
            })
    return chunks


def search_collection(collection_name: str, query_embedding, top_k: int = 1):
    """
    Search a specific collection using a pre-computed numpy embedding.
    Returns list of (document_text, capability, distance).
    """
    col = _get_collection(collection_name)
    results = col.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append((doc, meta.get("capability", ""), dist))
    return output


def search_all_collections(query_embedding, top_k: int = 1):
    """
    Search every collection and return the single globally best match.
    Returns (document_text, capability, collection_name, distance).
    """
    best = None
    for col_name in COLLECTION_MAP:
        results = search_collection(col_name, query_embedding, top_k=1)
        if not results:
            continue
        doc, capability, dist = results[0]
        if best is None or dist < best[3]:
            best = (doc, capability, col_name, dist)
    return best
