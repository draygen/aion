# memory_embeddings.py
# Pluggable embedding provider — local ONNX or remote API
# Ported from Sapphire core/embeddings.py (stripped multi-tenant router)

import logging
import numpy as np
from config import CONFIG

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = 'nomic-ai/nomic-embed-text-v1.5'
EMBEDDING_ONNX_FILE = 'onnx/model_quantized.onnx'


class LocalEmbedder:
    """Lazy-loaded nomic-embed-text-v1.5 via ONNX runtime."""

    def __init__(self):
        self.session = None
        self.tokenizer = None
        self.input_names = None

    def _load(self):
        if self.session is not None:
            return
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
            from huggingface_hub import hf_hub_download

            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    EMBEDDING_MODEL, trust_remote_code=True, local_files_only=True)
                model_path = hf_hub_download(
                    EMBEDDING_MODEL, EMBEDDING_ONNX_FILE, local_files_only=True)
            except Exception:
                logger.info(f"Downloading embedding model: {EMBEDDING_MODEL}")
                self.tokenizer = AutoTokenizer.from_pretrained(
                    EMBEDDING_MODEL, trust_remote_code=True)
                model_path = hf_hub_download(EMBEDDING_MODEL, EMBEDDING_ONNX_FILE)

            # Prefer CUDA, fall back to CPU automatically
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            self.session = ort.InferenceSession(model_path, providers=providers)
            active = self.session.get_providers()[0]
            self.input_names = [i.name for i in self.session.get_inputs()]
            logger.info(f"Embedding model loaded: {EMBEDDING_MODEL} (ONNX, provider={active})")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.session = None

    def embed(self, texts, prefix='search_document'):
        self._load()
        if self.session is None:
            return None
        try:
            prefixed = [f'{prefix}: {t}' for t in texts]
            encoded = self.tokenizer(prefixed, return_tensors='np', padding=True,
                                     truncation=True, max_length=512)
            inputs = {k: v for k, v in encoded.items() if k in self.input_names}
            if 'token_type_ids' not in inputs:
                inputs['token_type_ids'] = np.zeros_like(inputs['input_ids'])

            outputs = self.session.run(None, inputs)
            embeddings = outputs[0]
            mask = encoded['attention_mask']
            masked = embeddings * mask[:, :, np.newaxis]
            pooled = masked.sum(axis=1) / mask.sum(axis=1, keepdims=True)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return (pooled / norms).astype(np.float32)
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    @property
    def available(self):
        self._load()
        return self.session is not None


class RemoteEmbedder:
    """OpenAI-compatible embedding API client."""

    @staticmethod
    def _normalize_url(url):
        from urllib.parse import urlparse, urlunparse
        url = url.strip()
        if not url:
            return ''
        if not url.startswith(('http://', 'https://')):
            url = f'http://{url}'
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        if not path.endswith('/v1/embeddings'):
            if path.endswith('/v1'):
                path += '/embeddings'
            elif not path.endswith('/embeddings'):
                path += '/v1/embeddings'
        return urlunparse((parsed.scheme, parsed.netloc, path, '', '', ''))

    def embed(self, texts, prefix='search_document'):
        raw_url = CONFIG.get('EMBEDDING_API_URL', '')
        url = self._normalize_url(raw_url)
        if not url:
            return None
        try:
            import httpx
            key = CONFIG.get('EMBEDDING_API_KEY', '')
            headers = {}
            if key:
                headers['Authorization'] = f'Bearer {key}'

            prefixed = [f'{prefix}: {t}' for t in texts]
            resp = httpx.post(url, json={'input': prefixed, 'model': EMBEDDING_MODEL},
                              headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json().get('data', [])
            if not data:
                logger.warning("Remote embedding returned empty data")
                return None
            vecs = np.array([d['embedding'] for d in data], dtype=np.float32)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return (vecs / norms).astype(np.float32)
        except Exception as e:
            logger.error(f"Remote embedding failed: {e}")
            return None

    @property
    def available(self):
        return bool(self._normalize_url(CONFIG.get('EMBEDDING_API_URL', '')))


class OllamaEmbedder:
    """Ollama embedding API — runs on GPU via the same path as LLM inference.

    Uses nomic-embed-text (768-dim) via http://localhost:11434/api/embed.
    Falls back to NullEmbedder if Ollama isn't reachable.
    """

    def embed(self, texts, prefix='search_document'):
        base_url = CONFIG.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        model = CONFIG.get('OLLAMA_EMBED_MODEL', 'nomic-embed-text')
        try:
            import httpx
            prefixed = [f'{prefix}: {t}' for t in texts]
            resp = httpx.post(
                f'{base_url}/api/embed',
                json={'model': model, 'input': prefixed},
                timeout=30.0,
            )
            resp.raise_for_status()
            embeddings = resp.json().get('embeddings', [])
            if not embeddings:
                logger.warning("Ollama embed returned empty embeddings")
                return None
            vecs = np.array(embeddings, dtype=np.float32)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1
            return (vecs / norms).astype(np.float32)
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return None

    @property
    def available(self):
        base_url = CONFIG.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        try:
            import httpx
            r = httpx.get(f'{base_url}/', timeout=1.0)
            return r.status_code == 200
        except Exception:
            return False


class NullEmbedder:
    """Disabled — consumers fall back to FTS5/LIKE search."""

    def embed(self, texts, prefix='search_document'):
        return None

    @property
    def available(self):
        return False


# ─── Singleton + hot-swap ─────────────────────────────────────────────────────

_embedder = None


def _create_embedder(provider_name=None):
    name = provider_name or CONFIG.get('EMBEDDING_PROVIDER', 'null')
    if name == 'ollama':
        return OllamaEmbedder()
    if name == 'api':
        return RemoteEmbedder()
    if name == 'local':
        return LocalEmbedder()
    return NullEmbedder()


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = _create_embedder()
    return _embedder


def switch_embedding_provider(provider_name):
    global _embedder
    logger.info(f"Switching embedding provider to: {provider_name}")
    _embedder = _create_embedder(provider_name)
    # Reset backfill so new provider can embed any missing memories
    try:
        import memory_store as mem
        mem._backfill_done = False
    except Exception:
        pass
