"""
Retrieval strategy benchmark v2: single vector vs HyDE+vector vs HyDE+BM25+vector
Uses manually-written queries targeting specific source documents for accurate evaluation.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Load .env first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from app.rag.vector_store import VectorStoreService
from app.utils.factory import chat_model
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document

# ============================================================
# Manually-written test queries with target source filenames
# Each query is designed to test retrieval discrimination
# ============================================================
TEST_QUERIES = [
    # === Vocabulary gap queries (user language ≠ document language) ===
    # HyDE should help by generating a hypothetical answer with technical terms

    # "把大单体拆成小服务" → doc says "将单体应用拆分为多个小型独立服务" (microservices_arch)
    ("怎么把一个大系统拆成多个小服务独立部署？", "microservices_arch.txt"),
    # "怎么在多个服务间共享数据又不相互依赖" → doc about 数据管理/去中心化 (microservices_arch)
    ("微服务里每个服务都用自己的数据库，怎么处理跨服务的数据查询？", "microservices_arch.txt"),
    # "Spring Cloud全家桶有哪些东西" → doc covers Nacos, Sentinel, Gateway etc
    ("阿里开源的微服务组件有哪些，分别干什么用的？", "spring_cloud_practice.txt"),
    # "改配置不想重启服务" → doc about Nacos Config + @RefreshScope
    ("Spring Cloud应用怎么做到改配置文件不用重启？", "spring_cloud_practice.txt"),
    # "缓存没命中数据库会不会被打爆" → doc about 缓存穿透/击穿/雪崩
    ("高并发时缓存没命中，怎么防止数据库被瞬时流量打挂？", "distributed_cache.txt"),
    # "缓存数据怎么和数据库保持一致" → doc about Cache Aside / consistency
    ("更新数据库后，怎么保证缓存里的数据也是最新的？", "distributed_cache.txt"),
    # "消息队列选型" → doc compares RabbitMQ/Kafka/RocketMQ
    ("做业务系统选RabbitMQ还是Kafka，主要看什么？", "message_queue_async.txt"),
    # "消息丢了怎么办" → doc about 消息可靠性保障
    ("用消息队列异步处理订单，怎么保证消息不会丢？", "message_queue_async.txt"),
    # "网关干嘛的" → doc about API Gateway 核心功能
    ("微服务架构里网关层负责哪些事情？", "api_gateway_k8s.txt"),
    # "怎么灰度发布" → doc about 灰度发布/流量染色
    ("新版本上线怎么做到只让一小部分用户先用？", "api_gateway_k8s.txt"),
    # "JWT怎么防伪造" → doc about JWT签名验证
    ("用户登录后的身份令牌怎么防止被别人伪造？", "backend_security.txt"),
    # "SQL注入怎么防" → doc about 预编译/参数化查询
    ("用户输入恶意SQL语句怎么拦截？参数化查询的原理是什么？", "backend_security.txt"),

    # === Keyword-specific queries (BM25 should excel at exact term matching) ===
    # "Saga CQRS" → specific technical terms unique to one doc
    ("Saga模式和CQRS模式在微服务中如何应用？", "microservices_arch.txt"),
    # "Sentinel 熔断降级" → specific Spring Cloud terms
    ("Sentinel的熔断降级机制是如何工作的？", "spring_cloud_practice.txt"),
    # "布隆过滤器 缓存穿透" → specific cache terms
    ("如何用布隆过滤器解决缓存穿透问题？", "distributed_cache.txt"),
    # "死信队列" → specific RabbitMQ term
    ("RabbitMQ的死信队列机制如何处理消费失败的消息？", "message_queue_async.txt"),
    # "Service Mesh" → specific K8s governance term
    ("Service Mesh和API网关在服务治理中的职责有什么不同？", "api_gateway_k8s.txt"),
    # "CSRF Token SameSite" → specific security terms
    ("CSRF攻击的防御措施有哪些？SameSite Cookie和CSRF Token怎么配合？", "backend_security.txt"),

    # === Cross-topic ambiguous queries (could match multiple docs) ===
    # "限流" appears in spring_cloud (Sentinel), api_gateway, distributed_cache → want api_gateway
    ("微服务中应该在哪个层面做统一的限流和鉴权？", "api_gateway_k8s.txt"),
    # "服务发现" appears in microservices_arch AND spring_cloud → want spring_cloud (more specific)
    ("Nacos作为注册中心如何实现服务发现和健康检查？", "spring_cloud_practice.txt"),
    # "异步" in message_queue AND microservices → want message_queue
    ("订单系统如何通过异步消息实现削峰填谷？", "message_queue_async.txt"),
    # "数据一致性" in distributed_cache AND message_queue → want message_queue (最终一致性)
    ("在异步消息驱动的系统中，如何保证数据的最终一致性？", "message_queue_async.txt"),
]


def get_source_from_metadata(doc: Document) -> str:
    """Extract source filename from document metadata."""
    meta = doc.metadata
    source = meta.get('source', '')
    return os.path.basename(source)


async def clean_and_index(store: VectorStoreService, user_id: str = "benchmark_user"):
    """Clean all ChromaDB data and MD5 records, then re-index."""
    # Delete all documents from ChromaDB by getting all IDs and deleting
    try:
        all_data = await asyncio.to_thread(
            store.vectors_store.get,
            include=['metadatas']
        )
        if all_data and all_data.get('ids'):
            await asyncio.to_thread(
                store.vectors_store.delete,
                ids=all_data['ids']
            )
            print(f"  Deleted {len(all_data['ids'])} existing chunks from ChromaDB")
    except Exception as e:
        print(f"  Clean warning: {e}")

    # Clear MD5 store
    from app.utils.config import chroma_config
    from app.utils.path_tool import get_abstract_path
    md5_file = get_abstract_path(chroma_config['md5_hex_store'])
    if os.path.exists(md5_file):
        os.remove(md5_file)
        print(f"  Cleared MD5 dedup store")

    # Index all documents
    await store.get_document(user_id=user_id)
    docs = await store._get_all_documents()
    print(f"  Indexed {len(docs)} total chunks")

    # Show source distribution
    sources = {}
    for d in docs:
        src = get_source_from_metadata(d)
        sources[src] = sources.get(src, 0) + 1
    print(f"  Sources: {json.dumps(sources, ensure_ascii=False, indent=2)}")
    return docs


async def strategy_vector_only(store, question, k=5):
    """Strategy A: Pure dense vector retrieval."""
    retriever = store.vectors_store.as_retriever(
        search_type='similarity',
        search_kwargs={'k': k},
    )
    return await retriever.ainvoke(question)


async def strategy_hyde_vector(store, question, k=5):
    """Strategy B: HyDE + vector retrieval."""
    hyde_prompt = PromptTemplate.from_template(
        "基于以下问题，生成一个详细的假设性回答，我会根据你的这个假设性回答在向量数据库里检索文档：\n\n"
        "问题：{query}\n\n假设性回答："
    )
    hyde_chain = hyde_prompt | chat_model | StrOutputParser()
    try:
        hypothetical_doc = await hyde_chain.ainvoke({"query": question})
    except Exception:
        hypothetical_doc = question

    retriever = store.vectors_store.as_retriever(
        search_type='similarity',
        search_kwargs={'k': k},
    )
    return await retriever.ainvoke(hypothetical_doc)


async def strategy_hyde_bm25_vector(store, question, k=5):
    """Strategy C: HyDE + BM25 + Dense ensemble (full pipeline)."""
    hyde_prompt = PromptTemplate.from_template(
        "基于以下问题，生成一个详细的假设性回答，我会根据你的这个假设性回答在向量数据库里检索文档：\n\n"
        "问题：{query}\n\n假设性回答："
    )
    hyde_chain = hyde_prompt | chat_model | StrOutputParser()
    try:
        hypothetical_doc = await hyde_chain.ainvoke({"query": question})
    except Exception:
        hypothetical_doc = question

    ensemble = await store.get_retriever(query=hypothetical_doc)
    docs = await ensemble.ainvoke(hypothetical_doc)
    return docs[:k]


def evaluate_hit(retrieved_docs, target_source, top_k):
    """Check if any document in top-k results comes from the target source."""
    for rank, doc in enumerate(retrieved_docs[:top_k]):
        src = get_source_from_metadata(doc)
        if src == target_source:
            return rank + 1  # 1-indexed rank
    return None


async def run_benchmark():
    print("=" * 65)
    print("  FastRag Retrieval Strategy Benchmark v2")
    print("  Comparison: Vector-Only vs HyDE+Vector vs HyDE+BM25+Vector")
    print("=" * 65)

    # 1. Clean + Index
    print("\n[1/3] Cleaning ChromaDB and indexing documents...")
    store = VectorStoreService()
    all_docs = await clean_and_index(store, user_id="benchmark_user")

    # 2. Run strategies on all test queries
    print(f"\n[2/3] Running {len(TEST_QUERIES)} test queries across 3 strategies...")
    K = 5

    strategies = {
        "A: Vector-Only": strategy_vector_only,
        "B: HyDE+Vector": strategy_hyde_vector,
        "C: HyDE+BM25+Vector": strategy_hyde_bm25_vector,
    }

    results = {}
    for name in strategies:
        results[name] = {"top1": 0, "top3": 0, "top5": 0, "miss": 0, "latencies": [], "ranks": []}

    for i, (question, target_source) in enumerate(TEST_QUERIES):
        # Truncate for display
        q_display = question[:70] + ("..." if len(question) > 70 else "")
        print(f"\n  [{i+1:>2}/{len(TEST_QUERIES)}] [{target_source[:25]}] {q_display}")

        for strat_name, strat_fn in strategies.items():
            t0 = time.time()
            try:
                retrieved = await strat_fn(store, question, k=K)
                elapsed = (time.time() - t0) * 1000
            except Exception as e:
                print(f"     {strat_name}: ERROR — {str(e)[:80]}")
                results[strat_name]["miss"] += 1
                results[strat_name]["latencies"].append(0)
                continue

            results[strat_name]["latencies"].append(elapsed)
            hit_rank = evaluate_hit(retrieved, target_source, K)

            if hit_rank:
                results[strat_name]["ranks"].append(hit_rank)
                if hit_rank <= 1:
                    results[strat_name]["top1"] += 1
                if hit_rank <= 3:
                    results[strat_name]["top3"] += 1
                if hit_rank <= 5:
                    results[strat_name]["top5"] += 1
                # Show retrieved sources
                top_sources = [get_source_from_metadata(d)[:20] for d in retrieved[:3]]
                print(f"     {strat_name}: HIT @{hit_rank} ({elapsed:.0f}ms) → top3: {top_sources}")
            else:
                results[strat_name]["miss"] += 1
                top_sources = [get_source_from_metadata(d)[:20] for d in retrieved[:3]]
                print(f"     {strat_name}: MISS  ({elapsed:.0f}ms) → top3: {top_sources}")

    # 3. Report
    print("\n" + "=" * 65)
    print("[3/3] FINAL RESULTS")
    print("=" * 65)
    n = len(TEST_QUERIES)

    print(f"\n  Total test queries: {n}")
    print(f"  Top-K hit rate (by source document match)\n")
    print(f"  {'Strategy':<28} {'Top-1':>8} {'Top-3':>8} {'Top-5':>8} {'Miss':>8} {'Avg Lat':>10}")
    print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    baseline = {}
    for strat_name in strategies:
        r = results[strat_name]
        t1 = r["top1"] / n * 100
        t3 = r["top3"] / n * 100
        t5 = r["top5"] / n * 100
        miss = r["miss"] / n * 100
        avg_lat = sum(r["latencies"]) / len(r["latencies"]) if r["latencies"] else 0
        print(f"  {strat_name:<28} {t1:>7.1f}% {t3:>7.1f}% {t5:>7.1f}% {miss:>7.1f}% {avg_lat:>8.0f}ms")
        baseline[strat_name] = {"top1": t1, "top3": t3, "top5": t5, "miss": miss}

    # Improvement analysis
    va = baseline["A: Vector-Only"]
    vb = baseline["B: HyDE+Vector"]
    vc = baseline["C: HyDE+BM25+Vector"]

    print(f"\n  {'='*55}")
    print(f"  IMPROVEMENT ANALYSIS (Top-5 hit rate)")
    print(f"  {'='*55}")
    print(f"  Baseline (Vector-Only):           {va['top5']:.1f}%")
    print(f"  + HyDE:                           {vb['top5']:.1f}%  ({vb['top5']-va['top5']:+.1f} pp)")
    print(f"  + HyDE + BM25 (full pipeline):    {vc['top5']:.1f}%  ({vc['top5']-va['top5']:+.1f} pp)")
    if va['top5'] > 0:
        print(f"\n  Relative improvement: {(vc['top5']-va['top5'])/va['top5']*100:+.1f}% over baseline")

    print(f"\n  {'='*55}")
    print(f"  Top-1 HIT RATE (most strict)")
    print(f"  {'='*55}")
    print(f"  Baseline: {va['top1']:.1f}% → Full Pipeline: {vc['top1']:.1f}% ({vc['top1']-va['top1']:+.1f} pp)")


import json
if __name__ == '__main__':
    asyncio.run(run_benchmark())
