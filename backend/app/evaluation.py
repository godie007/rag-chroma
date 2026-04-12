from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from datasets import Dataset
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import aevaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from app.config import Settings
from app.rag_service import RAGService

logger = logging.getLogger("rag_qc")

METRIC_LABELS_ES: dict[str, str] = {
    "faithfulness": "Fidelidad",
    "answer_relevancy": "Relevancia",
    "context_precision": "Precisión del contexto",
    "context_recall": "Recuperación",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


async def run_ragas_evaluation_async(
    rag: RAGService,
    settings: Settings,
    eval_path: Path,
) -> dict[str, Any]:
    if not eval_path.is_file():
        raise FileNotFoundError(f"No existe el archivo de evaluación: {eval_path}")

    raw = read_jsonl(eval_path)
    if not raw:
        raise ValueError("El archivo de evaluación no tiene filas JSON válidas")

    questions: list[str] = []
    ground_truths: list[str] = []
    answers: list[str] = []
    contexts_list: list[list[str]] = []

    for row in raw:
        q = row["question"]
        gt = row["ground_truth"]
        logger.info("Evaluación RAGAS, pregunta: %s", q[:72] + ("…" if len(q) > 72 else ""))
        chunks = rag.retrieve(q, infer_broad_retrieval=False)
        answer, _used = rag.generate(q, chunks)
        questions.append(q)
        ground_truths.append(gt)
        answers.append(answer)
        contexts_list.append([c.content for c in chunks])

    ds = Dataset.from_dict(
        {
            "question": questions,
            "ground_truth": ground_truths,
            "answer": answers,
            "contexts": contexts_list,
        }
    )

    common: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_api_base:
        common["base_url"] = settings.openai_api_base

    llm = LangchainLLMWrapper(
        ChatOpenAI(model=settings.openai_chat_model, temperature=0, **common)
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=settings.openai_embedding_model, **common)
    )

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    result = await aevaluate(
        ds,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=True,
    )

    metric_names = list(result.scores[0].keys())
    averages = {k: float(np.nanmean([row[k] for row in result.scores])) for k in metric_names}

    per_question: list[dict[str, Any]] = []
    for i, score_row in enumerate(result.scores):
        ans = answers[i]
        preview = ans if len(ans) <= 200 else ans[:200] + "…"
        per_question.append(
            {
                "question": questions[i],
                "answer_preview": preview,
                "scores": {k: float(v) if v == v else None for k, v in score_row.items()},
            }
        )

    return {
        "eval_file": str(eval_path),
        "averages": averages,
        "metric_labels_es": METRIC_LABELS_ES,
        "ragas_metric_keys": metric_names,
        "per_question": per_question,
    }
