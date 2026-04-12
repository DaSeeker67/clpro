"use client";

import { useSearchParams } from "next/navigation";
import { useState, Suspense } from "react";

function SuccessContent() {
  const params = useSearchParams();
  const key = params.get("key") || "";
  const [copied, setCopied] = useState(false);

  function copyKey() {
    navigator.clipboard.writeText(key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!key) {
    return (
      <div className="key-display" style={{ marginTop: "120px" }}>
        <h2>No License Key</h2>
        <div className="key-instructions">
          Return to the <a href="/" style={{ color: "var(--accent)" }}>home page</a> to get a key.
        </div>
      </div>
    );
  }

  return (
    <div className="key-display" style={{ marginTop: "120px" }}>
      <h2>Payment Successful!</h2>
      <div className="key-value">{key}</div>
      <button className="key-copy-btn" onClick={copyKey}>
        {copied ? "Copied!" : "Copy to Clipboard"}
      </button>
      <div className="key-instructions">
        Open <strong>Cluely Pro</strong> → Settings (gear icon) → paste your
        license key → Save.
        <br />
        Your key is tied to one device on first use.
      </div>
    </div>
  );
}

export default function SuccessPage() {
  return (
    <main>
      <Suspense fallback={<div style={{ textAlign: "center", padding: "120px 20px", color: "var(--text2)" }}>Loading…</div>}>
        <SuccessContent />
      </Suspense>
      <footer className="footer">
        Cluely Pro &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}
