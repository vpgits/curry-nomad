"""Evaluation harness — two contrasting styles.

Analytics is graded against ground truth *derived from the data itself* (run the reference
SQL); marketing is graded with deterministic guardrails + an LLM-as-judge rubric. The dataset
being self-owned is what makes the analytics evals deterministic and CI-able.
"""
