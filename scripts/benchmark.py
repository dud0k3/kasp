"""Small streaming benchmark. No prompts or model replies are saved."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
from urllib.request import Request, urlopen


def request_once(base_url, token, model, prompt, output_tokens):
    payload = {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": output_tokens, "temperature": 0, "ignore_eos": True,
        "stream": True, "stream_options": {"include_usage": True},
    }
    req = Request(base_url + "/v1/chat/completions", data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    started = time.perf_counter()
    ttft = None
    usage = None
    done = False
    with urlopen(req, timeout=600) as response:
        for raw in response:
            if not raw.startswith(b"data: "):
                continue
            data = raw[6:].strip()
            if data == b"[DONE]":
                done = True
                break
            chunk = json.loads(data)
            if "error" in chunk:
                raise RuntimeError("Streaming API returned an error")
            if chunk.get("usage"):
                usage = chunk["usage"]
            if any(c.get("delta", {}).get("content") for c in chunk.get("choices", [])) and ttft is None:
                ttft = time.perf_counter() - started
    latency = time.perf_counter() - started
    if not done or ttft is None or not usage or usage["completion_tokens"] < 1:
        raise RuntimeError("Incomplete stream or missing token usage")
    return {"ttft_s": ttft, "latency_s": latency, "prompt_tokens": usage["prompt_tokens"],
            "output_tokens": usage["completion_tokens"]}


def percentile(values, p):
    ordered = sorted(values)
    i = (len(ordered) - 1) * p
    low = int(i)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (i - low)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", default=".secrets/api-key")
    parser.add_argument("--model", default="qwen-cpu")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--output-tokens", type=int, default=32)
    parser.add_argument("--out", default="results/benchmark.json")
    args = parser.parse_args()
    if args.requests < 1 or min(args.concurrency) < 1:
        parser.error("requests and concurrency must be positive")
    token = Path(args.token_file).read_text().strip()
    prompts = {
        "short": "Explain what a database index is in simple words.",
        "long": ("A service receives events, checks their schema and stores them in a database. " * 70
                 + "Summarize the main steps and suggest one improvement."),
    }
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "requests_per_case": args.requests, "output_tokens_requested": args.output_tokens,
              "prefix_caching": False, "cases": []}
    for name, prompt in prompts.items():
        # Warmup is excluded from all measured cases.
        request_once(args.base_url, token, args.model, prompt, args.output_tokens)
        for concurrency in args.concurrency:
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                samples = list(executor.map(lambda _: request_once(
                    args.base_url, token, args.model, prompt, args.output_tokens), range(args.requests)))
            elapsed = time.perf_counter() - start
            case = {
                "prompt": name, "concurrency": concurrency, "wall_s": elapsed,
                "ttft_mean_s": statistics.mean(s["ttft_s"] for s in samples),
                "ttft_p95_s": percentile([s["ttft_s"] for s in samples], 0.95),
                "latency_mean_s": statistics.mean(s["latency_s"] for s in samples),
                "latency_p95_s": percentile([s["latency_s"] for s in samples], 0.95),
                "output_tokens_per_s": sum(s["output_tokens"] for s in samples) / elapsed,
                "requests_per_s": len(samples) / elapsed, "samples": samples,
            }
            result["cases"].append(case)
            print(name, "concurrency=", concurrency, "TTFT=", round(case["ttft_mean_s"], 3),
                  "latency=", round(case["latency_mean_s"], 3),
                  "output tok/s=", round(case["output_tokens_per_s"], 2), flush=True)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
