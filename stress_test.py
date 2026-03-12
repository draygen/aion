"""
stress_test.py — Concurrent load test for Aion with live GPU monitoring.

Fires N parallel chat threads against the live server while sampling
nvidia-smi every 500ms, then prints a timeline and latency distribution.

Usage: python3 stress_test.py [--workers 4] [--requests 20] [--host localhost:5000]
"""

import argparse
import queue
import subprocess
import sys
import threading
import time
import requests as req

# ─────────────────────────────────────────────────────────────────────────────

PROMPTS = [
    "What are Brian's main hobbies?",
    "Tell me something about Aion the AI assistant.",
    "What's the best way to optimize Python code?",
    "Who is Brian and what does he work on?",
    "Give me a one-sentence summary of machine learning.",
    "What is the capital of France?",
    "How does TF-IDF work?",
    "What's a good breakfast for a developer?",
    "What is CUDA and why does it matter?",
    "Explain what an RTX 4060 Ti is good for.",
]

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RST    = "\033[0m"

# ─────────────────────────────────────────────────────────────────────────────

def login(host, username="brian", password="stress2026"):
    s = req.Session()
    r = s.post(f"http://{host}/api/login",
               json={"username": username, "password": password}, timeout=10)
    if r.status_code != 200 or not r.json().get("ok"):
        print(f"{RED}Login failed: {r.text[:120]}{RST}")
        sys.exit(1)
    return s


def send_chat(session, host, prompt, result_q, idx):
    t0 = time.perf_counter()
    try:
        r = session.post(
            f"http://{host}/api/chat",
            json={"message": prompt, "tts": False},
            timeout=60,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        ok = r.status_code == 200
        answer = (r.json().get("response", "") if ok else r.text)[:60]
        result_q.put({"idx": idx, "ok": ok, "ms": elapsed,
                      "prompt": prompt[:40], "answer": answer})
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        result_q.put({"idx": idx, "ok": False, "ms": elapsed,
                      "prompt": prompt[:40], "answer": str(e)[:60]})


def sample_gpu(samples, stop_event, interval=0.4):
    while not stop_event.is_set():
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                parts = r.stdout.strip().split(", ")
                if len(parts) >= 2:
                    samples.append({
                        "t": time.perf_counter(),
                        "util": int(parts[0]),
                        "mem":  int(parts[1]),
                        "pwr":  float(parts[2]) if len(parts) > 2 else 0,
                    })
        except Exception:
            pass
        time.sleep(interval)


# ─────────────────────────────────────────────────────────────────────────────

def run_stress(host, workers, total_requests, username, password):
    print(f"\n{BOLD}{'━'*62}{RST}")
    print(f"{BOLD}  Aion GPU Stress Test{RST}")
    print(f"  Host: {host}  |  Workers: {workers}  |  Requests: {total_requests}")
    print(f"{BOLD}{'━'*62}{RST}\n")

    session = login(host, username, password)

    # Kick off GPU sampler
    gpu_samples = []
    stop_gpu = threading.Event()
    gpu_thread = threading.Thread(target=sample_gpu, args=(gpu_samples, stop_gpu), daemon=True)
    gpu_thread.start()

    result_q = queue.Queue()
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(total_requests)]

    print(f"  {YELLOW}Sending {total_requests} requests across {workers} workers...{RST}\n")
    t_start = time.perf_counter()
    active_threads = []

    # Feed requests in batches of `workers`
    for batch_start in range(0, total_requests, workers):
        batch = prompts[batch_start: batch_start + workers]
        threads = []
        for i, prompt in enumerate(batch):
            t = threading.Thread(
                target=send_chat,
                args=(session, host, prompt, result_q, batch_start + i),
                daemon=True,
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)

    total_wall = (time.perf_counter() - t_start) * 1000
    stop_gpu.set()
    gpu_thread.join(timeout=2)

    # ── Collect results ────────────────────────────────────────────────────
    results = []
    while not result_q.empty():
        results.append(result_q.get())
    results.sort(key=lambda r: r["idx"])

    # ── Print per-request results ──────────────────────────────────────────
    print(f"  {'#':<4} {'ms':>7}  {'status':<6}  {'prompt':<40}  answer")
    print(f"  {'─'*4} {'─'*7}  {'─'*6}  {'─'*40}  {'─'*30}")
    for r in results:
        icon  = f"{GREEN}✓{RST}" if r["ok"] else f"{RED}✗{RST}"
        flag  = ""
        color = RST
        if r["ms"] > 15000:
            flag = f" {RED}[SLOW]{RST}"
            color = RED
        elif r["ms"] > 5000:
            flag = f" {YELLOW}[slow]{RST}"
        print(f"  {r['idx']:<4} {color}{r['ms']:>7.0f}{RST}ms  {icon}      "
              f"  {r['prompt']:<40}  {r['answer'][:35]!r}{flag}")

    # ── Latency stats ──────────────────────────────────────────────────────
    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    if passed:
        lats  = sorted(r["ms"] for r in passed)
        p50   = lats[len(lats)//2]
        p95   = lats[int(len(lats)*0.95)]
        p99   = lats[min(int(len(lats)*0.99), len(lats)-1)]
        avg   = sum(lats)/len(lats)
        rps   = len(passed) / (total_wall / 1000)

    print(f"\n{BOLD}  Latency (ms){RST}                {BOLD}GPU during test{RST}")
    print(f"  {'─'*30}  {'─'*28}")
    if passed:
        print(f"  Avg      {avg:>8.0f}ms")
        print(f"  p50      {p50:>8.0f}ms")
        print(f"  p95      {p95:>8.0f}ms")
        print(f"  p99      {p99:>8.0f}ms")
        print(f"  Min      {lats[0]:>8.0f}ms")
        print(f"  Max      {lats[-1]:>8.0f}ms")
        print(f"  RPS      {rps:>8.2f}")

    if gpu_samples:
        peak_util = max(s["util"] for s in gpu_samples)
        avg_util  = sum(s["util"] for s in gpu_samples) / len(gpu_samples)
        peak_mem  = max(s["mem"]  for s in gpu_samples)
        peak_pwr  = max(s["pwr"]  for s in gpu_samples)
        avg_pwr   = sum(s["pwr"]  for s in gpu_samples) / len(gpu_samples)

        # Print GPU timeline (bar chart)
        print(f"\n  {BOLD}GPU utilization timeline (each bar = ~0.4s){RST}")
        for s in gpu_samples:
            u = s["util"]
            bar_len = u // 5
            color = GREEN if u < 50 else (YELLOW if u < 80 else RED)
            bar = f"{color}{'█'*bar_len}{RST}"
            print(f"    {u:3d}%  {bar}")

        print(f"\n  {BOLD}GPU Summary{RST}")
        print(f"    Peak util  : {peak_util}%")
        print(f"    Avg util   : {avg_util:.0f}%")
        print(f"    Peak VRAM  : {peak_mem} MiB / 8188 MiB")
        print(f"    Peak power : {peak_pwr:.0f}W / 160W")
        print(f"    Avg power  : {avg_pwr:.0f}W")

    print(f"\n  {BOLD}Results{RST}: {GREEN}{len(passed)} passed{RST}",
          f"  {RED}{len(failed)} failed{RST}" if failed else "",
          f"  |  Total wall time: {total_wall/1000:.1f}s")
    print(f"{BOLD}{'━'*62}{RST}\n")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aion GPU stress test")
    parser.add_argument("--workers",  type=int, default=4,            help="concurrent workers")
    parser.add_argument("--requests", type=int, default=12,           help="total requests to send")
    parser.add_argument("--host",     default="localhost:5000",        help="Aion host:port")
    parser.add_argument("--user",     default="brian",                 help="username")
    parser.add_argument("--password", default="stress2026",            help="password")
    args = parser.parse_args()

    run_stress(args.host, args.workers, args.requests, args.user, args.password)
