"""Deterministic Chinese bigram BM25; index built once, no models or IO."""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .config import Settings
from .corpus import Corpus, Entry

_RUNS = re.compile(r"[\u3400-\u9fff]+|[a-z0-9]+")
_CAVEAT = re.compile(r"限制|不支持|不提供|不能|不可|不保证|不代表|不限|不超过|仅|最多|上限|注意|下线|暂不|暂无|不含|除外|条数|口径")
_QUESTION_WORDS = re.compile(
    r"行业洞察|cecemate|平台|是否|支持|有没有|有哪些|有什么|用什么|能做什么|是做什么|是什么|在哪里查|哪里查|怎么查|怎么找|怎么检索|怎么|如何|哪里|功能|可以|能够|请问|想看|一家|某条|一个|里的|相关|吗|呢"
)


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()


def tokenize(text):
    tokens = []
    for run in _RUNS.findall(normalize(text)):
        if "\u3400" <= run[0] <= "\u9fff":
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    return tokens


@dataclass(frozen=True)
class Match:
    entry: Entry
    excerpt: str
    score: float
    partial: bool = False


class Retriever:
    def __init__(self, corpus: Corpus, settings: Settings):
        self.corpus = corpus
        self.settings = settings
        self._counts = []
        self._lengths = []
        df = Counter()
        self._fields = []
        self._title_terms = []
        for entry in corpus.entries:
            # Field weighting retains ordinary BM25 length normalization for body text.
            fields = [(entry.title, 4), (" ".join(entry.aliases), 3), (" ".join(entry.scenarios), 2), (entry.module, 1), (entry.content, 1)]
            counts = Counter()
            for text, weight in fields:
                for term, count in Counter(tokenize(text)).items():
                    counts[term] += count * weight
            self._counts.append(counts)
            self._lengths.append(sum(counts.values()))
            df.update(counts.keys())
            self._fields.append(normalize(" ".join([entry.title, *entry.aliases, *entry.scenarios])))
            self._title_terms.append(set(tokenize(entry.title)))
        n = len(corpus.entries)
        self._idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        self._average = sum(self._lengths) / max(n, 1)
        self._expansions = tuple(tuple(normalize(t) for t in (key, *values)) for key, values in corpus.aliases.items())

    def _query(self, query):
        if not isinstance(query, str) or len(query) > self.settings.max_query_chars:
            raise ValueError("Invalid or oversized manual query")
        query = normalize(query).strip()
        # General product/question words are not evidence of a requested feature.
        # Keep overview-only questions valid, but abstain when most substantive
        # bigrams are unknown to the corpus (e.g. an unsupported technology).
        topic_terms = set(tokenize(_QUESTION_WORDS.sub(" ", query)))
        if topic_terms and sum(term in self._idf for term in topic_terms) / len(topic_terms) < 0.5:
            return query, {}
        weights = {term: 1.0 for term in (topic_terms or tokenize(query))}
        if re.search(r"服务形式|服务形态|产品定位", query):
            for term in tokenize("平台定位 产品概述"):
                weights.setdefault(term, 0.75)
        # One hop, bidirectional synonym groups; expansion never triggers other groups.
        for group in self._expansions:
            if any(term in query for term in group):
                for term in tokenize(" ".join(group)):
                    weights.setdefault(term, 0.55)
        return query, weights

    def search(self, query):
        query, weights = self._query(query)
        if not weights:
            return []
        ranked = []
        for index, entry in enumerate(self.corpus.entries):
            if entry.status == "retired":
                # Only the actual title (minus explicit retirement markup) unlocks old evidence.
                title = re.sub(r"[（(](?:已下线|下线|已停用|停用)[）)]", "", normalize(entry.title)).replace("~", "").strip()
                if len(title) < 2 or title not in query:
                    continue
            counts = self._counts[index]
            score = 0.0
            for term, weight in weights.items():
                tf = counts.get(term, 0)
                if tf:
                    score += weight * self._idf[term] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * self._lengths[index] / self._average))
            if score <= 0:
                continue
            score += sum(self._idf.get(term, 0) * weights.get(term, 0) * (2 + 4 / max(1, len(self._title_terms[index]))) for term in self._title_terms[index])
            # Reward literal topic phrases without any special handling of example queries.
            for phrase in (entry.title, *entry.aliases, *entry.scenarios):
                phrase = normalize(phrase)
                if len(phrase) >= 2 and phrase in query:
                    score += min(len(phrase), 12) * 0.6
            ranked.append((score, index, entry))
        # Greedy topic coverage prevents six near-duplicate body mentions from
        # crowding distinct requested features out of a multi-topic question.
        ordered = []
        covered = set()
        while ranked:
            best = max(
                ranked,
                key=lambda row: (
                    row[0]
                    + 4 * sum(self._idf.get(t, 0) * weights.get(t, 0) for t in self._title_terms[row[1]] - covered)
                    - 3 * sum(self._idf.get(t, 0) * weights.get(t, 0) for t in self._title_terms[row[1]] & covered),
                    -row[1],
                ),
            )
            ranked.remove(best)
            ordered.append(best)
            covered.update(self._title_terms[best[1]])
        result = []
        remaining = self.settings.max_total_chars
        for score, _, entry in ordered:
            if len(result) >= self.settings.max_hits:
                break
            fragments = self._excerpts(entry.content, weights, remaining)
            if not fragments or len(result) + len(fragments) > self.settings.max_hits:
                continue
            for excerpt in fragments:
                result.append(Match(entry, excerpt, score, len(fragments) > 1 or excerpt != entry.content.strip()))
                remaining -= len(excerpt)
        return result

    def _excerpts(self, content, weights, budget):
        cap = min(budget, self.settings.max_excerpt_chars)
        if len(content.strip()) <= cap:
            return [content.strip()]
        # Reserve every caveat, then fill the available span with neighboring
        # definition/features. Coalescing may include intervening source text;
        # this preserves context and avoids tiny fragments consuming hit slots.
        matches = [m for m in re.finditer(r"[^\n。！？]+[。！？]?", content) if m.group().strip()]
        parts = [m.group().strip() for m in matches]
        spans = [(m.start() + len(m.group()) - len(m.group().lstrip()), m.end() - len(m.group()) + len(m.group().rstrip())) for m in matches]
        caveats = {i for i, part in enumerate(parts) if _CAVEAT.search(part)}
        relevance = [sum(self._idf.get(t, 0) * weights.get(t, 0) for t in set(tokenize(part))) for part in parts]
        if not relevance or max(relevance) <= 0:
            return []
        best = max(range(len(parts)), key=lambda i: relevance[i])
        selected = caveats | {best}

        def groups_for(indices):
            groups = []
            for i in sorted(indices):
                start, end = spans[i]
                if groups and end - groups[-1][0] <= cap:
                    groups[-1] = (groups[-1][0], end)
                else:
                    groups.append((start, end))
            return groups

        groups = groups_for(selected)
        # Never spend more than one excerpt's character allowance per topic,
        # unless the caveats alone require more space. Keep their exact wording.
        allowance = min(budget, max(cap, sum(end - start for start, end in groups)))
        if any(end - start > cap for start, end in groups) or sum(end - start for start, end in groups) > budget:
            return []
        # Relevant sentences first, then nearby sentences, until the allowance is full.
        candidates = sorted(set(range(len(parts))) - selected, key=lambda i: (-relevance[i], abs(i - best), i))
        for i in candidates:
            proposed = groups_for(selected | {i})
            if all(end - start <= cap for start, end in proposed) and sum(end - start for start, end in proposed) <= allowance:
                selected.add(i)
                groups = proposed
        return [content[start:end] for start, end in groups]
