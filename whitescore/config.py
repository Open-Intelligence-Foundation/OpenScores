"""Tunable settings for discovery, benchmarks and score weights.

Every value here can be overridden with an environment variable of the same
name where that makes sense (see ``env_int`` / ``env_float`` usage below).
"""
from __future__ import annotations

import os


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Measurement windows (days)
# ---------------------------------------------------------------------------
WINDOW_DAYS = 90          # rolling window T for health / popularity growth
MAINTAINER_WINDOW_DAYS = 180
RELEASE_WINDOW_DAYS = 365
STALE_ISSUE_DAYS = 180

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
# GitHub topics that identify AI-related repositories. Each topic is searched
# separately (sorted by stars) and the results are merged and de-duplicated.
AI_TOPICS = [
    # language models & inference
    "llm", "llms", "large-language-models", "llm-inference", "llm-serving", "llmops",
    "language-model", "text-generation", "quantization", "gguf", "ollama", "vllm",
    "openai", "chatgpt", "gpt", "gpt-4", "gpt4", "claude", "gemini", "llama", "llama2", "llama3",
    "mistral", "qwen", "deepseek", "gemma", "huggingface", "transformers", "transformer",
    # agents, orchestration, RAG
    "ai-agents", "agents", "agent", "agentic-ai", "agentic", "autonomous-agents", "llm-agents",
    "multi-agent", "multi-agent-systems", "agent-framework", "mcp", "model-context-protocol",
    "rag", "retrieval-augmented-generation", "vector-database", "vector-search", "vectordb",
    "embeddings", "langchain", "llamaindex", "prompt-engineering", "prompt", "function-calling",
    # assistants, chat, coding
    "ai-assistant", "chatbot", "chatbots", "copilot", "code-generation", "ai-coding",
    "coding-assistant", "ai-chatbot", "chat", "assistant",
    # general ML / DL
    "machine-learning", "deep-learning", "neural-network", "neural-networks",
    "artificial-intelligence", "ai", "generative-ai", "genai", "pytorch", "tensorflow", "jax",
    "keras", "scikit-learn", "automl", "fine-tuning", "finetuning", "lora", "peft", "rlhf",
    "distributed-training", "model-serving", "inference", "onnx", "cuda", "triton",
    # vision & generative media
    "computer-vision", "object-detection", "image-segmentation", "segmentation", "yolo", "ocr",
    "face-recognition", "pose-estimation", "image-classification", "vision-language-model", "vlm",
    "multimodal", "stable-diffusion", "diffusion-models", "diffusion", "text-to-image",
    "text-to-video", "image-generation", "video-generation", "ai-art", "comfyui", "3d-generation",
    "gaussian-splatting", "nerf", "gan", "generative-adversarial-network", "image-editing",
    "super-resolution", "autonomous-driving", "medical-imaging",
    # nlp, speech, audio
    "nlp", "natural-language-processing", "bert", "sentence-embeddings", "named-entity-recognition",
    "machine-translation", "question-answering", "speech-recognition", "speech-to-text",
    "text-to-speech", "tts", "asr", "whisper", "speech-synthesis", "voice-cloning", "voice",
    "audio-generation", "music-generation", "speaker-recognition",
    # RL, robotics, science
    "reinforcement-learning", "deep-reinforcement-learning", "robotics", "gym", "gymnasium",
    "graph-neural-networks", "time-series", "anomaly-detection", "recommender-system",
    "recommendation-system", "knowledge-graph", "federated-learning", "drug-discovery", "bioinformatics",
    # data, mlops, evaluation, safety
    "mlops", "data-science", "experiment-tracking", "feature-store", "model-management",
    "llm-evaluation", "evaluation", "benchmark", "ai-safety", "interpretability", "explainable-ai",
    "ai-observability", "llm-observability", "guardrails", "data-labeling", "annotation-tool",
    "synthetic-data", "dataset", "jupyter", "notebook",
]

# Topics that almost everything AI-adjacent carries. They count for very little
# when categorizing and when judging whether a repository is really an AI project.
GENERIC_TOPICS = {
    "ai", "artificial-intelligence", "generative-ai", "genai", "llm", "llms", "large-language-models",
    "gpt", "gpt-4", "gpt4", "chatgpt", "openai", "claude", "gemini", "llama", "llama2", "llama3", "mistral",
    "qwen", "deepseek", "gemma", "ollama", "huggingface", "machine-learning", "deep-learning",
    "chat", "assistant", "agent", "agents", "prompt", "voice", "inference", "dataset", "benchmark",
    "evaluation", "notebook", "jupyter", "cuda", "gpu", "data-science", "python", "typescript",
    "javascript", "rust", "go", "api", "cli", "open-source", "self-hosted", "time-series", "monitoring",
    "observability", "analytics", "search-engine", "knowledge-graph", "bioinformatics", "simulation",
    "anomaly-detection", "recommender-system", "recommendation-system", "drug-discovery", "nextjs", "react",
    "electron", "tauri", "ui", "gui", "frontend", "library", "platform", "database", "docker", "kubernetes",
    "automation", "workflow", "productivity", "desktop", "mobile", "android", "ios", "macos", "windows",
    "linux", "web", "app", "tool", "tools", "framework", "sdk", "plugin", "extension", "chrome-extension",
    "vscode-extension", "markdown", "pdf", "json", "sql", "hacktoberfest", "awesome", "research", "paper",
    "testing", "deployment", "pipeline", "dashboard", "visualization", "statistics", "optimization",
}

# Name/description keyword searches catch well-known repositories that carry no
# topics at all (llama.cpp, whisper, LibreChat ...). Run with a higher star floor.
KEYWORD_QUERIES = [
    "llm", "large language model", "language model", "machine learning", "deep learning",
    "neural network", "artificial intelligence", "ai agent", "ai agents", "agentic", "chatgpt", "gpt",
    "openai", "anthropic", "claude", "gemini", "ollama", "llama", "transformer", "diffusion",
    "stable diffusion", "text-to-speech", "speech recognition", "whisper", "computer vision",
    "object detection", "embedding", "embeddings", "rag", "vector database", "fine-tuning", "finetune",
    "reinforcement learning", "generative ai", "copilot", "coding agent", "mcp server",
    "model context protocol", "inference engine", "vision language", "multimodal", "ai-powered",
]
CATALOG_KEYWORD_MIN_STARS = env_int("CATALOG_KEYWORD_MIN_STARS", 1000)
CATALOG_MIN_SIGNAL = env_int("CATALOG_MIN_SIGNAL", 2)   # below this a repo is only "AI-adjacent"

# Repositories that are always tracked even if topic search misses them.
SEED_REPOS = [
    "pytorch/pytorch", "tensorflow/tensorflow", "huggingface/transformers",
    "ggml-org/llama.cpp", "ollama/ollama", "vllm-project/vllm",
    "langchain-ai/langchain", "run-llama/llama_index", "openai/whisper",
    "AUTOMATIC1111/stable-diffusion-webui", "comfyanonymous/ComfyUI",
    "scikit-learn/scikit-learn", "jax-ml/jax", "keras-team/keras",
    "microsoft/DeepSpeed", "ray-project/ray", "mlflow/mlflow",
    "ultralytics/ultralytics", "opencv/opencv", "deepseek-ai/DeepSeek-V3",
    "LibreChat-AI/LibreChat", "lobehub/lobehub", "ggml-org/whisper.cpp", "microsoft/autogen",
    "crewAIInc/crewAI", "browser-use/browser-use", "infiniflow/ragflow", "langgenius/dify",
    "Mintplex-Labs/anything-llm", "black-forest-labs/flux", "facebookresearch/segment-anything",
    "Stability-AI/generative-models", "openai/openai-python", "anthropics/anthropic-sdk-python",
    "google-deepmind/deepmind-research", "NVIDIA/TensorRT-LLM", "sgl-project/sglang",
    "huggingface/diffusers", "huggingface/peft", "huggingface/trl", "hiyouga/LLaMA-Factory",
    "QwenLM/Qwen3", "meta-llama/llama", "mistralai/mistral-inference", "google-gemini/cookbook",
    "openai/gpt-oss", "modelcontextprotocol/servers", "aider-ai/aider", "TabbyML/tabby",
    "continuedev/continue", "cline/cline", "OpenHands/OpenHands", "deepseek-ai/DeepSeek-R1",
    "exo-explore/exo", "LMStudio-ai/lms", "mozilla-ai/llamafile", "apple/ml-fastvlm",
]

MIN_STARS = env_int("MIN_STARS", 500)           # discovery threshold for the leaderboard
CATALOG_MIN_STARS = env_int("CATALOG_MIN_STARS", 200)  # threshold for the full catalog sweep
INCLUDE_CURATED_LISTS = env_bool("INCLUDE_CURATED_LISTS", False)  # track awesome-lists on the leaderboard?
MAX_REPOS = env_int("MAX_REPOS", 300)           # cap on tracked repos per run
PAGES_PER_TOPIC = env_int("PAGES_PER_TOPIC", 2)  # 100 results per page
REQUIRE_RECOGNIZED_LICENSE = env_bool("REQUIRE_RECOGNIZED_LICENSE", True)
MAX_COMMIT_PAGES = env_int("MAX_COMMIT_PAGES", 5)  # 100 commits per page
WORKERS = env_int("WORKERS", 3)
HISTORY_MAX_POINTS = env_int("HISTORY_MAX_POINTS", 400)

# Category rules. Each category lists topics (weight 2) and description keywords
# (weight 1). A repository gets the category with the highest total; ties go to
# the earlier rule. Curated lists are detected separately (see discover.py).
CATEGORY_RULES = [
    ("AI Coding Assistants", {
        "topics": {"copilot", "code-generation", "ai-coding", "coding-assistant", "code-assistant",
                   "coding-agent", "code-completion", "pair-programming", "code-review", "developer-tools",
                   "ide", "vscode-extension", "swe-bench", "code-llm"},
        "keywords": {"coding assistant", "coding agent", "code generation", "pair programm", "in your terminal",
                     "ide ", "vs code", "vscode", "software engineer", "write code", "code completion", "codebase",
                     "terminal", "code review", "programming", "developer", "cursor", "claude code", "codex"}}),
    ("Agents & Orchestration", {
        "topics": {"ai-agents", "agents", "agent", "agentic-ai", "agentic", "autonomous-agents", "llm-agents",
                   "multi-agent", "multi-agent-systems", "agent-framework", "mcp", "model-context-protocol",
                   "langchain", "llm-framework", "workflow", "automation", "function-calling", "tool-use",
                   "browser-automation", "computer-use", "ai-workflow", "llm-apps", "llm-application"},
        "keywords": {"agent", "orchestrat", "workflow", "automate", "multi-agent", "tool calling", "mcp server"}}),
    ("RAG & Vector Search", {
        "topics": {"rag", "retrieval-augmented-generation", "vector-database", "vector-search", "vectordb",
                   "embeddings", "sentence-embeddings", "semantic-search", "llamaindex", "knowledge-base",
                   "document-qa", "similarity-search", "ann", "nearest-neighbor-search", "knowledge-graph",
                   "graphrag", "search-engine", "information-retrieval"},
        "keywords": {"retrieval", "rag ", "vector", "embedding", "knowledge base", "semantic search",
                     "chat with your", "documents", "search engine"}}),
    ("Chat UIs & Assistants", {
        "topics": {"ai-assistant", "chatbot", "chatbots", "ai-chatbot", "chat", "assistant", "chatgpt-ui",
                   "chat-ui", "chatgpt-app", "desktop-app", "webui", "web-ui", "ui", "gui", "frontend",
                   "voice-assistant", "personal-assistant", "telegram-bot", "discord-bot", "slack-bot",
                   "electron", "tauri", "nextjs", "react"},
        "keywords": {"chat ui", "chat interface", "web ui", "webui", "interface", "desktop app", "assistant",
                     "chatgpt clone", "chatbot", "telegram", "discord", "whatsapp", "frontend", "gui", "client",
                     "user-friendly", "chat with"}}),
    ("LLMs & Inference", {
        "topics": {"llm", "llms", "large-language-models", "llm-inference", "llm-serving", "inference",
                   "llama", "llama2", "llama3", "gpt", "gpt-4", "gpt4", "chatgpt", "openai", "claude", "gemini",
                   "language-model", "text-generation", "llmops", "quantization", "gguf", "mistral", "qwen",
                   "deepseek", "gemma", "model-serving", "ollama", "vllm", "inference-engine", "tensorrt",
                   "openai-api", "api-gateway", "llm-gateway", "llm-proxy", "prompt-engineering", "prompt",
                   "prompts", "foundation-models", "moe", "mixture-of-experts", "kv-cache", "speculative-decoding"},
        "keywords": {"language model", "llm", "inference", "serving", "gpt", "chatgpt", "openai", "prompt",
                     "tokens", "quantiz", "run locally", "local llm"}}),
    ("Fine-tuning & Alignment", {
        "topics": {"fine-tuning", "finetuning", "lora", "qlora", "peft", "rlhf", "dpo", "alignment",
                   "instruction-tuning", "sft", "pretraining", "pre-training", "training", "distributed-training",
                   "llm-training", "ai-safety", "red-teaming", "guardrails", "interpretability", "explainable-ai",
                   "mechanistic-interpretability", "jailbreak", "prompt-injection"},
        "keywords": {"fine-tun", "finetun", "lora", "rlhf", "alignment", "pretrain", "pre-train", "train llm",
                     "safety", "guardrail", "jailbreak", "interpretab", "red team"}}),
    ("Generative Media", {
        "topics": {"stable-diffusion", "diffusion-models", "diffusion", "image-generation", "text-to-image",
                   "text-to-video", "video-generation", "ai-art", "generative-art", "comfyui", "3d-generation",
                   "text-to-3d", "gaussian-splatting", "nerf", "gan", "generative-adversarial-network",
                   "image-editing", "inpainting", "super-resolution", "image-restoration", "deepfake",
                   "faceswap", "animation", "flux", "midjourney", "dalle", "sdxl", "controlnet", "lora-models",
                   "audio-generation", "music-generation"},
        "keywords": {"diffusion", "image generation", "text-to-image", "text to image", "video generation",
                     "generate images", "stable diffusion", "art", "3d", "upscal", "deepfake", "face swap",
                     "music generation"}}),
    ("Speech & Audio", {
        "topics": {"speech-recognition", "speech-to-text", "text-to-speech", "tts", "asr", "whisper", "speech",
                   "speech-synthesis", "voice-cloning", "voice", "voice-conversion", "audio", "audio-processing",
                   "speaker-recognition", "speaker-diarization", "voice-assistant", "podcast", "transcription",
                   "sound", "music", "singing-voice-synthesis"},
        "keywords": {"speech", "voice", "text-to-speech", "text to speech", "audio", "transcri", "tts", "asr",
                     "whisper", "music", "sound"}}),
    ("Computer Vision", {
        "topics": {"computer-vision", "object-detection", "image-segmentation", "segmentation", "yolo", "ocr",
                   "face-recognition", "face-detection", "pose-estimation", "image-classification", "vision",
                   "image-processing", "opencv", "detection", "tracking", "object-tracking", "depth-estimation",
                   "3d-reconstruction", "slam", "autonomous-driving", "self-driving-cars", "medical-imaging",
                   "remote-sensing", "vision-language-model", "vlm", "multimodal", "video-understanding",
                   "document-ai", "document-understanding", "layout-analysis", "visual-question-answering",
                   "anomaly-detection"},
        "keywords": {"vision", "image", "detection", "segmentation", "ocr", "face", "video", "camera", "visual",
                     "multimodal", "document parsing", "pdf"}}),
    ("NLP", {
        "topics": {"nlp", "natural-language-processing", "bert", "named-entity-recognition", "text-classification",
                   "machine-translation", "translation", "question-answering", "summarization", "tokenizer",
                   "tokenization", "information-extraction", "sentiment-analysis", "text-mining", "spacy",
                   "text-processing", "word2vec", "topic-modeling", "linguistics", "grammar", "chinese-nlp"},
        "keywords": {"nlp", "natural language", "text classification", "translation", "named entity",
                     "tokeniz", "sentiment", "linguistic", "text analysis"}}),
    ("Reinforcement Learning & Robotics", {
        "topics": {"reinforcement-learning", "deep-reinforcement-learning", "rl", "robotics", "robot", "gym",
                   "gymnasium", "simulation", "simulator", "embodied-ai", "imitation-learning", "ros", "drone",
                   "game-ai", "multi-agent-reinforcement-learning", "self-driving", "control", "manipulation",
                   "humanoid", "isaac-sim", "mujoco"},
        "keywords": {"reinforcement", "robot", "simulat", "policy", "embodied", "gym", "environment",
                     "game"}}),
    ("ML Frameworks & Training", {
        "topics": {"machine-learning", "deep-learning", "neural-network", "neural-networks", "pytorch", "tensorflow",
                   "jax", "keras", "scikit-learn", "sklearn", "automl", "gradient-boosting", "xgboost", "autograd",
                   "tensor", "compiler", "cuda", "gpu", "triton", "onnx", "tensorrt", "hpc", "numpy", "mlx",
                   "deep-learning-framework", "neural-architecture-search", "graph-neural-networks", "gnn",
                   "time-series", "forecasting", "recommender-system", "recommendation-system", "federated-learning",
                   "optimization", "bayesian", "probabilistic-programming", "statistics", "tabular-data",
                   "drug-discovery", "bioinformatics", "protein", "chemistry", "physics", "scientific-computing",
                   "transformers", "transformer", "huggingface", "attention", "flash-attention"},
        "keywords": {"machine learning", "deep learning", "neural network", "pytorch", "tensorflow", "ml framework",
                     "training", "gpu", "tensor", "forecast", "recommend", "graph neural", "gradient", "autograd"}}),
    ("Data, MLOps & Evaluation", {
        "topics": {"mlops", "data-science", "experiment-tracking", "feature-store", "model-management",
                   "model-registry", "llm-evaluation", "evaluation", "benchmark", "benchmarks", "leaderboard",
                   "ai-observability", "llm-observability", "observability", "monitoring", "tracing",
                   "data-labeling", "annotation-tool", "annotation", "labeling", "synthetic-data", "dataset",
                   "datasets", "data-pipeline", "etl", "data-engineering", "data-quality", "data-validation",
                   "jupyter", "notebook", "notebooks", "kubernetes", "deployment", "serverless", "pipeline",
                   "data-versioning", "dvc", "feature-engineering", "analytics", "visualization", "dashboard",
                   "ai-gateway", "cost-tracking", "prompt-management", "testing"},
        "keywords": {"mlops", "evaluat", "benchmark", "observab", "llm monitor", "tracing", "label", "annotation",
                     "dataset", "ml pipeline", "deploy", "experiment", "data science", "notebook",
                     "lifecycle", "versioning", "feature store", "model registry"}}),
    ("Research Code & Models", {
        "topics": {"model", "models", "pretrained-models", "foundation-model", "foundation-models", "weights",
                   "checkpoint", "open-source-models", "open-weights", "model-zoo", "sota", "paper", "research",
                   "arxiv", "cvpr", "neurips", "iclr", "icml", "acl", "emnlp", "eccv", "iccv", "aaai", "siggraph"},
        "keywords": {"official implementation", "official repo", "official code", "official pytorch",
                     "implementation of", "weights", "checkpoints", "technical report", "pretrained", "model zoo",
                     "sota", "state-of-the-art", "[cvpr", "[neurips", "[iclr", "[icml", "[acl", "[emnlp", "[eccv",
                     "[iccv", "[aaai", "[siggraph", "arxiv", "paper"}}),
    ("AI Applications & Tools", {
        "topics": {"ai", "artificial-intelligence", "generative-ai", "genai", "ai-tools", "productivity",
                   "browser-extension", "chrome-extension", "mobile", "ios", "android", "macos", "windows",
                   "desktop", "cli", "terminal", "writing", "education", "translation-tool", "note-taking",
                   "game", "health", "finance", "trading", "legal", "marketing", "no-code", "low-code", "saas"},
        "keywords": {"ai-powered", "ai powered", "powered by", "app", "tool", "extension", "plugin", "generate",
                     "productivity", "free", "open-source alternative", "alternative to"}}),
]
CURATED_LIST_CATEGORY = "Courses, Papers & Curated Lists"
DEFAULT_CATEGORY = "AI (General)"

# ---------------------------------------------------------------------------
# Popularity benchmarks (the value at which a metric saturates to 100).
# These are tuned for the AI ecosystem, where star counts are large.
# ---------------------------------------------------------------------------
POPULARITY_BENCHMARKS = {
    "stars": env_int("BENCH_STARS", 50_000),
    "star_growth": env_int("BENCH_STAR_GROWTH", 5_000),
    "forks": env_int("BENCH_FORKS", 10_000),
    "fork_growth": env_int("BENCH_FORK_GROWTH", 1_000),
    "watchers": env_int("BENCH_WATCHERS", 1_000),
    "contributors": env_int("BENCH_CONTRIBUTORS", 500),
    "external_engagement": env_int("BENCH_EXTERNAL", 1_000),
}

# ---------------------------------------------------------------------------
# Score weights. Each dict must sum to 1.0.
# ---------------------------------------------------------------------------
MATURITY_WEIGHTS = {
    "age": 0.10, "releases": 0.15, "documentation": 0.15, "governance": 0.15,
    "ci_tests": 0.15, "maintainers": 0.10, "versioning": 0.10, "compatibility": 0.10,
}
HEALTH_WEIGHTS = {
    "commit_activity": 0.15, "issue_response": 0.15, "pr_response": 0.15,
    "issue_closure": 0.15, "pr_merge": 0.10, "backlog": 0.10,
    "contributor_diversity": 0.10, "release_freshness": 0.05, "ci_reliability": 0.05,
}
POPULARITY_WEIGHTS = {
    "stars": 0.25, "star_growth": 0.20, "forks": 0.15, "fork_growth": 0.10,
    "watchers": 0.10, "contributors": 0.10, "external_engagement": 0.10,
}
RISK_WEIGHTS = {
    "bus_factor": 0.20, "concentration": 0.15, "commit_staleness": 0.15,
    "release_staleness": 0.10, "security": 0.10, "stale_issues": 0.10,
    "ownership": 0.10, "archived": 0.10,
}
SUSTAINABILITY_WEIGHTS = {
    "maintainers": 0.20, "maintainer_diversity": 0.15, "retention": 0.15,
    "sponsorship": 0.10, "org_backing": 0.10, "governance": 0.10,
    "release_consistency": 0.10, "workload": 0.10,
}
# Overall White Score used for the default leaderboard ranking: the core suite
# (maturity, health, popularity) equally weighted.
OVERALL_WEIGHTS = {"maturity": 1 / 3, "health": 1 / 3, "popularity": 1 / 3}

# Bot accounts to ignore when counting humans.
BOT_LOGINS = {
    "dependabot", "dependabot[bot]", "github-actions", "github-actions[bot]",
    "renovate", "renovate[bot]", "pre-commit-ci", "pre-commit-ci[bot]",
    "allcontributors[bot]", "codecov", "codecov[bot]", "copilot", "web-flow",
    "mergify[bot]", "stale[bot]", "imgbot[bot]", "snyk-bot", "greenkeeper[bot]",
}
