"""Find candidate open source AI repositories via GitHub topic search."""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, List

from . import config
from .github import GitHubClient
from .queries import DISCOVER

log = logging.getLogger("whitescore.discover")


def _search_query(topic: str) -> str:
    return "topic:%s stars:>=%d archived:false fork:false sort:stars-desc" % (topic, config.MIN_STARS)


def discover(client: GitHubClient, topics: List[str] = None, pages_per_topic: int = None,
             min_stars: int = None) -> Dict[str, dict]:
    """Return {nameWithOwner: {stars, topics}} for every candidate found."""
    topics = topics or config.AI_TOPICS
    pages_per_topic = pages_per_topic or config.PAGES_PER_TOPIC
    min_stars = config.MIN_STARS if min_stars is None else min_stars
    found: Dict[str, dict] = {}

    for topic in topics:
        after = None
        for page in range(pages_per_topic):
            data = client.graphql(DISCOVER, {"q": _search_query(topic), "after": after})
            search = data.get("search") or {}
            for node in search.get("nodes") or []:
                if not node or node.get("isArchived") or node.get("isFork"):
                    continue
                license_info = node.get("licenseInfo") or {}
                spdx = license_info.get("spdxId")
                if config.REQUIRE_RECOGNIZED_LICENSE and (not spdx or spdx == "NOASSERTION"):
                    continue
                if node.get("stargazerCount", 0) < min_stars:
                    continue
                name = node["nameWithOwner"]
                entry = found.setdefault(name, {"stars": node["stargazerCount"], "topics": set(), "hits": 0})
                entry["topics"].update(t["topic"]["name"] for t in node["repositoryTopics"]["nodes"])
                entry["hits"] += 1
            info = search.get("pageInfo") or {}
            log.info("topic=%s page=%d total=%s found=%d", topic, page + 1,
                     search.get("repositoryCount"), len(found))
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
            time.sleep(0.5)
    for entry in found.values():
        entry["topics"] = sorted(entry["topics"])
    return found


def select_repos(found: Dict[str, dict], seeds: List[str] = None, max_repos: int = None) -> List[str]:
    """Rank candidates by stars, always keeping seed repos, capped at max_repos."""
    seeds = config.SEED_REPOS if seeds is None else seeds
    max_repos = max_repos or config.MAX_REPOS
    ranked = sorted(found.items(), key=lambda kv: (-kv[1]["stars"], kv[0]))
    chosen: List[str] = []
    seen = set()
    for seed in seeds:
        key = seed.strip()
        if key and key.lower() not in seen:
            chosen.append(key)
            seen.add(key.lower())
    for name, _ in ranked:
        if len(chosen) >= max_repos:
            break
        if name.lower() not in seen:
            chosen.append(name)
            seen.add(name.lower())
    return chosen


LIST_NAME_RE = re.compile(r"(^|[-_/])(awesome|curated|roadmap|cheatsheet|cheat-sheet|interview|papers?|reading-list|tutorials?|course|courses|handbook|guide|book|books|lectures?|notes|examples?|cookbook|collection|resources|syllabus|learn|learning-path|100-days|30-days|for-beginners|beginners|lessons|bootcamp|zero-to|101|curriculum|study|survey|progress|list)([-_/]|$)", re.I)
LIST_TOPICS = {"awesome", "awesome-list", "awesome-lists", "list", "lists", "curated-list", "papers", "paper-list",
               "survey", "roadmap", "tutorial", "tutorials", "course", "courses", "cheatsheet", "interview",
               "interview-questions", "books", "book", "resources", "learning-resources", "study-notes", "lecture-notes"}


def is_curated_list(full_name: str, description: str, topics: List[str]) -> bool:
    """True for awesome-lists, paper collections, courses and similar non-software repos."""
    name = full_name.split("/")[-1]
    topic_set = {t.lower() for t in topics}
    if topic_set & LIST_TOPICS:
        return True
    if LIST_NAME_RE.search(name):
        return True
    low = name.lower()
    if any(w in low for w in ("handbook", "cookbook", "tutorial", "awesome", "cheatsheet", "roadmap", "lessons",
                              "for-beginners", "from-scratch", "fromscratch", "course", "interview", "bootcamp")):
        return True
    desc = (description or "").lower()
    markers = ("curated list", "a list of", "list of ", "collection of", "awesome ", "roadmap", "cheat sheet",
               "cheatsheet", "interview", "reading list", "paper list", "papers on", "tutorials", "course ",
               "lecture", "learning resources", "study guide", "syllabus", "must-read", "must read", "lessons",
               "quizzes", "curriculum", "for beginners", "learning path", "track the progress", "survey of",
               "a survey", "reading group", "book ", "textbook", "notes on", "collection ")
    return any(m in desc for m in markers)


def categorize(topics: List[str], description: str = "", full_name: str = "") -> str:
    if full_name and is_curated_list(full_name, description, topics):
        return config.CURATED_LIST_CATEGORY
    topic_set = {t.lower() for t in topics}
    desc = (description or "").lower()
    lead = desc[:60]                       # descriptions lead with what the project is
    best, best_score = config.DEFAULT_CATEGORY, 0.0
    for category, rule in config.CATEGORY_RULES:
        matched = topic_set & rule["topics"]
        score = sum(0.25 if t in config.GENERIC_TOPICS else 2.0 for t in matched)
        score += sum(2.0 if k in lead else 1.0 for k in rule["keywords"] if k in desc)
        if score > best_score:
            best, best_score = category, score
    if best == config.DEFAULT_CATEGORY and full_name:
        best = _category_from_name(full_name.lower())
    return best


NAME_HINTS = [
    ("AI Coding Assistants", ("code", "coder", "copilot", "codex", "cursor", "devin", "swe-")),
    ("Agents & Orchestration", ("agent", "mcp", "modelcontextprotocol", "crew", "swarm", "workflow", "autogpt", "langchain", "langgraph")),
    ("RAG & Vector Search", ("rag", "vector", "embed", "retriev", "search", "index")),
    ("Chat UIs & Assistants", ("chat", "webui", "assistant", "bot")),
    ("Speech & Audio", ("tts", "speech", "voice", "audio", "whisper", "asr", "sovits", "music")),
    ("Generative Media", ("diffusion", "sdxl", "flux", "img", "image", "video", "gen", "dall", "controlnet", "comfy")),
    ("Computer Vision", ("yolo", "vision", "ocr", "detect", "segment", "face", "cv", "vlm", "clip")),
    ("NLP", ("nlp", "bert", "text", "token", "translat", "ner")),
    ("Reinforcement Learning & Robotics", ("rl", "robot", "gym", "drone", "sim")),
    ("Fine-tuning & Alignment", ("finetun", "fine-tun", "lora", "peft", "rlhf", "train", "tuning")),
    ("Data, MLOps & Evaluation", ("mlops", "eval", "bench", "label", "dataset", "pipeline")),
    ("LLMs & Inference", ("llm", "llama", "gpt", "deepseek", "qwen", "mistral", "gemma", "mixtral", "phi-", "glm", "baichuan",
                          "yi-", "infer", "model", "moe", "transformer", "lm", "openai", "claude", "gemini")),
    ("ML Frameworks & Training", ("torch", "tensor", "jax", "keras", "ml", "learn", "neural", "net", "deep", "nn")),
]


def _category_from_name(name: str) -> str:
    for category, needles in NAME_HINTS:
        if any(n in name for n in needles):
            return category
    return config.DEFAULT_CATEGORY


AI_WORDS = (" ai ", " ai-", "ai-powered", " ai.", "(ai)", "llm", "language model", "machine learning", "deep learning",
            "neural", "gpt", "chatgpt", "openai", "claude", "gemini", "llama", "ai agent", "agents", "agentic",
            "transformer", "diffusion", "embedding", "rag ", "retrieval-augmented", "inference", "fine-tun", "finetun",
            "computer vision", "speech", "whisper", "generative", "copilot", "chatbot", "prompt", " ml ", "nlp",
            "ocr", "object detection", "segmentation", "reinforcement learning", "text-to-", "mcp ", "mcp server",
            "stable diffusion", "image generation", "voice clon", "artificial intelligence")


def ai_signal(topics: List[str], hits: List[str], description: str) -> int:
    """How clearly AI-related a repository is: strong topic hits count double,
    generic ones single, and AI words in the description add up to two."""
    strong = sum(1 for h in hits if h not in config.GENERIC_TOPICS and not h.startswith("kw:") and h != "seed")
    strong += sum(1 for h in hits if h.startswith("kw:"))          # matched an AI keyword in name/description
    generic = min(1, sum(1 for h in hits if h in config.GENERIC_TOPICS))
    topic_bonus = sum(1 for t in topics if t.lower() in config.AI_TOPICS and t.lower() not in config.GENERIC_TOPICS and t not in hits)
    desc = " " + (description or "").lower() + " "
    words = min(2, sum(1 for w in AI_WORDS if w in desc))
    return 2 * strong + generic + min(2, topic_bonus) + words
