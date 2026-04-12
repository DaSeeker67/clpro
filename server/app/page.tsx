"use client";

import { useState } from "react";
import Script from "next/script";

declare global {
  interface Window {
    Razorpay: any;
  }
}

export default function Home() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState("");
  const [licenseKey, setLicenseKey] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleFree() {
    if (!email || !email.includes("@")) {
      setError("Please enter a valid email address");
      return;
    }
    setLoading("free");
    setError("");
    try {
      const res = await fetch("/api/license/create-free", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (data.license_key) {
        setLicenseKey(data.license_key);
      } else {
        setError(data.error || "Failed to create license key");
      }
    } catch {
      setError("Network error. Please try again.");
    }
    setLoading("");
  }

  async function handlePay(plan: "pro" | "promax") {
    if (!email || !email.includes("@")) {
      setError("Enter your email first, then select a plan");
      return;
    }
    setLoading(plan);
    setError("");
    try {
      const res = await fetch("/api/payment/create-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan, email }),
      });
      const { order_id, amount } = await res.json();

      const options = {
        key: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
        amount,
        currency: "INR",
        name: "Cluely Pro",
        description: plan === "pro" ? "Pro — Monthly" : "Pro Max — Annual",
        order_id,
        prefill: { email },
        theme: { color: "#6ee7b7" },
        handler: async function (response: any) {
          const verifyRes = await fetch("/api/payment/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              email,
              plan,
            }),
          });
          const data = await verifyRes.json();
          if (data.license_key) {
            setLicenseKey(data.license_key);
          } else {
            setError(data.error || "Payment verification failed");
          }
        },
        modal: {
          ondismiss: () => setLoading(""),
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch {
      setError("Failed to initiate payment");
      setLoading("");
    }
  }

  function copyKey() {
    navigator.clipboard.writeText(licenseKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // ─── License key display ───
  if (licenseKey) {
    return (
      <main>
        <Script src="https://checkout.razorpay.com/v1/checkout.js" />
        <div className="key-display" style={{ marginTop: "120px" }}>
          <h2>Your License Key</h2>
          <div className="key-value">{licenseKey}</div>
          <button className="key-copy-btn" onClick={copyKey}>
            {copied ? "Copied!" : "Copy to Clipboard"}
          </button>
          <div className="key-instructions">
            Open <strong>Cluely Pro</strong> → Settings (gear icon) → paste
            your license key → Save.
            <br />
            Your key is tied to one device on first use.
          </div>
          <a href="https://github.com/DaSeeker67/clpro/releases/latest/download/CluePro-Windows.zip" className="download-btn" style={{ marginTop: "20px" }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download for Windows
          </a>
        </div>
        <footer className="footer">
          Cluely Pro &copy; {new Date().getFullYear()}
        </footer>
      </main>
    );
  }

  // ─── Main page ─────────────
  return (
    <main>
      <Script src="https://checkout.razorpay.com/v1/checkout.js" />

      {/* Hero */}
      <section className="hero">
        <div className="hero-badge">SCREEN-CAPTURE PROOF</div>
        <h1>
          Your Invisible
          <br />
          AI <span>Copilot</span>
        </h1>
        <p>
          Real-time AI answers overlaid on your screen. Invisible to screen
          share, recordings, and screenshots. Built for meetings, interviews,
          and assessments.
        </p>
        <a href="https://github.com/DaSeeker67/clpro/releases/latest/download/CluePro-Windows.zip" className="download-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Download for Windows
        </a>
        <span className="download-hint">Windows 10/11 &bull; 64-bit &bull; Free to try</span>
      </section>

      {/* Features */}
      <div className="features">
        <div className="feature">
          <div className="feature-icon">👻</div>
          <h3>Truly Invisible</h3>
          <p>
            Protected from all screen capture APIs. Nobody sees your overlay.
          </p>
        </div>
        <div className="feature">
          <div className="feature-icon">🎙️</div>
          <h3>Live Transcription</h3>
          <p>Captures system audio and microphone with real-time STT.</p>
        </div>
        <div className="feature">
          <div className="feature-icon">🧠</div>
          <h3>AI Answers</h3>
          <p>
            Powered by LLaMA 3.3 70B. Instant, context-aware answers streamed
            live.
          </p>
        </div>
        <div className="feature">
          <div className="feature-icon">📸</div>
          <h3>Vision Analysis</h3>
          <p>Screenshot any screen content and get AI analysis instantly.</p>
        </div>
      </div>

      {/* Email */}
      <div className="email-section">
        <input
          type="email"
          className="email-input"
          placeholder="you@email.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="email-label">
          Enter your email to get started. Required for all plans.
        </div>
      </div>

      {error && (
        <div className="alert error">{error}</div>
      )}

      {/* Pricing */}
      <section className="pricing-section">
        <h2 className="pricing-title">Simple Pricing</h2>
        <p className="pricing-sub">
          Bring your own Groq API key. We just enable the app.
        </p>

        <div className="pricing-grid">
          {/* Free */}
          <div className="plan-card">
            <div className="plan-name">Free</div>
            <div className="plan-price">
              ₹0 <span></span>
            </div>
            <div className="plan-period">Try it out</div>
            <ul className="plan-features">
              <li>10 AI answers</li>
              <li>5 screenshots</li>
              <li>BYOK (Groq API)</li>
              <li>Single device</li>
            </ul>
            <button
              className="plan-btn secondary"
              onClick={handleFree}
              disabled={loading === "free"}
            >
              {loading === "free" ? "Creating…" : "Get Free Key"}
            </button>
          </div>

          {/* Pro */}
          <div className="plan-card featured">
            <div className="plan-name">Pro</div>
            <div className="plan-price">
              ₹499 <span>/mo</span>
            </div>
            <div className="plan-period">Billed monthly</div>
            <ul className="plan-features">
              <li>Unlimited AI answers</li>
              <li>Unlimited screenshots</li>
              <li>BYOK (Groq API)</li>
              <li>Single device</li>
              <li>Priority support</li>
            </ul>
            <button
              className="plan-btn primary"
              onClick={() => handlePay("pro")}
              disabled={loading === "pro"}
            >
              {loading === "pro" ? "Processing…" : "Buy Pro"}
            </button>
          </div>

          {/* Pro Max */}
          <div className="plan-card">
            <div className="plan-name">Pro Max</div>
            <div className="plan-price">
              ₹2,999 <span>/yr</span>
            </div>
            <div className="plan-period">Save 50% — billed annually</div>
            <ul className="plan-features">
              <li>Unlimited AI answers</li>
              <li>Unlimited screenshots</li>
              <li>BYOK (Groq API)</li>
              <li>Single device</li>
              <li>Priority support</li>
            </ul>
            <button
              className="plan-btn secondary"
              onClick={() => handlePay("promax")}
              disabled={loading === "promax"}
            >
              {loading === "promax" ? "Processing…" : "Buy Pro Max"}
            </button>
          </div>
        </div>
      </section>

      <footer className="footer">
        Cluely Pro &copy; {new Date().getFullYear()}
      </footer>
    </main>
  );
}
