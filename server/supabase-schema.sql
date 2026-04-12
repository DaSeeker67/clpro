-- Cluely Pro — Supabase Schema
-- Run this in the Supabase SQL editor to create the required tables.

CREATE TABLE IF NOT EXISTS licenses (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_key   VARCHAR(64)  UNIQUE NOT NULL,
  email         VARCHAR(255) NOT NULL,
  plan          VARCHAR(20)  NOT NULL DEFAULT 'free',   -- free | pro | promax
  hwid          VARCHAR(64),                             -- SHA-256 prefix, bound on first use
  usage_answers     INTEGER NOT NULL DEFAULT 0,
  usage_screenshots INTEGER NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at    TIMESTAMPTZ,                             -- NULL = no expiry (free tier)
  razorpay_payment_id VARCHAR(255),
  razorpay_order_id   VARCHAR(255),
  active        BOOLEAN NOT NULL DEFAULT TRUE
);

-- Fast lookups
CREATE INDEX IF NOT EXISTS idx_licenses_key   ON licenses (license_key);
CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses (email);

-- Row-level security (optional but recommended)
ALTER TABLE licenses ENABLE ROW LEVEL SECURITY;

-- Allow the service-role key full access (API routes use service key)
CREATE POLICY "Service role full access"
  ON licenses
  FOR ALL
  USING (true)
  WITH CHECK (true);
