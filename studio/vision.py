"""Local CLIP vision (fastembed, ONNX, CPU): food/head/consensus/text-image signals.

CLIP ViT-B/32 is weak at fine-grained dish names but useful for coarse groups and
image-image agreement, so vision only vetoes clear mismatches and breaks ties.
"""
from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from studio.lexicon import HEAD_GROUP, HEAD_PROMPT

log = logging.getLogger("studio.vision")

MODEL_IMAGE = "Qdrant/clip-ViT-B-32-vision"
MODEL_TEXT = "Qdrant/clip-ViT-B-32-text"

FOOD_PROMPTS: list[str] = [
    "a photo of food on a plate",
    "a photo of a dish of Indian food",
    "a photo of a drink in a glass",
    "a photo of a dessert",
    "a close-up photo of a meal",
]
NONFOOD_PROMPTS: list[str] = [
    "a logo",
    "a poster with text",
    "a menu card with prices",
    "a photo of a person",
    "a restaurant interior",
    "an empty table",
    "a cardboard delivery box with a brand logo",
    "a collage of many different dishes",
]

_HEAD_VETO_MARGIN = 0.02


class Vision(Protocol):
    available: bool
    reason: str

    def embed_images(self, images: list[bytes]) -> np.ndarray: ...

    def embed_texts(self, texts: list[str]) -> np.ndarray: ...


def _normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vecs / norms).astype(np.float32)


class ClipVision:
    def __init__(self, cache_dir: Path, allow_download: bool = True):
        self.cache_dir = cache_dir
        self.allow_download = allow_download
        self.available = False
        self.reason = ""
        self._image_model = None
        self._text_model = None
        self._text_cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._image_model is not None and self._text_model is not None:
            return
        from fastembed import ImageEmbedding, TextEmbedding

        with self._lock:
            if self._image_model is None or self._text_model is None:
                kwargs = {} if self.allow_download else {"local_files_only": True}
                self._image_model = ImageEmbedding(
                    MODEL_IMAGE, cache_dir=str(self.cache_dir), **kwargs
                )
                self._text_model = TextEmbedding(
                    MODEL_TEXT, cache_dir=str(self.cache_dir), **kwargs
                )
                self.available = True

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        self._ensure_loaded()
        pil_images = []
        for data in images:
            img = Image.open(io.BytesIO(data))
            img.load()
            pil_images.append(img.convert("RGB"))
        vecs = np.array(list(self._image_model.embed(pil_images, batch_size=32)))
        return _normalize(vecs)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        self._ensure_loaded()
        missing = [t for t in texts if t not in self._text_cache]
        if missing:
            vecs = _normalize(np.array(list(self._text_model.embed(missing))))
            for t, v in zip(missing, vecs):
                self._text_cache[t] = v
        return np.stack([self._text_cache[t] for t in texts])


class NullVision:
    def __init__(self, reason: str):
        self.available = False
        self.reason = reason

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        raise RuntimeError("vision unavailable")

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("vision unavailable")


def _smoke_image_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def load_vision(cache_dir: Path, allow_download: bool = True) -> Vision:
    try:
        vision = ClipVision(cache_dir, allow_download=allow_download)
        vision.embed_images([_smoke_image_bytes()])
        vision.embed_texts(["a photo of food"])
        return vision
    except Exception as exc:
        log.warning("vision unavailable: %s", exc)
        return NullVision(reason=str(exc)[:200])


def food_ok(vision: Vision, img_vecs: np.ndarray) -> np.ndarray:
    prompts = FOOD_PROMPTS + NONFOOD_PROMPTS
    text_vecs = vision.embed_texts(prompts)
    logits = 100.0 * (img_vecs @ text_vecs.T)
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = exp / exp.sum(axis=1, keepdims=True)
    food_prob = probs[:, : len(FOOD_PROMPTS)].sum(axis=1)
    return food_prob >= 0.5


def head_ok(vision: Vision, img_vecs: np.ndarray, head: str | None) -> np.ndarray:
    n = len(img_vecs)
    if head is None or head not in HEAD_PROMPT:
        return np.ones(n, dtype=bool)

    groups_order: list[str] = []
    representative: dict[str, str] = {}
    for h, g in HEAD_GROUP.items():
        if g not in representative:
            representative[g] = h
            groups_order.append(g)

    own_group = HEAD_GROUP[head]
    own_prompt = HEAD_PROMPT[head]
    group_prompt = {g: HEAD_PROMPT[representative[g]] for g in groups_order}

    other_groups = [g for g in groups_order if g != own_group]
    if not other_groups:
        return np.ones(n, dtype=bool)

    texts = list(dict.fromkeys([own_prompt] + [group_prompt[g] for g in other_groups]))
    text_vecs = vision.embed_texts(texts)
    text_idx = {t: i for i, t in enumerate(texts)}

    sims = img_vecs @ text_vecs.T
    own = sims[:, text_idx[own_prompt]]
    best_other = sims[:, [text_idx[group_prompt[g]] for g in other_groups]].max(axis=1)
    return own >= best_other - _HEAD_VETO_MARGIN


def consensus(img_vecs: np.ndarray, weights: np.ndarray) -> np.ndarray:
    n = len(img_vecs)
    if n <= 1:
        return np.ones(n, dtype=np.float64)

    weights = np.asarray(weights, dtype=np.float64)
    cos = img_vecs @ img_vecs.T
    raw = np.zeros(n, dtype=np.float64)
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        w = weights[mask]
        total = w.sum()
        raw[i] = float((w * cos[i][mask]).sum() / total) if total > 0 else 0.0

    lo, hi = raw.min(), raw.max()
    if hi - lo < 1e-12:
        return np.full(n, 0.5, dtype=np.float64)
    return (raw - lo) / (hi - lo)


def text_sim(vision: Vision, img_vecs: np.ndarray, text: str) -> np.ndarray:
    vec = vision.embed_texts([f"a photo of {text}"])[0]
    cos = img_vecs @ vec
    return np.clip((cos - 0.15) / 0.2, 0.0, 1.0)
