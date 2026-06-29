import multiprocessing
import signal
import sys
import uvicorn

SERVERS = [
    ("tests.dummy_providers.openai_dummy:app", 8001, "OpenAI"),
    ("tests.dummy_providers.anthropic_dummy:app", 8002, "Anthropic"),
    ("tests.dummy_providers.gemini_dummy:app", 8003, "Gemini"),
    ("tests.dummy_providers.ollama_dummy:app", 8004, "Ollama"),
]


def _run(app_str: str, port: int, name: str):
    print(f"[{name}] listening on port {port}", flush=True)
    uvicorn.run(app_str, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    processes = []
    for app_str, port, name in SERVERS:
        p = multiprocessing.Process(target=_run, args=(app_str, port, name), daemon=True)
        p.start()
        processes.append(p)

    print("All dummy providers running:")
    print("  OpenAI    → http://localhost:8001")
    print("  Anthropic → http://localhost:8002")
    print("  Gemini    → http://localhost:8003")
    print("  Ollama    → http://localhost:8004")
    print("Press Ctrl+C to stop all.\n")

    def _shutdown(sig, frame):
        print("\nShutting down all dummy servers...")
        for p in processes:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for p in processes:
        p.join()
