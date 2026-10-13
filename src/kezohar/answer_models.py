"""Provider adapters. Default transport is the existing local-compatible client."""
from . import config, llm


class OpenAICompatibleAnswerModel:
    def __init__(self, settings):
        self.settings = settings

    @property
    def identity(self):
        return self.settings

    def generate(self, question, sources, timeout=4.5,cancel_event=None):
        return llm.ask(question, sources, self.settings.base_url,
                       self.settings.model, timeout=timeout,cancel_event=cancel_event)

    def health(self, timeout=8):
        return llm.check_health(self.settings.base_url, timeout=timeout)
    def generate_knowledge(self,question,sources,timeout=4.5,cancel_event=None):
        return llm.ask(question,sources,self.settings.base_url,self.settings.model,
            timeout=timeout,cancel_event=cancel_event,task='knowledge')


_PROVIDERS = {'openai-compatible': OpenAICompatibleAnswerModel}


def register_answer_provider(name, factory):
    """Explicit plugin registration; settings never import arbitrary Python code."""
    if name in _PROVIDERS:
        raise ValueError('answer provider already registered')
    _PROVIDERS[name] = factory


def create_answer_model(settings):
    try:
        factory = _PROVIDERS[settings.provider]
    except KeyError:
        raise ValueError('unknown answer provider') from None
    return factory(settings)


class ConfiguredAnswerModel:
    """Reconfigure lazily without touching knowledge or retrieval indexes.

    Explicit legacy constructor overrides remain supported. Environment settings
    are read per request; changing the identity invalidates the answer cache.
    """
    def __init__(self, base_url=None, model=None):
        self.base_url = base_url
        self.model = model
        self._settings = None
        self._adapter = None

    @property
    def identity(self):
        return config.answer_settings(self.base_url, self.model)

    def _current(self):
        settings = self.identity
        if settings != self._settings:
            adapter = create_answer_model(settings)
            self._adapter, self._settings = adapter, settings
        return self._adapter

    def generate(self, question, sources, timeout=4.5,cancel_event=None):
        adapter=self._current()
        import inspect
        opts={'timeout':timeout}
        if cancel_event is not None and 'cancel_event' in inspect.signature(adapter.generate).parameters:opts['cancel_event']=cancel_event
        return adapter.generate(question, sources, **opts)

    def health(self, timeout=8):
        return self._current().health(timeout=timeout)
    def generate_knowledge(self,question,sources,timeout=4.5,cancel_event=None):
        adapter=self._current()
        method=getattr(adapter,'generate_knowledge',adapter.generate)
        import inspect
        opts={'timeout':timeout}
        if cancel_event is not None and 'cancel_event' in inspect.signature(method).parameters:opts['cancel_event']=cancel_event
        return method(question,sources,**opts)
