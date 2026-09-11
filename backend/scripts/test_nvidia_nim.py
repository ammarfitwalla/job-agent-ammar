#!/usr/bin/env python3
"""Standalone benchmark: NVIDIA NIM (nemotron) vs current Groq primary.

Uses the app's REAL prompts (relevance scoring, internship scoring, batch
scoring, keyword extraction) to compare:
  - speed  : per-call latency + tokens/sec
  - quality: JSON validity, is_relevant correctness vs labelled cases,
             score-in-band agreement, keyword structure sanity

Run from anywhere:
    set NVIDIA_API_KEY=<your key>            # required for the NVIDIA leg
    set GROQ_API_KEY=<your key>              # required for the Groq comparison leg
    python backend/scripts/test_nvidia_nim.py

Flags:
    --runs N           repeat each case N times (default 1)
    --model M          override NVIDIA model (default: NVIDIA_MODEL env, else
                       nvidia/nemotron-3-super-120b-a12b)
    --nvidia-only      skip the Groq comparison leg
    --no-batch         skip the batch-scoring case
    --no-keywords      skip the keyword-extraction case
    --resume FILE      resume text to score against (default backend/resume.txt)
"""
import argparse
import json
import os
import statistics
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("PYTHONUNBUFFERED", "1")


# Known "correct" answers for the scoring cases, judged against
# backend/resume.txt (cloud/devops-focused resume). Bands are generous on
# purpose so the benchmark measures "right direction", not exact scores.
SCORE_CASES = [
    dict(
        label="DevOps Engineer",
        internship=False,
        job_title="DevOps Engineer",
        jd=(
            "We are looking for a DevOps Engineer to own CI/CD pipelines. "
            "Stack: Docker, Kubernetes, Terraform, AWS (EC2, S3, IAM), "
            "Jenkins, GitHub Actions, Bash, Linux. Must manage containers, "
            "IaC and automated deployments for production workloads. "
            "2+ years experience."
        ),
        exp_true=True,
        exp_band=(50, 95),
    ),
    dict(
        label="Cloud Solutions Architect",
        internship=False,
        job_title="Cloud Solutions Architect",
        jd=(
            "Design multi-cloud infrastructure on AWS, Azure and GCP. "
            "Deep knowledge of VPC, IAM, CloudFormation, S3, Terraform, "
            "GitOps and self-service developer portals. Use Backstage "
            "catalog and templating to onboard internal teams."
        ),
        exp_true=True,
        exp_band=(40, 85),
    ),
    dict(
        label="ML Engineer (mismatch)",
        internship=False,
        job_title="Senior Machine Learning Engineer",
        jd=(
            "Train and deploy LLMs at scale. PyTorch, TensorFlow, "
            "Kubernetes, model serving, MLOps, GPU clusters, Ray. "
            "Requires 6+ years of ML experience and a published track record."
        ),
        exp_true=False,
        exp_band=(0, 35),
    ),
    dict(
        label="Sales (mismatch)",
        internship=False,
        job_title="Enterprise Account Manager",
        jd=(
            "Own quota for SaaS accounts. Cold calling, pipeline management, "
            "CRM hygiene, forecasting, customer success reviews. "
            "3+ years in enterprise B2B sales."
        ),
        exp_true=False,
        exp_band=(0, 25),
    ),
    dict(
        label="Cloud Platform Intern",
        internship=True,
        job_title="Platform Engineering Intern",
        jd=(
            "Help our platform team containerize services with Docker and "
            "Docker Compose, write Terraform modules for AWS, automate "
            "CI/CD with GitHub Actions and Jenkins, and keep Linux servers healthy."
        ),
        exp_true=True,
        exp_band=(40, 85),
    ),
]

BATCH_BUNDLE = ["DevOps Engineer", "Sales (mismatch)", "ML Engineer (mismatch)"]


def load_resume(path):
    if not path:
        path = os.path.join(_BACKEND_DIR, "resume.txt")
    if not os.path.isfile(path):
        print(f"!! resume not found at {path} — pass --resume FILE")
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * len(sorted_vals)) - 1)))
    return sorted_vals[idx]


def check_single(parsed, exp_true, exp_band):
    """Return (status, correct_bool)."""
    if not isinstance(parsed, dict):
        return ("bad_json", False)
    score = parsed.get("score")
    rel = parsed.get("is_relevant")
    ok_band = isinstance(score, (int, float)) and exp_band[0] <= score <= exp_band[1]
    ok_rel = isinstance(rel, bool) and rel == exp_true
    return ("ok", ok_band and ok_rel)


def check_batch(parsed, exps):
    if not isinstance(parsed, list) or len(parsed) != len(exps):
        return ("bad_json", False)
    for item, (exp_true, exp_band) in zip(parsed, exps):
        status, ok = check_single(item, exp_true, exp_band)
        if not ok:
            return (status, False)
    return ("ok", True)


def check_keywords(parsed, available_roles):
    if not isinstance(parsed, dict):
        return ("bad_json", False)
    kw = parsed.get("keywords", [])
    roles = parsed.get("suggested_roles", [])
    ok = (
        isinstance(kw, list) and 3 <= len(kw) <= 40 and
        all(isinstance(k, str) and k.strip() for k in kw) and
        isinstance(roles, list) and len(roles) <= 3 and
        all(r in available_roles for r in roles)
    )
    return ("ok" if ok else "keys", ok)


def nvidia_chat(model, api_key, prompt, max_tokens):
    ticks = time.monotonic()
    from openai import OpenAI
    client = OpenAI(base_url="https://integrate.api.nvidia.com/v1",
                    api_key=api_key, timeout=60)
    comp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=max_tokens,
        top_p=0.95,
        stream=False,
        timeout=60,
    )
    elapsed = time.monotonic() - ticks
    content = (comp.choices[0].message.content or "") if comp.choices else ""
    usage = comp.usage
    finish = (comp.choices[0].finish_reason or "") if comp.choices else ""
    return content, usage, finish, elapsed


def groq_chat(model, api_key, prompt, max_tokens):
    from llm.providers import GroqProvider
    ticks = time.monotonic()
    client = GroqProvider(api_key=api_key, model=model)
    client._bucket = client._bucket.__class__(capacity=100000, refill_rate=100000 / 60)
    content = client.chat(prompt, max_tokens=max_tokens)
    elapsed = time.monotonic() - ticks
    return content, None, "?", elapsed


def run_case(chat_fn, prompt, max_tokens):
    content, usage, finish, elapsed = chat_fn(prompt, max_tokens)
    parsed = None
    if content:
        from utils.json_parser import extract_json
        parsed = extract_json(content)
    total_tokens = 0
    if usage:
        total_tokens = (getattr(usage, "prompt_tokens", 0) or 0) + \
                       (getattr(usage, "completion_tokens", 0) or 0)
    return dict(
        elapsed=elapsed,
        chars=len(content),
        tps=round(total_tokens / elapsed, 1) if elapsed > 0 else 0.0,
        finish=finish,
        parsed=parsed,
    )


def main():
    ap = argparse.ArgumentParser(description="NVIDIA NIM vs Groq LLM bench")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default=os.environ.get(
        "NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"))
    ap.add_argument("--nvidia-only", action="store_true")
    ap.add_argument("--no-batch", action="store_true")
    ap.add_argument("--no-keywords", action="store_true")
    ap.add_argument("--resume", default="")
    args = ap.parse_args()

    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    if not nvidia_key:
        print("NVIDIA_API_KEY is not set — nothing to benchmark")
        return 2

    resume = load_resume(args.resume)
    if not resume:
        print("No resume to score against — aborting")
        return 2

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        try:
            import config
            groq_key = getattr(config, "GROQ_API_KEY", "")
        except Exception:
            pass
    groq_model = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
    groq_kw_model = os.environ.get("GROQ_KEYWORDS_MODEL", "openai/gpt-oss-20b")

    providers = {"NVIDIA NIM": {"key": nvidia_key, "model": args.model}}
    runners = {"NVIDIA NIM": lambda p, mt, c: nvidia_chat(c["model"], c["key"], p, mt)}

    if not args.nvidia_only:
        if not groq_key:
            print("GROQ_API_KEY is not set — skipping the Groq comparison leg")
        else:
            providers["GROQ"] = {"key": groq_key, "model": groq_model}
            runners["GROQ"] = lambda p, mt, c: groq_chat(c["model"], c["key"], p, mt)

    print(f"\nResume: {os.path.basename(args.resume) or 'backend/resume.txt'} "
          f"({len(resume)} chars)")
    print("Prompt set: relevance / internship / batch / keywords\n")

    results = {name: [] for name in providers}

    def run_case_all(name, label, prompt, max_tokens, checker, checker_args):
        for _ in range(args.runs):
            print(f"[{name}] {label} ...", flush=True)
            t_start = time.monotonic()
            r = run_case(lambda p, mt: runners[name](p, mt, providers[name]),
                         prompt, max_tokens)
            status, acc = checker(r["parsed"], *checker_args)
            r["status"] = status
            r["acc"] = acc
            results[name].append(dict(label=label, **r))
            print(f"[{name}] {label}: {r['elapsed']:.1f}s "
                  f"status={status} acc={'OK' if acc else 'MISS'}", flush=True)

    from llm.prompts import (relevance_prompt, internship_relevance_prompt,
                             batch_relevance_prompt)
    from config import TARGET_ROLES

    try:
        from api.routes.resume import EXTRACT_PROMPT
    except Exception:
        EXTRACT_PROMPT = DEFAULT_KEYWORDS_PROMPT

    for c in SCORE_CASES:
        pf = internship_relevance_prompt if c["internship"] else relevance_prompt
        prompt = pf(job_title=c["job_title"], jd=c["jd"], resume=resume)
        for name in providers:
            run_case_all(name, c["label"], prompt, 3000, check_single,
                         (c["exp_true"], c["exp_band"]))

    if not args.no_batch:
        picked = [x for x in SCORE_CASES if x["label"] in BATCH_BUNDLE]
        prompt = batch_relevance_prompt(
            [(x["job_title"], x["jd"], None) for x in picked], resume=resume)
        exps = [(x["exp_true"], x["exp_band"]) for x in picked]
        for name in providers:
            run_case_all(name, "Batch(3)", prompt, 3000, check_batch, (exps,))

    if not args.no_keywords:
        prompt = EXTRACT_PROMPT.format(available_roles=json.dumps(TARGET_ROLES),
                                       resume=resume)
        for name in providers:
            run_case_all(name, "Keywords", prompt, 4000, check_keywords,
                         (TARGET_ROLES,))

    hdr = f"{'case':<26} {'sec':>7} {'tok/s':>7} {'chars':>7} {'status/acc':>10}"
    for name in results:
        rows = results[name]
        print(f"== {name} ==  ({providers[name]['model']})  "
              f"{args.runs} run(s) per case")
        print(hdr)
        for r in rows:
            acc = "OK" if r["acc"] else "MISS"
            print(f"{r['label']:<26} {r['elapsed']:>6.1f} "
                  f"{r['tps']:>7} {r['chars']:>7} "
                  f"{r['status'] + '/' + acc:>10}")
        times = sorted(r["elapsed"] for r in rows)
        tps = [r["tps"] for r in rows]
        accs = [r["acc"] for r in rows]
        print(f"{'MEAN':<26} {statistics.mean(times):>6.2f} "
              f"{statistics.mean(tps):>7.1f}")
        print(f"{'P50':<26} {percentile(times, 50):>6.2f}")
        print(f"{'P95':<26} {percentile(times, 95):>6.2f}")
        print(f"{'ACCURACY':<26} {sum(accs)}/{len(accs)} correct "
              f"({100.0 * sum(accs) / len(accs):.0f}%)\n")

    print("Note: acc=OK means is_relevant==expected AND score in expected band "
          "(generous bands).")


DEFAULT_KEYWORDS_PROMPT = """You are a career coach. Given a resume, do TWO things:

PART 1: Extract the top 20 most relevant keywords (skills, tools, certifications, domain expertise) that explicitly appear in the resume text. ONLY extract what is literally written.

PART 2: From the available roles list, decide 0-3 roles matching the candidate's career track.

Priority: (1) job titles AND what the bullet points under each role actually describe doing/building, (2) dominant domain across most recent/primary work experience, (3) degree/field of study as a tiebreaker.

Do NOT suggest a role based on one skill.
No clear match -> return an empty array.

Available roles: {available_roles}

Resume:
{resume}

Return ONLY the raw JSON object, no markdown fences:
{{"keywords": ["keyword1", "keyword2", ...], "suggested_roles": ["Role 1", "Role 2"]}}
"""


if __name__ == "__main__":
    raise SystemExit(main())