"""Generate a clearly-labelled SAMPLE leaderboard for local site development.

The metrics are synthetic (seeded random), but they flow through the real
scoring code so the site renders exactly what a live run would produce.
Run:  python scripts/make_sample_data.py
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from whitescore import __version__, config, pipeline  # noqa: E402
from whitescore.discover import categorize  # noqa: E402

SAMPLE_REPOS = [
    ("pytorch/pytorch", "Tensors and dynamic neural networks in Python with strong GPU acceleration", "C++", ["deep-learning", "pytorch", "machine-learning", "gpu"]),
    ("huggingface/transformers", "State-of-the-art machine learning for PyTorch, TensorFlow and JAX", "Python", ["transformers", "nlp", "llm", "machine-learning"]),
    ("ggml-org/llama.cpp", "LLM inference in C/C++", "C++", ["llm", "llm-inference", "llama"]),
    ("ollama/ollama", "Get up and running with large language models locally", "Go", ["llm", "llama", "ollama"]),
    ("vllm-project/vllm", "A high-throughput and memory-efficient inference and serving engine for LLMs", "Python", ["llm", "inference", "llm-serving"]),
    ("langchain-ai/langchain", "Build context-aware reasoning applications", "Python", ["langchain", "agents", "llm"]),
    ("run-llama/llama_index", "Data framework for LLM applications", "Python", ["rag", "llm", "agents"]),
    ("comfyanonymous/ComfyUI", "The most powerful and modular diffusion model GUI", "Python", ["stable-diffusion", "comfyui", "diffusion-models"]),
    ("AUTOMATIC1111/stable-diffusion-webui", "Stable Diffusion web UI", "Python", ["stable-diffusion", "image-generation"]),
    ("openai/whisper", "Robust speech recognition via large-scale weak supervision", "Python", ["speech-recognition", "whisper", "audio"]),
    ("ultralytics/ultralytics", "YOLO object detection, segmentation and classification", "Python", ["computer-vision", "yolo", "object-detection"]),
    ("opencv/opencv", "Open Source Computer Vision Library", "C++", ["computer-vision", "image-processing"]),
    ("scikit-learn/scikit-learn", "Machine learning in Python", "Python", ["machine-learning", "scikit-learn", "data-science"]),
    ("jax-ml/jax", "Composable transformations of Python+NumPy programs", "Python", ["jax", "autograd", "gpu"]),
    ("keras-team/keras", "Deep learning for humans", "Python", ["deep-learning", "keras"]),
    ("mlflow/mlflow", "Open source platform for the machine learning lifecycle", "Python", ["mlops", "experiment-tracking"]),
    ("ray-project/ray", "Unified framework for scaling AI and Python applications", "Python", ["distributed-training", "machine-learning", "ray"]),
    ("microsoft/DeepSpeed", "Deep learning optimization library for distributed training and inference", "Python", ["deep-learning", "distributed-training"]),
    ("qdrant/qdrant", "High-performance vector database and search engine", "Rust", ["vector-database", "vector-search", "embeddings"]),
    ("chroma-core/chroma", "The AI-native open-source embedding database", "Rust", ["vector-database", "embeddings", "rag"]),
    ("Significant-Gravitas/AutoGPT", "AutoGPT is the vision of accessible AI for everyone", "Python", ["ai-agents", "autonomous-agents", "llm"]),
    ("crewAIInc/crewAI", "Framework for orchestrating role-playing, autonomous AI agents", "Python", ["ai-agents", "multi-agent", "llm"]),
    ("coqui-ai/TTS", "A deep learning toolkit for text-to-speech", "Python", ["text-to-speech", "tts", "speech-synthesis"]),
    ("Farama-Foundation/Gymnasium", "API standard for reinforcement learning environments", "Python", ["reinforcement-learning", "gymnasium"]),
    ("DLR-RM/stable-baselines3", "PyTorch implementations of reinforcement learning algorithms", "Python", ["reinforcement-learning", "pytorch"]),
    ("Lightning-AI/pytorch-lightning", "Pretrain, finetune and deploy AI models on multiple GPUs", "Python", ["deep-learning", "pytorch", "ai"]),
    ("unslothai/unsloth", "Finetune LLMs 2x faster with 70% less memory", "Python", ["fine-tuning", "llm", "lora"]),
    ("lm-sys/FastChat", "An open platform for training, serving and evaluating LLM-based chatbots", "Python", ["llm", "chatbot", "evaluation"]),
    ("deepfakes/faceswap", "Deepfakes software for all", "Python", ["deep-learning", "face-recognition", "computer-vision"]),
    ("PaddlePaddle/PaddleOCR", "Multilingual OCR toolkits based on PaddlePaddle", "Python", ["ocr", "computer-vision"]),
    ("explosion/spaCy", "Industrial-strength natural language processing in Python", "Python", ["nlp", "natural-language-processing"]),
    ("facebookresearch/segment-anything", "Segment Anything Model", "Jupyter Notebook", ["computer-vision", "segmentation"]),
    ("tinygrad/tinygrad", "You like pytorch? You like micrograd? You love tinygrad!", "Python", ["deep-learning", "autograd", "tensor"]),
    ("mozilla/DeepSpeech", "An open source embedded speech-to-text engine", "C++", ["speech-recognition", "deep-learning"]),
    ("facebookresearch/detectron2", "Next-generation platform for object detection and segmentation", "Python", ["computer-vision", "object-detection"]),
    ("dmlc/xgboost", "Scalable, portable and distributed gradient boosting", "C++", ["machine-learning", "gradient-boosting"]),
]


def synth_metrics(rng: random.Random, full_name: str, desc: str, lang: str, topics: list, now: datetime) -> dict:
    stars = int(rng.lognormvariate(10.2, 0.9))
    quality = rng.random()            # latent "how well run" factor
    activity = rng.random()           # latent "how alive" factor
    archived = rng.random() < 0.05
    org = rng.random() < 0.7
    age_months = rng.uniform(6, 120)
    commits_90d = 0 if archived else int(rng.lognormvariate(3.5 + 2 * activity, 0.6))
    maint = 0 if archived else max(1, int(rng.lognormvariate(0.5 + 2 * activity, 0.5)))
    issues_opened = int(stars / rng.uniform(40, 400))
    closed = int(issues_opened * min(1.3, rng.uniform(0.3, 1.2) + 0.4 * activity))
    prs_opened = int(issues_opened * rng.uniform(0.3, 1.5))
    prs_closed = int(prs_opened * rng.uniform(0.6, 1.0))
    releases_12m = 0 if archived else int(rng.triangular(0, 30, 6 + 10 * quality))
    top_share = rng.uniform(0.15, 0.95) if maint > 1 else 1.0
    return {
        "full_name": full_name, "name": full_name.split("/")[1], "owner": full_name.split("/")[0],
        "description": desc, "url": "https://github.com/" + full_name, "homepage": "",
        "language": lang, "topics": topics, "category": categorize(topics), "license": rng.choice(["MIT", "Apache-2.0", "BSD-3-Clause", "GPL-3.0", "AGPL-3.0"]),
        "created_at": (now - timedelta(days=age_months * 30.44)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_months": age_months, "releases_12m": releases_12m,
        "days_since_release": None if releases_12m == 0 and rng.random() < 0.5 else rng.uniform(1, 400) * (1.5 - quality),
        "has_readme": True, "has_install_docs": rng.random() < 0.5 + 0.5 * quality,
        "has_examples": rng.random() < 0.4 + 0.6 * quality, "has_api_docs": rng.random() < 0.4 + 0.6 * quality,
        "has_troubleshooting": rng.random() < 0.2 + 0.6 * quality,
        "has_license": True, "has_contributing": rng.random() < 0.3 + 0.7 * quality,
        "has_code_of_conduct": rng.random() < 0.3 + 0.6 * quality, "has_security_policy": rng.random() < 0.2 + 0.7 * quality,
        "has_issue_templates": rng.random() < 0.3 + 0.7 * quality,
        "has_ci": rng.random() < 0.5 + 0.5 * quality, "has_tests": rng.random() < 0.5 + 0.5 * quality,
        "ci_success_rate": None if rng.random() < 0.25 else rng.uniform(0.4, 1.0),
        "active_maintainers_180d": maint, "uses_semver": rng.random() < 0.3 + 0.7 * quality,
        "has_changelog": rng.random() < 0.3 + 0.6 * quality, "release_cadence_consistency": rng.uniform(0, 1) * quality,
        "breaking_changes_12m": int(rng.triangular(0, 12, 2)),
        "commits_90d": commits_90d, "days_since_commit": 400 if archived else rng.expovariate(1 / (3 + 40 * (1 - activity))),
        "median_issue_response_hours": None if issues_opened == 0 else rng.lognormvariate(3 + 2 * (1 - activity), 0.8),
        "median_pr_response_hours": None if prs_opened == 0 else rng.lognormvariate(2.5 + 2 * (1 - activity), 0.8),
        "issues_opened_90d": issues_opened, "issues_closed_90d": closed, "prs_opened_90d": prs_opened,
        "prs_merged_90d": int(prs_closed * rng.uniform(0.5, 0.95)), "prs_closed_90d": prs_closed,
        "open_issues": int(issues_opened * rng.uniform(0.5, 6)), "open_prs": int(prs_opened * rng.uniform(0.1, 1)),
        "active_contributors_90d": int(maint * rng.uniform(1, 6)),
        "stars": stars, "stars_90d": int(stars * rng.uniform(0.01, 0.2)), "stars_90d_estimated": rng.random() < 0.3,
        "forks": int(stars * rng.uniform(0.08, 0.3)), "forks_90d": int(stars * rng.uniform(0.002, 0.03)), "forks_90d_estimated": False,
        "watchers": int(stars * rng.uniform(0.005, 0.03)), "contributors_total": int(rng.lognormvariate(4.5, 1.0)),
        "external_engagement_90d": int((issues_opened + prs_opened) * rng.uniform(0.3, 0.9)),
        "bus_factor": 1 if top_share > 0.5 else int(rng.uniform(2, 8)), "top_contributor_share": top_share,
        "stale_open_issues": int(issues_opened * rng.uniform(0, 3)),
        "owner_is_org": org, "is_archived": archived, "has_sponsorship": rng.random() < 0.5,
        "contributor_retention": rng.uniform(0.1, 0.9), "commit_sample_truncated": commits_90d > 500,
        "commit_sample_size": min(500, commits_90d * 2),
    }


def main() -> None:
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    projects = [pipeline.build_project(synth_metrics(rng, *r, now)) for r in SAMPLE_REPOS]
    projects.sort(key=lambda p: -p["scores"]["overall"])

    # fabricate 60 days of history so sparklines and deltas have something to show
    history = {}
    for p in projects:
        series = []
        base = dict(p["scores"])
        for back in range(60, -1, -1):
            day = (now - timedelta(days=back)).strftime("%Y-%m-%d")
            jitter = lambda v: round(max(0, min(100, v + rng.gauss(0, 1.2) - back * rng.uniform(-0.08, 0.08))), 1)
            series.append({"d": day, "o": jitter(base["overall"]), "m": jitter(base["maturity"]), "h": jitter(base["health"]),
                           "p": jitter(base["popularity"]), "r": jitter(base["risk"]), "s": jitter(base["sustainability"]),
                           "stars": int(p["metrics"]["stars"] * (1 - back * 0.001))})
        series[-1].update({"o": base["overall"], "m": base["maturity"], "h": base["health"], "p": base["popularity"],
                           "r": base["risk"], "s": base["sustainability"], "stars": p["metrics"]["stars"]})
        history[p["full_name"]] = series
        prev = series[-8]
        p["delta_7d"] = {"overall": round(base["overall"] - prev["o"], 1), "stars": p["metrics"]["stars"] - prev["stars"]}
    for rank, p in enumerate(projects, 1):
        p["rank"] = rank

    board = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "version": __version__,
        "window_days": config.WINDOW_DAYS, "project_count": len(projects),
        "categories": sorted({p["category"] for p in projects}), "benchmarks": config.POPULARITY_BENCHMARKS,
        "weights": {"overall": config.OVERALL_WEIGHTS, "maturity": config.MATURITY_WEIGHTS, "health": config.HEALTH_WEIGHTS,
                    "popularity": config.POPULARITY_WEIGHTS, "risk": config.RISK_WEIGHTS, "sustainability": config.SUSTAINABILITY_WEIGHTS},
        "failures": [], "sample": True, "projects": projects,
    }
    pipeline.DATA_DIR.mkdir(parents=True, exist_ok=True)
    pipeline.LEADERBOARD_PATH.write_text(json.dumps(board, separators=(",", ":")))
    pipeline.HISTORY_PATH.write_text(json.dumps(history, separators=(",", ":")))
    print("wrote sample data for %d projects to %s" % (len(projects), pipeline.DATA_DIR))


if __name__ == "__main__":
    main()
