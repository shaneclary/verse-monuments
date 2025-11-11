/**
 * Helcim Payment Gateway Integration
 * API Docs: https://docs.helcim.com/
 */

export interface HelcimPaymentRequest {
  amount: number; // in cents
  currency: string;
  customerCode?: string;
  invoiceNumber?: string;
  comments?: string;
  cardData: {
    cardNumber: string;
    cardExpiry: string; // MMYY
    cardCVV: string;
    cardHolderName: string;
    cardHolderAddress?: string;
    cardHolderPostalCode?: string;
  };
}

export interface HelcimPaymentResponse {
  success: boolean;
  transactionId?: string;
  message?: string;
  error?: string;
  response?: any;
}

export async function processHelcimPayment(
  request: HelcimPaymentRequest
): Promise<HelcimPaymentResponse> {
  const apiKey = process.env.HELCIM_API_KEY;
  const terminalId = process.env.HELCIM_TERMINAL_ID;

  if (!apiKey || !terminalId) {
    return {
      success: false,
      error: "Helcim API credentials not configured",
    };
  }

  try {
    const response = await fetch("https://api.helcim.com/v2/payment", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "api-token": apiKey,
      },
      body: JSON.stringify({
        terminalId: parseInt(terminalId),
        amount: request.amount / 100, // Convert cents to dollars
        currency: request.currency,
        customerCode: request.customerCode,
        invoiceNumber: request.invoiceNumber,
        comments: request.comments,
        cardNumber: request.cardData.cardNumber,
        cardExpiry: request.cardData.cardExpiry,
        cardCVV: request.cardData.cardCVV,
        cardHolderName: request.cardData.cardHolderName,
        cardHolderAddress: request.cardData.cardHolderAddress,
        cardHolderPostalCode: request.cardData.cardHolderPostalCode,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      return {
        success: false,
        error: data.message || "Payment processing failed",
        response: data,
      };
    }

    return {
      success: true,
      transactionId: data.transactionId,
      message: "Payment successful",
      response: data,
    };
  } catch (error) {
    console.error("Helcim payment error:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error occurred",
    };
  }
}

// Helper to calculate total from cart items
export function calculateCartTotal(items: { quantity: number; price: number }[]): number {
  return items.reduce((total, item) => total + (item.quantity * item.price), 0);
}
