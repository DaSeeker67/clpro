import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { signToken } from "@/lib/jwt";
import { PLAN_LIMITS } from "@/lib/license";

export async function POST(req: NextRequest) {
  try {
    const { license_key, hwid } = await req.json();

    if (!license_key) {
      return NextResponse.json(
        { valid: false, error: "Missing license key" },
        { status: 400 }
      );
    }

    const { data: license, error } = await supabase
      .from("licenses")
      .select("*")
      .eq("license_key", license_key)
      .eq("active", true)
      .single();

    if (error || !license) {
      return NextResponse.json(
        { valid: false, error: "Invalid license key" },
        { status: 401 }
      );
    }

    // Check expiry
    if (license.expires_at && new Date(license.expires_at) < new Date()) {
      return NextResponse.json(
        { valid: false, error: "License expired. Please renew your plan." },
        { status: 401 }
      );
    }

    // HWID binding — first use binds the key to the device
    if (license.hwid && license.hwid !== hwid) {
      return NextResponse.json(
        { valid: false, error: "This key is already activated on another device" },
        { status: 403 }
      );
    }
    if (!license.hwid && hwid) {
      await supabase
        .from("licenses")
        .update({ hwid })
        .eq("id", license.id);
    }

    // Calculate remaining usage
    const limits = PLAN_LIMITS[license.plan] || PLAN_LIMITS.free;
    const remaining_answers =
      limits.answers === Infinity
        ? -1
        : Math.max(0, limits.answers - license.usage_answers);
    const remaining_screenshots =
      limits.screenshots === Infinity
        ? -1
        : Math.max(0, limits.screenshots - license.usage_screenshots);

    // Sign a token (valid 1 hour, app must re-validate)
    const token = await signToken({
      key: license_key,
      plan: license.plan,
      hwid,
      ra: remaining_answers,
      rs: remaining_screenshots,
    });

    return NextResponse.json({
      valid: true,
      plan: license.plan,
      remaining_answers,
      remaining_screenshots,
      expires_at: license.expires_at,
      token,
    });
  } catch {
    return NextResponse.json(
      { valid: false, error: "Server error" },
      { status: 500 }
    );
  }
}
