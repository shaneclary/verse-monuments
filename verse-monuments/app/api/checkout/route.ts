import { NextRequest, NextResponse } from "next/server";
import { processHelcimPayment } from "@/lib/helcim";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const {
      amount,
      currency,
      customerCode,
      invoiceNumber,
      comments,
      cardData,
      billing,
      items,
      productLine,
    } = body;

    // Validate required fields
    if (!amount || !cardData || !billing) {
      return NextResponse.json(
        { success: false, error: "Missing required fields" },
        { status: 400 }
      );
    }

    // Process payment via Helcim
    const paymentResult = await processHelcimPayment({
      amount,
      currency: currency || "USD",
      customerCode,
      invoiceNumber,
      comments,
      cardData,
    });

    if (!paymentResult.success) {
      return NextResponse.json(
        {
          success: false,
          error: paymentResult.error || "Payment processing failed",
        },
        { status: 400 }
      );
    }

    // TODO: Store order in database
    // TODO: Send confirmation email
    // TODO: Trigger fulfillment workflow

    // Return success response
    return NextResponse.json({
      success: true,
      transactionId: paymentResult.transactionId,
      message: "Payment processed successfully",
      order: {
        transactionId: paymentResult.transactionId,
        amount,
        currency,
        billing,
        items,
        productLine,
        timestamp: new Date().toISOString(),
      },
    });
  } catch (error) {
    console.error("Checkout API error:", error);
    return NextResponse.json(
      {
        success: false,
        error: "An unexpected error occurred",
      },
      { status: 500 }
    );
  }
}
