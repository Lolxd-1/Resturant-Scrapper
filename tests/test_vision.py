"""Tests for studio.vision (offline; FakeVision stands in for the real CLIP model)."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from studio import config, vision
from studio.lexicon import HEAD_PROMPT


class FakeVision:
    """Deterministic stand-in for ClipVision: each distinct string gets its own
    orthogonal one-hot direction, so cosine similarity is 1.0 for a match and 0.0
    otherwise. `image_bytes_for(text)` builds fake image bytes (first byte = index)
    that embed to the same vector as that text.
    """

    available = True
    reason = ""
    _DIM = 64

    def __init__(self):
        self._text_index: dict[str, int] = {}

    def _index_for(self, text: str) -> int:
        if text not in self._text_index:
            self._text_index[text] = len(self._text_index)
        return self._text_index[text]

    def _one_hot(self, idx: int) -> np.ndarray:
        vec = np.zeros(self._DIM, dtype=np.float32)
        vec[idx % self._DIM] = 1.0
        return vec

    def image_bytes_for(self, text: str) -> bytes:
        return bytes([self._index_for(text)])

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        return np.stack([self._one_hot(data[0]) for data in images])

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._one_hot(self._index_for(t)) for t in texts])


@pytest.fixture
def fake_vision():
    return FakeVision()


# ---- TC3: NullVision + load_vision fallback ----

def test_tc3_null_vision_unavailable_and_raises():
    nv = vision.NullVision(reason="no onnxruntime")
    assert nv.available is False
    assert nv.reason == "no onnxruntime"
    with pytest.raises(RuntimeError):
        nv.embed_images([b"x"])
    with pytest.raises(RuntimeError):
        nv.embed_texts(["x"])


def test_tc3_load_vision_falls_back_to_null_on_construction_error(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model files missing")

    monkeypatch.setattr(vision, "ClipVision", boom)

    result = vision.load_vision(tmp_path)

    assert isinstance(result, vision.NullVision)
    assert result.available is False


# ---- TC4: food_ok ----

def test_tc4_food_ok_logo_false_food_true(fake_vision):
    logo_bytes = fake_vision.image_bytes_for("a logo")
    food_bytes = fake_vision.image_bytes_for("a photo of food on a plate")
    img_vecs = fake_vision.embed_images([logo_bytes, food_bytes])

    result = vision.food_ok(fake_vision, img_vecs)

    assert list(result) == [False, True]


# ---- TUNE1: FOOD_MIN_PROB threshold (0.30, not the old 0.5) ----

def test_tune1_food_ok_uses_lowered_threshold(fake_vision):
    food_bytes = fake_vision.image_bytes_for("a photo of food on a plate")
    img_vecs = fake_vision.embed_images([food_bytes])
    probs = vision.food_prob(fake_vision, img_vecs)

    assert bool(vision.food_ok(fake_vision, img_vecs)[0]) is True
    assert probs[0] > vision.FOOD_MIN_PROB


# ---- TC5: head_ok ----

def test_tc5_head_ok_pizza_vs_other_group(fake_vision):
    pizza_bytes = fake_vision.image_bytes_for(HEAD_PROMPT["PIZZA"])
    img_vecs = fake_vision.embed_images([pizza_bytes])

    assert vision.head_ok(fake_vision, img_vecs, "DAL")[0] == np.bool_(False)
    assert vision.head_ok(fake_vision, img_vecs, "PIZZA")[0] == np.bool_(True)
    assert vision.head_ok(fake_vision, img_vecs, None)[0] == np.bool_(True)


# ---- TUNE1: head_margin raw signal ----

def test_tune1_head_margin_inf_when_head_unknown(fake_vision):
    bytes_ = fake_vision.image_bytes_for(HEAD_PROMPT["PIZZA"])
    img_vecs = fake_vision.embed_images([bytes_])

    assert vision.head_margin(fake_vision, img_vecs, None)[0] == np.inf
    assert vision.head_margin(fake_vision, img_vecs, "not-a-head")[0] == np.inf


def test_tune1_head_margin_matches_head_ok_threshold(fake_vision):
    pizza_bytes = fake_vision.image_bytes_for(HEAD_PROMPT["PIZZA"])
    img_vecs = fake_vision.embed_images([pizza_bytes])

    margin = vision.head_margin(fake_vision, img_vecs, "PIZZA")[0]
    assert margin == pytest.approx(1.0)
    assert bool(vision.head_ok(fake_vision, img_vecs, "PIZZA")[0]) is bool(margin >= vision.HEAD_SOFT_VETO)


# ---- TC6: consensus ----

def test_tc6_consensus_orthogonal_outlier_scores_lowest():
    vecs = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    weights = np.ones(4)

    result = vision.consensus(vecs, weights)

    assert result[3] == pytest.approx(0.0, abs=1e-9)
    assert result[0] >= 0.9
    assert result[1] >= 0.9
    assert result[2] >= 0.9


def test_consensus_single_item_returns_ones():
    result = vision.consensus(np.array([[1.0, 0.0]]), np.array([1.0]))
    assert list(result) == [1.0]


# ---- text_sim (part of the vision contract, exercised with FakeVision) ----

def test_text_sim_maps_matching_and_orthogonal(fake_vision):
    aligned_bytes = fake_vision.image_bytes_for("a photo of pizza")
    fake_vision.image_bytes_for("misc")  # reserve a distinct, non-matching direction
    img_vecs = fake_vision.embed_images([aligned_bytes, fake_vision.image_bytes_for("misc")])

    result = vision.text_sim(fake_vision, img_vecs, "pizza")

    assert result[0] == pytest.approx(1.0, abs=1e-6)  # (1.0 - 0.15) / 0.2 clipped to 1.0
    assert result[1] == pytest.approx(0.0, abs=1e-6)


# ---- TC8: real CLIP smoke test (skipped unless the model is locally available) ----

def _real_vision_ready() -> bool:
    if os.environ.get("MENUSTUDIO_TEST_REAL_VISION") == "1":
        return True
    models_dir = config.models_dir()
    return any(models_dir.iterdir())


@pytest.mark.skipif(not _real_vision_ready(), reason="real CLIP model not available locally")
def test_tc8_real_clip_smoke():
    img_path = Path(__file__).resolve().parent.parent / "smartbiz_out_hfood" / "zimages" / "HFC-004.jpg"
    cv = vision.ClipVision(config.models_dir())
    img_vecs = cv.embed_images([img_path.read_bytes()])

    assert bool(vision.head_ok(cv, img_vecs, "PIZZA")[0]) is True
    assert bool(vision.head_ok(cv, img_vecs, "SHAKE")[0]) is False
