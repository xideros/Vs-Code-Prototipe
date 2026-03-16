# core/rnn_text_filter.py
# RNN-фильтр OCR текста: отсекает шумные строки перед дальнейшей обработкой.

from __future__ import annotations

import numpy as np


class SimpleRNNBinaryClassifier:
    """Минимальная many-to-one RNN для бинарной классификации последовательностей."""

    def __init__(self, input_size: int = 1, hidden_size: int = 16, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.input_size = input_size
        self.hidden_size = hidden_size

        self.Wxh = rng.normal(0, np.sqrt(1 / input_size), size=(hidden_size, input_size))
        self.Whh = rng.normal(0, np.sqrt(1 / hidden_size), size=(hidden_size, hidden_size))
        self.bh = np.zeros((hidden_size, 1))

        self.Why = rng.normal(0, np.sqrt(1 / hidden_size), size=(1, hidden_size))
        self.by = np.zeros((1, 1))

    @staticmethod
    def sigmoid(x):
        return 1.0 / (1.0 + np.exp(-x))

    def forward(self, x_seq):
        h_prev = np.zeros((self.hidden_size, 1))
        h_states = [h_prev]
        x_cache = []

        for x_t in x_seq:
            x_t = x_t.reshape(self.input_size, 1)
            h_t = np.tanh(self.Wxh @ x_t + self.Whh @ h_prev + self.bh)
            x_cache.append(x_t)
            h_states.append(h_t)
            h_prev = h_t

        y_logit = self.Why @ h_states[-1] + self.by
        y_prob = self.sigmoid(y_logit)
        return y_prob, {"x": x_cache, "h": h_states, "y_prob": y_prob}

    def backward(self, cache, y_true):
        x_cache = cache["x"]
        h_states = cache["h"]
        y_prob = cache["y_prob"]

        dy = y_prob - y_true

        dWhy = dy @ h_states[-1].T
        dby = dy

        dWxh = np.zeros_like(self.Wxh)
        dWhh = np.zeros_like(self.Whh)
        dbh = np.zeros_like(self.bh)

        dh_next = self.Why.T @ dy

        for t in reversed(range(len(x_cache))):
            h_t = h_states[t + 1]
            h_prev = h_states[t]
            x_t = x_cache[t]

            dtanh = (1 - h_t ** 2) * dh_next
            dWxh += dtanh @ x_t.T
            dWhh += dtanh @ h_prev.T
            dbh += dtanh
            dh_next = self.Whh.T @ dtanh

        return {"Wxh": dWxh, "Whh": dWhh, "bh": dbh, "Why": dWhy, "by": dby}

    def step(self, grads, lr: float = 0.01, clip: float = 5.0):
        for g in grads.values():
            np.clip(g, -clip, clip, out=g)

        self.Wxh -= lr * grads["Wxh"]
        self.Whh -= lr * grads["Whh"]
        self.bh -= lr * grads["bh"]
        self.Why -= lr * grads["Why"]
        self.by -= lr * grads["by"]

    def predict_proba(self, x_seq) -> float:
        y_prob, _ = self.forward(x_seq)
        return float(y_prob[0, 0])


class RNNTextNoiseFilter:
    """
    Легковесный RNN-классификатор: оценивает, похожа ли строка на осмысленный текст.

    Идея признаков: символ -> 1, если это буква, иначе 0.
    """

    def __init__(
        self,
        seq_len: int = 48,
        hidden_size: int = 20,
        threshold: float = 0.55,
        train_samples: int = 1200,
        epochs: int = 12,
        seed: int = 123,
    ):
        self.seq_len = seq_len
        self.threshold = threshold
        self.rng = np.random.default_rng(seed)
        self.model = SimpleRNNBinaryClassifier(input_size=1, hidden_size=hidden_size, seed=seed)
        self._train_synthetic(train_samples=train_samples, epochs=epochs)

    def _make_synthetic_dataset(self, num_samples: int):
        # Синтетика под задачу фильтрации шума:
        # 1 = буквенные символы доминируют в последовательности
        X = self.rng.integers(0, 2, size=(num_samples, self.seq_len, 1)).astype(np.float64)
        y = (X.sum(axis=1) > (self.seq_len // 2)).astype(np.float64).reshape(-1, 1)
        return X, y

    @staticmethod
    def _bce_loss(y_prob, y_true, eps: float = 1e-9):
        y_prob = np.clip(y_prob, eps, 1 - eps)
        return -(y_true * np.log(y_prob) + (1 - y_true) * np.log(1 - y_prob))

    def _train_synthetic(self, train_samples: int, epochs: int):
        X, y = self._make_synthetic_dataset(train_samples)
        lr = 0.015

        for _ in range(max(1, epochs)):
            idx = self.rng.permutation(len(X))
            X = X[idx]
            y = y[idx]

            for i in range(len(X)):
                x_seq = X[i]
                y_true = y[i, 0]
                y_prob, cache = self.model.forward(x_seq)
                _ = self._bce_loss(y_prob, y_true)
                grads = self.model.backward(cache, y_true)
                self.model.step(grads, lr=lr)

    def _encode_text(self, text: str):
        if not text:
            seq = np.zeros((self.seq_len, 1), dtype=np.float64)
            return seq

        values = []
        for ch in text[: self.seq_len]:
            values.append([1.0 if ch.isalpha() else 0.0])

        if len(values) < self.seq_len:
            values.extend([[0.0]] * (self.seq_len - len(values)))

        return np.array(values, dtype=np.float64)

    def score(self, text: str) -> float:
        seq = self._encode_text(text)
        return self.model.predict_proba(seq)

    def is_meaningful(self, text: str) -> bool:
        return self.score(text) >= self.threshold
