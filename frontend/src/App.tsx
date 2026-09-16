import { useEffect, useState } from "react";
import { getHealth } from "./services/api";

function App() {
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">(
    "checking",
  );

  useEffect(() => {
    getHealth()
      .then(() => setBackendStatus("online"))
      .catch(() => setBackendStatus("offline"));
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="rounded-lg border border-border bg-surface p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-text-primary">Resolve</h1>
        <p className="mt-1 text-text-secondary">Intelligent Issue Resolution Platform</p>
        <p className="mt-4 text-sm">
          Backend status:{" "}
          <span
            className={
              backendStatus === "online"
                ? "text-success"
                : backendStatus === "offline"
                  ? "text-danger"
                  : "text-text-secondary"
            }
          >
            {backendStatus}
          </span>
        </p>
      </div>
    </div>
  );
}

export default App;
