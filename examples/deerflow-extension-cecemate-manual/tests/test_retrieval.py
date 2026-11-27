"""Offline lexical ranking, corpus validation and evidence regressions."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_extension_cecemate_manual.config import Settings
from deerflow_extension_cecemate_manual.corpus import Corpus
from deerflow_extension_cecemate_manual.retrieval import Retriever


@pytest.fixture
def data():
    rows = [
        ("overview", "概览", "平台介绍", ["服务形式"], ["平台是做什么"], "平台提供产业数据查询与咨询服务。服务形式包括在线平台与专项报告。"),
        ("chain", "产业链", "产业链图谱", ["上下游"], ["企业分布", "区域评分"], "查询产业链上下游企业分布及区域评分。评分仅供参考，不代表投资建议。"),
        ("growth", "区域", "区域龙头", ["扩张", "科技企业"], ["企业成长"], "区域龙头扩张与科技企业分析。"),
        ("leads", "商机", "潜客挖掘", ["潜客", "商机"], ["挖掘客户"], "挖掘潜客商机，筛选企业线索。"),
        ("company", "企业", "企业查询", ["股东穿透", "风险", "资质", "知识产权"], ["哪里查"], "企业档案可查股东穿透、风险、资质和知识产权。不保证覆盖全部历史信息。"),
        ("bids", "企业", "招中标", ["企业上下游"], ["采购线索"], "企业上下游招中标信息查询。仅显示已公开信息。"),
        ("news", "资讯", "政策研报", ["资讯检索"], ["政策查询"], "检索政策、研报和资讯。"),
        ("retired", "资讯", "历史公告检索", ["公告"], [], "历史公告检索已下线，不再提供。"),
    ]
    entries = [
        dict(id=i, module=m, title=t, aliases=a, scenarios=s, content=c, status="retired" if i == "retired" else "active", chapter=str(n), source_lines=[n, n])
        for n, (i, m, t, a, s, c) in enumerate(rows, 1)
    ]
    manifest = dict(title="测试手册", version="1.0", date="2026-11-27", source_sha256="a" * 64, entry_count=len(entries))
    return entries, manifest, {"找客户": ["潜客", "商机"], "潜客": ["客户线索"]}


@pytest.fixture
def corpus(data):
    return Corpus.from_data(*data)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("平台是做什么服务形式", "overview"),
        ("产业链上下游企业分布区域评分", "chain"),
        ("区域龙头扩张科技企业", "growth"),
        ("挖掘潜客商机", "leads"),
        ("企业股东穿透风险资质知识产权哪里查", "company"),
        ("企业上下游招中标", "bids"),
        ("政策研报资讯检索", "news"),
        ("找客户", "leads"),
    ],
)
def test_ranking(corpus, query, expected):
    assert Retriever(corpus, Settings()).search(query)[0].entry.id == expected


def test_no_match_and_retired_gate(corpus):
    retriever = Retriever(corpus, Settings())
    for query in ("", "   ", "火星种植香蕉", "公告", "请查询企业公告"):
        assert all(hit.entry.status == "active" for hit in retriever.search(query))
    assert retriever.search("火星种植香蕉") == []
    assert retriever.search(" ") == []
    assert "retired" in [hit.entry.id for hit in retriever.search("历史公告检索现在能用吗")]


def test_cross_module_exact_evidence_and_limits(corpus):
    settings = Settings(max_hits=6, max_total_chars=300, max_excerpt_chars=200)
    hits = Retriever(corpus, settings).search("产业链区域评分和企业股东穿透风险资质知识产权")
    assert {"产业链", "企业"} <= {hit.entry.module for hit in hits}
    assert len(hits) <= 6
    assert sum(len(hit.excerpt) for hit in hits) <= 300
    assert all(hit.excerpt in hit.entry.content for hit in hits)
    assert "不代表投资建议" in next(hit.excerpt for hit in hits if hit.entry.id == "chain")


def test_distant_caveat_is_not_silently_dropped(data):
    entries, manifest, aliases = copy.deepcopy(data)
    entries[0]["content"] = "平台介绍。" + "详细信息。" * 80 + "注意：本服务不支持导出。"
    retriever = Retriever(Corpus.from_data(entries, manifest, aliases), Settings(max_excerpt_chars=100))
    hits = [hit for hit in retriever.search("平台介绍") if hit.entry.id == "overview"]
    assert hits
    assert any("平台介绍" in hit.excerpt for hit in hits)
    assert any("不支持导出" in hit.excerpt for hit in hits)
    assert all(hit.excerpt in entries[0]["content"] and len(hit.excerpt) <= 100 for hit in hits)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e, m, a: m.update(entry_count=999),
        lambda e, m, a: m.update(source_sha256="bad"),
        lambda e, m, a: e.append(e[0]),
        lambda e, m, a: e[0].update(status="unknown"),
        lambda e, m, a: e[0].update(source_lines=[2, 1]),
        lambda e, m, a: e[0].update(aliases="platform"),
        lambda e, m, a: a.update({"bad": "not a list"}),
        lambda e, m, a: e[0].update(content=""),
    ],
)
def test_invalid_corpus_fails_closed(data, mutate):
    entries, manifest, aliases = copy.deepcopy(data)
    mutate(entries, manifest, aliases)
    with pytest.raises(ValueError):
        Corpus.from_data(entries, manifest, aliases)


@pytest.mark.parametrize("config", [{"max_hits": 7}, {"max_hits": True}, {"max_query_chars": 0}, {"max_total_chars": -1}, {"max_excerpt_chars": "500"}, {"unknown": 1}])
def test_invalid_settings(config):
    with pytest.raises((ValueError, TypeError)):
        Settings.from_config(config)


def test_query_limit(corpus):
    with pytest.raises(ValueError, match="query"):
        Retriever(corpus, Settings(max_query_chars=32)).search("企" * 33)


def test_packaged_corpus():
    corpus = Corpus.load()
    assert corpus.entries
    assert len(corpus.entries) == corpus.manifest.entry_count
    retriever = Retriever(corpus, Settings())
    queries = [
        "平台是做什么服务形式",
        "产业链上下游企业分布区域评分",
        "区域龙头扩张科技企业",
        "挖掘潜客商机",
        "企业股东穿透风险资质知识产权哪里查",
        "企业上下游招中标",
        "政策研报资讯检索",
    ]
    for query in queries:
        hits = retriever.search(query)
        assert hits, query
        assert all(hit.excerpt in hit.entry.content for hit in hits)
        assert all(hit.entry.status == "active" for hit in hits)


@pytest.mark.parametrize(
    ("query", "required_titles", "required_terms"),
    [
        ("平台是做什么服务形式", {"产品与服务形态", "行业洞察产业数据服务平台定位"}, {"SaaS", "API", "本地化"}),
        ("产业链上下游企业分布区域评分", {"产业企业分布", "产业评分", "产业链评估分析"}, {"企业分布", "六大维度", "暂不支持全国"}),
        ("区域龙头扩张科技企业", {"龙头企业", "扩张企业", "科技企业", "区域企业画像"}, {"筛选"}),
        ("挖掘潜客商机", {"2.6.7 潜客挖掘", "AI潜客挖掘助手"}, {"潜客"}),
        ("企业股东穿透风险资质知识产权哪里查", {"股权穿透图", "资质榜单", "知识产权"}, {"风险", "股东", "资质"}),
        ("企业上下游招中标", {"供应链图谱", "查公告"}, {"上下游", "中标", "供应商"}),
        ("政策研报资讯检索", {"查政策", "查研报", "资讯"}, {"政策", "研报", "资讯"}),
    ],
)
def test_actual_questions_have_substantive_cross_topic_evidence(query, required_titles, required_terms):
    hits = Retriever(Corpus.load(), Settings()).search(query)
    assert required_titles <= {hit.entry.title for hit in hits}
    evidence = "\n".join(hit.excerpt for hit in hits)
    assert all(term in evidence for term in required_terms)
    assert all(len(hit.excerpt) <= 800 and hit.excerpt in hit.entry.content for hit in hits)


def test_actual_score_dimensions_and_limit_survive_excerpt_selection():
    hits = Retriever(Corpus.load(), Settings()).search("产业评分有哪些维度？")
    evidence = "\n".join(hit.excerpt for hit in hits if hit.entry.title == "产业评分")
    for term in ("六大维度", "产业规模", "优质企业", "创新能力", "融资能力", "产业效益", "成长能力", "暂不支持全国的产业评分"):
        assert term in evidence


@pytest.mark.parametrize("query", ["支持人脸识别吗", "平台是否支持量子纠错计算", "行业洞察支持火星农业种植吗"])
def test_unknown_features_do_not_match_generic_platform_words(query):
    assert Retriever(Corpus.load(), Settings()).search(query) == []


@pytest.mark.parametrize("query", ["平台有哪些功能", "行业洞察能做什么", "是否支持查企业", "支持股权穿透吗"])
def test_generic_overview_and_known_features_remain_searchable(query):
    assert Retriever(Corpus.load(), Settings()).search(query)


@pytest.mark.parametrize(
    ("query", "titles"),
    [
        ("行业洞察平台是做什么的？有哪些服务形式？", {"产品与服务形态", "行业洞察产业数据服务平台定位"}),
        ("想看某条产业链的上中下游、企业分布和区域评分，用什么功能？", {"产业评分", "产业企业分布"}),
        ("怎么找一个区域里的龙头企业、扩张企业或科技企业？", {"龙头企业", "扩张企业", "科技企业"}),
        ("想挖掘潜在客户和商机线索，有哪些功能？", {"2.6.7 潜客挖掘"}),
        ("一家企业的股东、股权穿透、风险、资质、知识产权在哪里查？", {"股权穿透图", "知识产权", "资质榜单"}),
        ("怎么查企业的上下游和招中标信息？", {"供应链图谱", "查公告"}),
        ("相关政策、行业研报、资讯怎么检索？", {"查政策", "查研报", "资讯"}),
    ],
)
def test_requirement_questions_verbatim(query, titles):
    hits = Retriever(Corpus.load(), Settings()).search(query)
    assert titles <= {hit.entry.title for hit in hits}
