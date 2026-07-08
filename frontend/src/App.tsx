import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

type Status = "idle" | "streaming" | "completed" | "error";

interface DeltaPayload {
  index: number;
  text: string;
}

export default function App() {
  const [status, setStatus] = useState<Status>("idle");
  const [tokens, setTokens] = useState<string[]>([]);

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/api/v1/dev/stream-test`);

    source.addEventListener("response.started", () => setStatus("streaming"));

    source.addEventListener("response.delta", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as DeltaPayload;
      setTokens((prev) => [...prev, payload.text]);
    });

    source.addEventListener("response.completed", () => {
      setStatus("completed");
      source.close();
    });

    source.onerror = () => {
      // A clean close after completion also fires onerror; don't clobber success.
      setStatus((current) => (current === "completed" ? current : "error"));
      source.close();
    };

    return () => source.close();
  }, []);

  return (
    <main className="skeleton">
      <h1>Cadre AI — walking skeleton</h1>
      <p className="status" data-testid="status">
        SSE status: <strong>{status}</strong>
      </p>
      <div className="stream" aria-live="polite" data-testid="stream">
        {tokens.map((token, index) => (
          <span key={index} className="token">
            {token}
          </span>
        ))}
      </div>
      {status === "error" && (
        <p className="error" role="alert">
          Stream error — is the backend running at {API_BASE}?
        </p>
      )}
    </main>
  );
}
