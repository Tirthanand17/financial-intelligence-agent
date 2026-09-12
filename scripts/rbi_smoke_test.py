import json
import sys

import httpx


API_BASE = "http://127.0.0.1:8000"
DEFAULT_RBI_URL = "https://www.rbi.org.in/"
DEFAULT_QUESTION = "What policy repo rate is shown on the RBI website?"


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RBI_URL
    question = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_QUESTION

    with httpx.Client(timeout=120.0) as client:
        ingest = client.post(
            f"{API_BASE}/ingest",
            json={"source_id": "rbi", "url": url},
        )
        ingest.raise_for_status()
        print("INGEST RESULT")
        print(json.dumps(ingest.json(), indent=2))

        answer = client.post(
            f"{API_BASE}/ask",
            json={"question": question, "source_id": "rbi", "top_k": 5},
        )
        answer.raise_for_status()
        print("\nANSWER RESULT")
        print(json.dumps(answer.json(), indent=2))


if __name__ == "__main__":
    main()
