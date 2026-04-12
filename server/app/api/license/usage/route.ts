import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { PLAN_LIMITS } from "@/lib/license";

export async function POST(req: NextRequest) {
  try {
    const { license_key, type } = await req.json();

    if (!license_key || !["answer", "screenshot"].includes(type)) {
      return NextResponse.json({ error: "Invalid request" }, { status: 400 });
    }

    const { data: license, error } = await supabase
      .from("licenses")
      .select("*")
      .eq("license_key", license_key)
      .eq("active", true)
      .single();

    if (error || !license) {
      return NextResponse.json({ error: "Invalid license" }, { status: 401 });
    }

    // Check expiry
    if (license.expires_at && new Date(license.expires_at) < new Date()) {
      return NextResponse.json(
        { error: "License expired" },
        { status: 401 }
      );
    }

    const limits = PLAN_LIMITS[license.plan] || PLAN_LIMITS.free;
    const field =
      type === "answer" ? "usage_answers" : "usage_screenshots";
    const limitKey = type === "answer" ? "answers" : "screenshots";

    // Check within limits (paid plans have Infinity)
    if (
      limits[limitKey] !== Infinity &&
      license[field] >= limits[limitKey]
    ) {
      return NextResponse.json(
        {
          error: "Usage limit reached. Upgrade your plan at cluelypro.com",
          limit_reached: true,
          remaining: 0,
        },
        { status: 403 }
      );
    }

    // Increment usage
    const { data } = await supabase
      .from("licenses")
      .update({ [field]: license[field] + 1 })
      .eq("id", license.id)
      .select(field)
      .single();

    const newUsage = data ? data[field] : license[field] + 1;
    const remaining =
      limits[limitKey] === Infinity
        ? -1
        : Math.max(0, limits[limitKey] - newUsage);

    return NextResponse.json({ remaining });
  } catch {
    return NextResponse.json({ error: "Server error" }, { status: 500 });
  }
}
