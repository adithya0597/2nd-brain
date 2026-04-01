"""Hybrid 5-tier message classification pipeline.

Tiers:
  0 — Noise filter (greetings, small talk)
  1 — Keyword matching (enhanced, dynamic from DB)
  1.5 — Zero-shot classification (cosine similarity against ICOR references)
  2 — Embedding similarity (sentence-transformers, lazy-loaded)
  3 — Claude LLM fallback (Haiku, cost-optimized)
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field


import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton Anthropic client for Tier 3 classification
# ---------------------------------------------------------------------------

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            import anthropic
            _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    dimension: str
    confidence: float
    method: str  # "keyword" | "embedding" | "llm"


@dataclass
class ClassificationResult:
    matches: list[DimensionScore] = field(default_factory=list)
    is_noise: bool = False
    is_actionable: bool = False
    execution_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = re.compile(
    r"^(good\s+(morning|afternoon|evening|night)|"
    r"hey(\s+what'?s\s+up)?|hello(\s+there)?|hi(\s+there)?|yo|sup|"
    r"what'?s\s+up|how'?s\s+it\s+going|how\s+are\s+you|"
    r"thanks|thank you|ok thanks|ok|okay|cool|nice|great|sure|yep|yup|nope|"
    r"gm|gn|bye|later|cheers|lol|haha)[\s!.?]*$",
    re.IGNORECASE,
)

_ACTION_PATTERNS = re.compile(
    r"\b(need to|should|must|todo|action|reminder|deadline|follow.up|"
    r"schedule|book|call|email|buy|pay|submit|send)\b",
    re.IGNORECASE,
)

# Reference texts per dimension for embedding similarity.
# Each dimension has 5 descriptive reference texts (20-30 words each)
# designed for maximum discrimination between dimensions.
# Embedding model is configurable via config.EMBEDDING_MODEL (shared with embedding_store).
_DIMENSION_REFERENCES: dict[str, list[str]] = {
    "Health & Vitality": [
        "Going to the gym for a workout hitting legs doing squats deadlifts and pushups then stretching and foam rolling",
        "Start every day with pushups squats and pull ups as a morning exercise routine to stay fit and active",
        "Woke up late from a bad nap and felt gloomy but forced myself to work out anyway to fix my energy and mood",
        "Checking my whoop band stats and health tracker data to monitor sleep recovery heart rate and daily fitness",
        "Struggling with sleep hygiene and insomnia need a consistent bedtime routine and less screen time before bed",
    ],
    "Wealth & Finance": [
        "Applying for jobs sending applications and going through interviews to get hired and earn a salary income",
        "LinkedIn outreach reaching out to hiring managers and recruiters to find job openings for financial stability",
        "Creating a demo video and sending it to a company recruiter as part of the job hiring process first round",
        "Automating job scraping job fit analysis and job applications to speed up the job search and get hired faster",
        "Had a hard day trying to automate my job search and application process but results with nothing but failure",
    ],
    "Relationships": [
        "Planning to meet up with friends or family for dinner catching up and spending quality time together",
        "Had a call with a professional contact or mentor to get guidance on networking and career strategy",
        "A director or recruiter from a company reached out on LinkedIn and wants to have a conversation with me",
        "Working on communication and setting healthy boundaries in personal and professional relationships",
        "Catching up with old friends organizing a group hangout or video call to maintain friendships",
    ],
    "Mind & Growth": [
        "Reading a book or article taking notes and connecting ideas to my existing knowledge and mental models",
        "Studying and prepping nonstop for technical interviews grinding problems and practicing algorithms",
        "Found an interesting resource or research paper that I want to read and learn from to grow my knowledge",
        "Learning a new technology platform like Microsoft Fabric or a cloud ecosystem to build my skills",
        "Deep personal reflection and journaling about values beliefs and life philosophy for self improvement",
    ],
    "Purpose & Impact": [
        "Writing a LinkedIn post sharing thought leadership about how data engineers need knowledge graphs and AI",
        "Volunteering at a community center teaching coding workshops to help underprivileged youth learn technology",
        "Working on my career mission clarifying what legacy I want to leave and how my work helps society at large",
        "Mentoring junior developers sharing knowledge and experience to help them grow in their engineering careers",
        "Contributing to open source projects or creating public educational content that benefits the community",
    ],
    "Systems & Environment": [
        "Building and coding my second brain system implementing features like cosine similarity search and automation",
        "Setting up automated workflows scripts and tools to streamline repetitive tasks and productivity systems",
        "Designing an agent judging workflow for AI Product Council to evaluate when agents are doing productive work",
        "Planning and building a dashboard webapp or infrastructure project to improve my digital environment",
        "Implementing mathematical functions and algorithms for the knowledge graph like RRF and vector embeddings",
    ],
}


# ---------------------------------------------------------------------------
# Embedding cache (lazy-loaded)
# ---------------------------------------------------------------------------

_dimension_embeddings: dict[str, list] = {}


def _load_embedding_model():
    """Lazy-load embeddings for dimension references using shared model."""
    global _dimension_embeddings
    if _dimension_embeddings:
        return

    try:
        from core.embedding_store import _get_model, _truncate_vector
        model = _get_model()
        if model is None:
            return

        # Pre-encode dimension reference texts (truncate for Matryoshka)
        for dim, texts in _DIMENSION_REFERENCES.items():
            raw = model.encode(texts)
            _dimension_embeddings[dim] = [_truncate_vector(v) for v in raw]

        logger.info("Dimension embeddings loaded, %d dimensions encoded", len(_dimension_embeddings))
    except ImportError:
        logger.warning("embedding_store not available — falling back to direct model load")
        try:
            from sentence_transformers import SentenceTransformer
            model_name = getattr(config, "EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            model = SentenceTransformer(model_name, trust_remote_code=True)
            from core.embedding_store import _truncate_vector
            for dim, texts in _DIMENSION_REFERENCES.items():
                raw = model.encode(texts)
                _dimension_embeddings[dim] = [_truncate_vector(v) for v in raw]
            logger.info("Fallback embedding model loaded: %s", model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed — embedding tier disabled")
    except Exception:
        logger.exception("Failed to load embedding model")


def _cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------------------------------------------------------------------------
# MessageClassifier
# ---------------------------------------------------------------------------

class MessageClassifier:
    """Hybrid 5-tier classification pipeline."""

    def __init__(self, keywords: dict[str, list[str]] | None = None):
        """Initialize with keyword dictionary.

        Args:
            keywords: Dimension -> keyword list mapping. If None, uses config.DIMENSION_KEYWORDS.
        """
        self._keywords = keywords or dict(config.DIMENSION_KEYWORDS)

    def update_keywords(self, keywords: dict[str, list[str]]):
        """Hot-swap keywords (e.g. after dynamic reload)."""
        self._keywords = keywords

    def classify(self, text: str) -> ClassificationResult:
        """Run the full classification pipeline with short-circuit."""
        start = time.monotonic()

        result = ClassificationResult()

        # Tier 0: Noise filter
        if self._tier_noise(text):
            result.is_noise = True
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Check actionability
        result.is_actionable = self._check_actionable(text)

        # Tier 1: Keyword match (always collected, never short-circuits alone)
        keyword_scores = self._tier_keywords(text)

        # Tier 2: Embedding similarity (always run to catch additional dimensions)
        embedding_scores = self._tier_embedding(text)

        # Merge: keywords take priority, embeddings add NEW dimensions only
        keyword_dims = {s.dimension for s in keyword_scores}
        extra_embedding = [s for s in embedding_scores if s.dimension not in keyword_dims]
        merged = keyword_scores + extra_embedding
        merged.sort(key=lambda s: s.confidence, reverse=True)

        if merged:
            result.matches = merged
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Tier 1.5: Zero-shot classification (fallback when no keywords or embeddings matched)
        zero_shot_scores = self._tier_zero_shot(text)
        if zero_shot_scores:
            result.matches = zero_shot_scores
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Tier 3: Claude LLM (last resort)
        llm_scores = self._tier_llm(text)
        if llm_scores:
            result.matches = llm_scores

        result.execution_time_ms = (time.monotonic() - start) * 1000
        return result

    # -- Tier 0 --

    def _tier_noise(self, text: str) -> bool:
        return bool(_NOISE_PATTERNS.match(text.strip()))

    # -- Tier 1 --

    def _tier_keywords(self, text: str) -> list[DimensionScore]:
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for dimension, keywords in self._keywords.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                scores[dimension] = count

        if not scores:
            return []

        max_count = max(scores.values())
        num_matching_dims = len(scores)
        result = []
        for dim, count in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            # Confidence scaling:
            # - Base: 0.65 for 1 match, +0.15 per additional match, cap at 1.0
            # - Unambiguous boost: +0.15 if only one dimension matched
            confidence = min(1.0, 0.65 + (count - 1) * 0.15)
            if num_matching_dims == 1:
                confidence = min(1.0, confidence + 0.15)
            # Weak matches (less than half of top) get penalized
            if count < max(1, max_count // 2):
                continue
            result.append(DimensionScore(
                dimension=dim,
                confidence=round(confidence, 2),
                method="keyword",
            ))

        return result

    # -- Tier 1.5: Zero-shot classification --

    def _tier_zero_shot(self, text: str) -> list[DimensionScore]:
        """Zero-shot classification using cosine similarity against expanded ICOR references.

        Uses the shared embedding model from embedding_store. Falls back gracefully
        if unavailable.
        """
        try:
            from core.embedding_store import _get_model
            model = _get_model()
            if model is None:
                return []
        except ImportError:
            return []

        try:
            from core.embedding_store import _truncate_vector
            text_embedding = _truncate_vector(model.encode([text])[0])

            scores = []
            for dim, texts in _DIMENSION_REFERENCES.items():
                # Encode reference texts (cached after first call via _dimension_embeddings)
                if dim not in _dimension_embeddings:
                    raw = model.encode(texts)
                    _dimension_embeddings[dim] = [_truncate_vector(v) for v in raw]

                ref_embeddings = _dimension_embeddings[dim]
                sims = [_cosine_similarity(text_embedding, ref) for ref in ref_embeddings]
                max_sim = max(sims)
                scores.append((dim, max_sim))

            scores.sort(key=lambda x: x[1], reverse=True)

            result = []
            for i, (dim, sim) in enumerate(scores):
                if sim < 0.32:
                    break
                result.append(DimensionScore(
                    dimension=dim,
                    confidence=round(sim, 2),
                    method="zero_shot",
                ))
                # Multi-label: include second dimension if within 0.1 of top
                if i == 0:
                    continue
                if i == 1 and scores[0][1] - sim <= 0.1:
                    continue  # Keep this one
                break  # Stop after first significant gap

            return result
        except Exception:
            logger.exception("Zero-shot classification failed")
            return []

    # -- Tier 2 --

    def _tier_embedding(self, text: str) -> list[DimensionScore]:
        _load_embedding_model()
        if not _dimension_embeddings:
            return []

        try:
            from core.embedding_store import _get_model, _truncate_vector
            model = _get_model()
            if model is None:
                return []
            text_embedding = _truncate_vector(model.encode([text])[0])

            scores = []
            for dim, ref_embeddings in _dimension_embeddings.items():
                # Max similarity across reference texts for this dimension
                sims = [_cosine_similarity(text_embedding, ref) for ref in ref_embeddings]
                max_sim = max(sims)
                scores.append((dim, max_sim))

            scores.sort(key=lambda x: x[1], reverse=True)

            result = []
            for dim, sim in scores:
                if sim < 0.55:
                    break
                result.append(DimensionScore(
                    dimension=dim,
                    confidence=round(sim, 2),
                    method="embedding",
                ))

            return result
        except Exception:
            logger.exception("Embedding classification failed")
            return []

    # -- Tier 3 --

    def _tier_llm(self, text: str) -> list[DimensionScore]:
        client = _get_anthropic_client()
        if client is None:
            return []

        try:
            dimensions = ", ".join(config.DIMENSION_TOPICS.keys())
            response = client.messages.create(
                model=config.CLASSIFIER_LLM_MODEL,
                max_tokens=100,
                system=[
                    {
                        "type": "text",
                        "text": (
                            f"You classify text into life dimensions: {dimensions}. "
                            "If the text doesn't relate to any dimension, reply with ONLY 'none'. "
                            "Otherwise reply with a JSON array of objects: "
                            '[{"dimension": "...", "confidence": 0.0-1.0}]. '
                            "Reply with ONLY the JSON array or 'none', nothing else."
                        ),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Classify: {text}",
                    }
                ],
            )
            raw = response.content[0].text.strip()

            try:
                from core.token_logger import log_token_usage
                log_token_usage(response, caller="classifier_tier3", model=config.CLASSIFIER_LLM_MODEL)
            except Exception:
                pass

            if raw.lower() == "none":
                return []

            # Parse JSON response
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    result = []
                    for item in parsed:
                        dim_name = item.get("dimension", "")
                        conf = float(item.get("confidence", 0.5))
                        # Validate dimension name
                        for known_dim in config.DIMENSION_TOPICS:
                            if known_dim.lower() in dim_name.lower():
                                result.append(DimensionScore(
                                    dimension=known_dim,
                                    confidence=round(conf, 2),
                                    method="llm",
                                ))
                                break
                    return sorted(result, key=lambda s: s.confidence, reverse=True)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            # Fallback: try to match dimension name from raw text
            for dim in config.DIMENSION_TOPICS:
                if dim.lower() in raw.lower():
                    return [DimensionScore(dimension=dim, confidence=0.6, method="llm")]

            return []
        except Exception:
            logger.exception("LLM classification failed")
            return []

    # -- Helpers --

    def _check_actionable(self, text: str) -> bool:
        return bool(_ACTION_PATTERNS.search(text))

    @staticmethod
    def _merge_scores(
        a: list[DimensionScore], b: list[DimensionScore]
    ) -> list[DimensionScore]:
        """Merge two score lists, keeping highest confidence per dimension."""
        by_dim: dict[str, DimensionScore] = {}
        for score in (a or []) + (b or []):
            existing = by_dim.get(score.dimension)
            if not existing or score.confidence > existing.confidence:
                by_dim[score.dimension] = score
        return sorted(by_dim.values(), key=lambda s: s.confidence, reverse=True)
