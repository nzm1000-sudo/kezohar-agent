"""Independent embedding configuration and versioned vector-index identity.

The default remains the free heuristic mock. A strictly local real-compatible
provider is opt-in; answer settings and vector index identity remain separate.
"""
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from . import config, hebrew


class VectorIndexMismatch(ValueError):
    pass


@dataclass(frozen=True)
class VectorIndexSpec:
    provider: str
    model: str
    dimensions: int
    revision: str
    normalization: str = 'hebrew-normalize-v1'

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.provider, settings.model, settings.dimensions, settings.revision,settings.normalization)

    @property
    def namespace(self):
        raw = json.dumps(asdict(self), sort_keys=True).encode('utf-8')
        return 'vectors-' + hashlib.sha256(raw).hexdigest()[:24]

    def manifest(self):
        return {'schema_version': 1, 'embedding': asdict(self), 'namespace': self.namespace}

    def check_manifest(self, manifest):
        if manifest != self.manifest():
            raise VectorIndexMismatch('embedding identity changed; build a separate vector index')


def _embed_heuristic(text, dim=128):
    """The preexisting deterministic mock; not semantic embeddings."""
    vec = [0.0] * dim
    for token in hebrew.tokens(text):
        for i in range(len(token)):
            tri = token[max(0, i-1):i+2]
            index = int(hashlib.md5(tri.encode('utf-8')).hexdigest(), 16) % dim
            vec[index] += 1.0
    norm = math.sqrt(sum(value*value for value in vec)) or 1.0
    return [value/norm for value in vec]


class MockEmbeddingModel:
    def __init__(self, settings):
        if settings.model != 'hash-trigram-v1':
            raise ValueError('unknown mock embedding model')
        self.spec = VectorIndexSpec.from_settings(settings)

    def embed(self, text):
        return _embed_heuristic(text, self.spec.dimensions)


def _local_factory(settings):
    from .local_embeddings import LocalEmbeddingModel
    return LocalEmbeddingModel(settings)

_PROVIDERS = {'mock': MockEmbeddingModel,'openai-compatible-local':_local_factory}


def register_embedding_provider(name, factory):
    if name in _PROVIDERS:
        raise ValueError('embedding provider already registered')
    _PROVIDERS[name] = factory


def create_embedding_model(settings=None):
    settings = settings or config.embedding_settings()
    try:
        factory = _PROVIDERS[settings.provider]
    except KeyError:
        raise ValueError('unknown embedding provider') from None
    return factory(settings)
