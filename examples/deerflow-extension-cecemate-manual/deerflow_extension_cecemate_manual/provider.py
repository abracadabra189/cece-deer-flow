"""Search-only adapter to the host's attributable knowledge contract."""

from deerflow.knowledge import KnowledgeCapabilities, KnowledgeSource, RetrievalHit, RetrievalResult

from .config import Settings
from .corpus import Corpus
from .retrieval import Retriever


class CecemateManualProvider:
    capabilities = KnowledgeCapabilities(operations={"search", "sources"})

    def __init__(self, corpus: Corpus, settings: Settings | None = None):
        self.corpus = corpus
        self.retriever = Retriever(corpus, settings or Settings())

    async def search(self, query: str) -> RetrievalResult:
        hits = []
        meta = self.corpus.manifest
        for match in self.retriever.search(query):
            entry = match.entry
            label = f"{entry.chapter} | {meta.version} ({meta.date})"
            if entry.status == "retired":
                label += " | 已下线 / retired"
            if match.partial:
                label += " | 节选（受预算限制；含限制说明） / partial excerpt"
            # Real source chapter/version, no invented URL or page locator.
            source = KnowledgeSource(provider="cecemate-manual", title=label[:500], excerpt=match.excerpt, dataset_name=meta.title)
            hits.append(RetrievalHit(content=match.excerpt, source=source, score=match.score))
        return RetrievalResult(hits=hits)
