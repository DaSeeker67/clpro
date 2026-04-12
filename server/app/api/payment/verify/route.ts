import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { supabase } from "@/lib/supabase";
import { generateLicenseKey, PLAN_LIMITS } from "@/lib/license";

export async function POST(req: NextRequest) {
  try {
    const {
      razorpay_order_id,
      razorpay_payment_id,
      razorpay_signature,
      email,
      plan,
    } = await req.json();

    if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature) {
      return NextResponse.json(
        { error: "Missing payment details" },
        { status: 400 }
      );
    }

    // Verify Razorpay signature
    const body = razorpay_order_id + "|" + razorpay_payment_id;
    const expected = crypto
      .createHmac("sha256", process.env.RAZORPAY_KEY_SECRET!)
      .update(body)
      .digest("hex");

    if (expected !== razorpay_signature) {
      return NextResponse.json(
        { error: "Invalid payment signature" },
        { status: 400 }
      );
    }

    // Create license
    const license_key = generateLicenseKey();
    const limits = PLAN_LIMITS[plan] || PLAN_LIMITS.pro;
    const expires_at = limits.duration_days
      ? new Date(
          Date.now() + limits.duration_days * 24 * 60 * 60 * 1000
        ).toISOString()
      : null;

    const { error } = await supabase.from("licenses").insert({
      license_key,
      email: email.toLowerCase().trim(),
      plan,
      expires_at,
      razorpay_payment_id,
      razorpay_order_id,
    });

    if (error) {
      return NextResponse.json(
        { error: "Failed to create license" },
        { status: 500 }
      );
    }

    return NextResponse.json({ license_key, plan, expires_at });
  } catch {
    return NextResponse.json(
      { error: "Server error" },
      { status: 500 }
    );
  }
}
