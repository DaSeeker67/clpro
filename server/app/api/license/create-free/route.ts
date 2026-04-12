import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { generateLicenseKey } from "@/lib/license";

export async function POST(req: NextRequest) {
  try {
    const { email } = await req.json();

    if (!email || !email.includes("@")) {
      return NextResponse.json(
        { error: "Valid email required" },
        { status: 400 }
      );
    }

    const emailLower = email.toLowerCase().trim();

    // Check if user already has a free key
    const { data: existing } = await supabase
      .from("licenses")
      .select("license_key")
      .eq("email", emailLower)
      .eq("plan", "free")
      .single();

    if (existing) {
      return NextResponse.json({
        license_key: existing.license_key,
        existing: true,
      });
    }

    const license_key = generateLicenseKey();

    const { error } = await supabase.from("licenses").insert({
      license_key,
      email: emailLower,
      plan: "free",
    });

    if (error) {
      return NextResponse.json(
        { error: "Failed to create license" },
        { status: 500 }
      );
    }

    return NextResponse.json({ license_key });
  } catch {
    return NextResponse.json(
      { error: "Server error" },
      { status: 500 }
    );
  }
}
