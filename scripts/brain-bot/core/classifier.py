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
        "Going to the gym for a full body workout with deadlifts squats and bench press followed by stretching and foam rolling",
        "Tracking my daily calorie intake and meal prepping chicken rice and vegetables for the whole week to stay on my nutrition plan",
        "Struggling with insomnia lately need to improve my sleep hygiene by cutting screen time and maintaining a consistent bedtime routine",
        "Booked a doctor appointment for my annual physical checkup including blood work and dental cleaning this month",
        "Morning meditation and yoga session for twenty minutes focusing on breathwork and mindfulness to reduce stress and anxiety",
    ],
    "Wealth & Finance": [
        "Reviewing my investment portfolio rebalancing between index funds bonds and crypto allocations to optimize for long term growth",
        "Setting up a monthly budget tracking income expenses savings rate and working toward eliminating credit card debt completely",
        "Exploring side hustle opportunities like freelancing consulting or building a SaaS product to create additional income streams",
        "Researching real estate investment properties analyzing cap rates rental yields and mortgage rates in target neighborhoods",
        "Tax planning season organizing receipts maximizing deductions and contributing to retirement accounts before the deadline",
    ],
    "Relationships": [
        "Planning a dinner date with my partner this weekend trying that new Italian restaurant downtown for our anniversary celebration",
        "Need to catch up with old college friends organizing a group hangout or video call to maintain those important friendships",
        "Family gathering this holiday coordinating travel plans gifts and making sure to spend quality time with parents and siblings",
        "Working on communication skills with my partner setting healthy boundaries and practicing active listening in conversations",
        "Meeting a new mentor for coffee this week to discuss career growth and build my professional network connections",
    ],
    "Mind & Growth": [
        "Reading a new book on cognitive psychology taking detailed notes and connecting ideas to my existing mental models knowledge base",
        "Enrolled in an online course on machine learning spending two hours daily on lectures practice problems and project work",
        "Deep personal reflection journaling about my values beliefs and life philosophy questioning assumptions and seeking deeper understanding",
        "Listening to podcasts about stoicism productivity and self improvement applying key takeaways to daily habits and routines",
        "Writing a detailed article synthesizing research from multiple sources developing critical thinking and improving communication skills",
    ],
    "Purpose & Impact": [
        "Working on my career mission statement clarifying what legacy I want to leave and how my work contributes to society",
        "Volunteering at the local community center teaching coding workshops to underprivileged youth making a positive social impact",
        "Building my portfolio project that solves a real problem for people combining technical skills with meaningful purpose and mission",
        "Mentoring junior developers at work sharing knowledge and experience to help them grow while strengthening my own leadership skills",
        "Brainstorming creative side projects that align with my passions and values exploring ways to turn purpose into sustainable work",
    ],
    "Systems & Environment": [
        "Setting up automated workflows with scripts and tools to streamline repetitive tasks and improve daily productivity systems",
        "Decluttering and reorganizing my home workspace optimizing desk layout lighting and ergonomics for better focus and comfort",
        "Building a morning routine habit stack with specific triggers and rewards tracking consistency in my habit tracker app",
        "Upgrading my tech setup installing new software configuring development environment and maintaining hardware infrastructure",
        "Optimizing my time management system reviewing weekly planning process adjusting priorities and eliminating efficiency bottlenecks",
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

        # Tier 1: Keyword match
        keyword_scores = self._tier_keywords(text)
        if keyword_scores and keyword_scores[0].confidence >= 0.8:
            result.matches = keyword_scores
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Tier 1.5: Zero-shot classification
        zero_shot_scores = self._tier_zero_shot(text)
        if zero_shot_scores and zero_shot_scores[0].confidence >= 0.75:
            result.matches = self._merge_scores(keyword_scores, zero_shot_scores)
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Tier 2: Embedding similarity
        embedding_scores = self._tier_embedding(text)
        if embedding_scores and embedding_scores[0].confidence >= 0.7:
            # Merge with any weak keyword matches
            result.matches = self._merge_scores(keyword_scores, embedding_scores)
            result.execution_time_ms = (time.monotonic() - start) * 1000
            return result

        # Tier 3: Claude LLM
        llm_scores = self._tier_llm(text)
        if llm_scores:
            result.matches = self._merge_scores(
                self._merge_scores(keyword_scores, embedding_scores),
                llm_scores,
            )
        else:
            # Use whatever we have from earlier tiers
            result.matches = self._merge_scores(keyword_scores, embedding_scores)

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
                if sim < 0.28:
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
