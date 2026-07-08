"""Manual smoke: hold a multi-turn conversation against the dev server.

The dev server must be running with a real OPENAI_API_KEY:

    uv run uvicorn app.main:app --port 8000
    uv run python scripts/chat_repl.py

Type messages; empty line, 'exit', or Ctrl-D quits.
"""

import json
import uuid

import httpx

BASE_URL = "http://localhost:8000"


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        created = client.post("/api/v1/conversations", json={"entry_page": "/repl"})
        created.raise_for_status()
        session = created.json()
        cid = session["conversation_id"]
        token = session["session_token"]
        print(f"[conversation {cid}]")
        print(f"Assistant: {session['welcome']['text']}")

        while True:
            try:
                content = input("\nYou: ").strip()
            except EOFError:
                break
            if not content or content in ("exit", "quit"):
                break

            cmid = f"cmid_{uuid.uuid4().hex}"
            print("Assistant: ", end="", flush=True)
            with client.stream(
                "POST",
                f"/api/v1/conversations/{cid}/messages",
                json={"content": content, "client_message_id": cmid},
                headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            ) as response:
                if response.status_code != 200:
                    print(f"[error {response.status_code}] {response.read().decode()}")
                    continue
                event = None
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[len("data:") :].strip())
                        if event == "response.delta":
                            print(data["text"], end="", flush=True)
                        elif event == "response.failed":
                            print(f"\n[failed: {data['error']['code']}]")
                        elif event == "limit.reached":
                            print(f"\n[{data['message']}]")
            print()


if __name__ == "__main__":
    main()
