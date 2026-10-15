"""Local cross-encoder relevance scores (Qwen3-Reranker) for retrieved units.

Scores order candidates only; they never prove that a passage supports a claim.
Opt-in via RERANKER_MODEL; any failure leaves the incoming order unchanged.
"""
import threading
from . import config

_lock = threading.Lock()
_loaded = {}

INSTRUCTION = ('Given a question about Jewish law or Torah, judge whether the passage directly answers it '
               '(not merely the same topic)')
PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the '
          'Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


def _model(name):
    with _lock:
        if name not in _loaded:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            tok = AutoTokenizer.from_pretrained(name, padding_side='left')
            device = 'mps' if torch.backends.mps.is_available() else 'cpu'
            model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.float32, attn_implementation='eager').to(device).eval()
            _loaded[name] = (tok, model, device, tok.convert_tokens_to_ids('yes'), tok.convert_tokens_to_ids('no'))
        return _loaded[name]


def scores(question, texts, name=None, batch=4, max_chars=800):
    """Probability that each text directly answers the question (0..1)."""
    import torch
    name = name or config.get('RERANKER_MODEL', '')
    if not name or not texts:
        return None
    tok, model, device, yes, no = _model(name)
    out = []
    for i in range(0, len(texts), batch):
        pairs = [PREFIX + f'<Instruct>: {INSTRUCTION}\n<Query>: {question}\n<Document>: {t[:max_chars]}' + SUFFIX
                 for t in texts[i:i + batch]]
        enc = tok(pairs, padding=True, truncation=True, max_length=512, return_tensors='pt').to(device)
        with torch.no_grad():
            logits = model(**enc).logits[:, -1, :]
        pair = torch.stack([logits[:, no], logits[:, yes]], dim=1).float()
        out += torch.softmax(pair, dim=1)[:, 1].tolist()
    return out
