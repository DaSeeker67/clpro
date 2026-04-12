import { NextRequest, NextResponse } from "next/server";
import Razorpay from "razorpay";
import { PLAN_PRICES } from "@/lib/license";

const razorpay = new Razorpay({
  key_id: process.env.RAZORPAY_KEY_ID!,
  key_secret: process.env.RAZORPAY_KEY_SECRET!,
});

export async function POST(req: NextRequest) {
  try {
    const { plan, email } = await req.json();

    if (!plan || !["pro", "promax"].includes(plan)) {
      return NextResponse.json({ error: "Invalid plan" }, { status: 400 });
    }
    if (!email || !email.includes("@")) {
      return NextResponse.json(
        { error: "Valid email required" },
        { status: 400 }
      );
    }

    const amount = PLAN_PRICES[plan];

    const order = await razorpay.orders.create({
      amount,
      currency: "INR",
      notes: { plan, email: email.toLowerCase() },
    });

    return NextResponse.json({ order_id: order.id, amount });
  } catch {
    return NextResponse.json(
      { error: "Failed to create order" },
      { status: 500 }
    );
  }
}
