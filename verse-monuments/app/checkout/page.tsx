"use client";

import { useState } from "react";
import { useCart } from "@/contexts/CartContext";
import { useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import monuments from "@/data/monuments.json";
import lines from "@/data/lines.json";
import { msrp, formatPrice } from "@/lib/pricing";

export default function CheckoutPage() {
  const { items, clearCart } = useCart();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [productLine, setProductLine] = useState<"standard" | "usa">("standard");

  const [formData, setFormData] = useState({
    // Billing Info
    fullName: "",
    email: "",
    phone: "",
    address: "",
    city: "",
    state: "",
    zip: "",
    country: "US",

    // Card Info
    cardNumber: "",
    cardExpiry: "", // MMYY
    cardCVV: "",
    cardHolderName: "",
  });

  // Calculate pricing
  const standardLine = lines.find((l) => l.id === "standard");
  const usaLine = lines.find((l) => l.id === "usa");
  const wholesalePrice = productLine === "standard"
    ? standardLine?.wholesaleExample || 18
    : usaLine?.wholesaleExample || 28;

  const lineItems = items.map((item) => {
    const monument = monuments.find((m) => m.id === item.id);
    if (!monument) return null;

    const price = msrp(wholesalePrice, monument.markupStd);
    return {
      ...item,
      unitPrice: price,
      totalPrice: price * item.quantity,
      monumentData: monument,
    };
  }).filter(Boolean);

  const subtotal = lineItems.reduce((sum, item) => sum + (item?.totalPrice || 0), 0);
  const tax = subtotal * 0.0875; // Example: 8.75% tax
  const shipping = 0; // Free shipping
  const total = subtotal + tax + shipping;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    let value = e.target.value;

    // Format card number with spaces
    if (e.target.name === "cardNumber") {
      value = value.replace(/\s/g, "").replace(/(\d{4})/g, "$1 ").trim();
    }

    // Format expiry as MM/YY
    if (e.target.name === "cardExpiry") {
      value = value.replace(/\D/g, "").slice(0, 4);
      if (value.length >= 2) {
        value = value.slice(0, 2) + "/" + value.slice(2);
      }
    }

    // Limit CVV to 3-4 digits
    if (e.target.name === "cardCVV") {
      value = value.replace(/\D/g, "").slice(0, 4);
    }

    setFormData({
      ...formData,
      [e.target.name]: value,
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      // Format card expiry for Helcim (MMYY)
      const expiryClean = formData.cardExpiry.replace(/\D/g, "");

      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount: Math.round(total * 100), // Convert to cents
          currency: "USD",
          customerCode: formData.email,
          invoiceNumber: `ORDER-${Date.now()}`,
          comments: `${items.length} item(s) - ${productLine} line`,
          cardData: {
            cardNumber: formData.cardNumber.replace(/\s/g, ""),
            cardExpiry: expiryClean,
            cardCVV: formData.cardCVV,
            cardHolderName: formData.cardHolderName || formData.fullName,
            cardHolderAddress: formData.address,
            cardHolderPostalCode: formData.zip,
          },
          billing: {
            fullName: formData.fullName,
            email: formData.email,
            phone: formData.phone,
            address: formData.address,
            city: formData.city,
            state: formData.state,
            zip: formData.zip,
            country: formData.country,
          },
          items: lineItems,
          productLine,
        }),
      });

      const result = await response.json();

      if (result.success) {
        clearCart();
        router.push(`/checkout/success?orderId=${result.transactionId}`);
      } else {
        setError(result.error || "Payment failed. Please check your card details and try again.");
      }
    } catch (err) {
      setError("An error occurred. Please try again.");
      console.error("Checkout error:", err);
    } finally {
      setLoading(false);
    }
  };

  if (items.length === 0) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-32 text-center">
        <h1 className="text-4xl font-unifraktur mb-8 tracking-tight">Your collection is empty</h1>
        <p className="text-lg text-ash/90 mb-8">Add some monuments to proceed with checkout.</p>
        <Link
          href="/#monuments"
          className="inline-block px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300"
        >
          Browse monuments
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-20">
      <h1 className="text-4xl md:text-5xl font-unifraktur mb-12 tracking-tight">Checkout</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* Form Column */}
        <div>
          <form onSubmit={handleSubmit} className="space-y-8">
            {/* Production Line Selection */}
            <div className="p-6 border border-hairline bg-white/[0.02] rounded-sm">
              <h2 className="text-xl font-medium mb-4 tracking-tight">Production Line</h2>
              <div className="space-y-3">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="productLine"
                    value="standard"
                    checked={productLine === "standard"}
                    onChange={(e) => setProductLine(e.target.value as "standard" | "usa")}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="font-medium">Standard Drop</div>
                    <div className="text-sm text-ash/90">On-demand global supply. Fastest launch.</div>
                  </div>
                </label>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="productLine"
                    value="usa"
                    checked={productLine === "usa"}
                    onChange={(e) => setProductLine(e.target.value as "standard" | "usa")}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="font-medium">USA Maker Line</div>
                    <div className="text-sm text-ash/90">USA-made & printed. Higher cost, higher ethos.</div>
                  </div>
                </label>
              </div>
            </div>

            {/* Billing Information */}
            <div>
              <h2 className="text-xl font-medium mb-6 tracking-tight">Billing Information</h2>
              <div className="space-y-4">
                <div>
                  <label htmlFor="fullName" className="block text-sm font-medium mb-2">
                    Full Name
                  </label>
                  <input
                    type="text"
                    id="fullName"
                    name="fullName"
                    value={formData.fullName}
                    onChange={handleChange}
                    required
                    className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="email" className="block text-sm font-medium mb-2">
                      Email
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      value={formData.email}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                    />
                  </div>
                  <div>
                    <label htmlFor="phone" className="block text-sm font-medium mb-2">
                      Phone
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      value={formData.phone}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="address" className="block text-sm font-medium mb-2">
                    Address
                  </label>
                  <input
                    type="text"
                    id="address"
                    name="address"
                    value={formData.address}
                    onChange={handleChange}
                    required
                    className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                  />
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div>
                    <label htmlFor="city" className="block text-sm font-medium mb-2">
                      City
                    </label>
                    <input
                      type="text"
                      id="city"
                      name="city"
                      value={formData.city}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                    />
                  </div>
                  <div>
                    <label htmlFor="state" className="block text-sm font-medium mb-2">
                      State
                    </label>
                    <input
                      type="text"
                      id="state"
                      name="state"
                      value={formData.state}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                    />
                  </div>
                  <div>
                    <label htmlFor="zip" className="block text-sm font-medium mb-2">
                      ZIP
                    </label>
                    <input
                      type="text"
                      id="zip"
                      name="zip"
                      value={formData.zip}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Payment Information */}
            <div>
              <h2 className="text-xl font-medium mb-6 tracking-tight">Payment Information</h2>
              <div className="space-y-4">
                <div>
                  <label htmlFor="cardNumber" className="block text-sm font-medium mb-2">
                    Card Number
                  </label>
                  <input
                    type="text"
                    id="cardNumber"
                    name="cardNumber"
                    value={formData.cardNumber}
                    onChange={handleChange}
                    required
                    placeholder="1234 5678 9012 3456"
                    maxLength={19}
                    className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors font-mono"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="cardExpiry" className="block text-sm font-medium mb-2">
                      Expiry (MM/YY)
                    </label>
                    <input
                      type="text"
                      id="cardExpiry"
                      name="cardExpiry"
                      value={formData.cardExpiry}
                      onChange={handleChange}
                      required
                      placeholder="MM/YY"
                      maxLength={5}
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors font-mono"
                    />
                  </div>
                  <div>
                    <label htmlFor="cardCVV" className="block text-sm font-medium mb-2">
                      CVV
                    </label>
                    <input
                      type="text"
                      id="cardCVV"
                      name="cardCVV"
                      value={formData.cardCVV}
                      onChange={handleChange}
                      required
                      placeholder="123"
                      maxLength={4}
                      className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="cardHolderName" className="block text-sm font-medium mb-2">
                    Cardholder Name <span className="text-ash/50 font-normal">(optional)</span>
                  </label>
                  <input
                    type="text"
                    id="cardHolderName"
                    name="cardHolderName"
                    value={formData.cardHolderName}
                    onChange={handleChange}
                    placeholder="Leave blank to use billing name"
                    className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
                  />
                </div>
              </div>
            </div>

            {/* Error Message */}
            {error && (
              <div className="p-4 border border-red-500/50 bg-red-500/10 text-red-300 rounded-sm">
                {error}
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Processing..." : `Complete Purchase — ${formatPrice(total)}`}
            </button>

            <p className="text-xs text-ash/70 text-center leading-relaxed">
              By completing this purchase, you agree to our terms of service. All sales are final.
              Payment processed securely via Helcim.
            </p>
          </form>
        </div>

        {/* Order Summary Column */}
        <div>
          <div className="p-8 border border-hairline bg-white/[0.02] rounded-sm sticky top-6">
            <h2 className="text-xl font-medium mb-6 tracking-tight">Order Summary</h2>

            <div className="space-y-6 mb-8">
              {lineItems.map((item) => (
                <div key={item?.id} className="flex gap-4">
                  <div className="relative w-20 h-20 bg-ink rounded-sm overflow-hidden flex-shrink-0">
                    <Image
                      src={item?.image || ""}
                      alt={item?.title || ""}
                      fill
                      className="object-contain"
                    />
                  </div>
                  <div className="flex-1">
                    <div className="font-medium mb-1">{item?.title}</div>
                    <div className="text-sm text-ash/90">Qty: {item?.quantity}</div>
                    <div className="text-sm text-ash/90">
                      {formatPrice(item?.unitPrice || 0)} × {item?.quantity} = {formatPrice(item?.totalPrice || 0)}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="space-y-3 text-sm border-t border-hairline pt-6">
              <div className="flex justify-between">
                <span className="text-ash/90">Subtotal</span>
                <span>{formatPrice(subtotal)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ash/90">Shipping</span>
                <span>{shipping === 0 ? "Free" : formatPrice(shipping)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ash/90">Tax (estimated)</span>
                <span>{formatPrice(tax)}</span>
              </div>
              <div className="flex justify-between text-lg font-medium border-t border-hairline pt-3">
                <span>Total</span>
                <span>{formatPrice(total)}</span>
              </div>
            </div>

            <div className="mt-6 pt-6 border-t border-hairline text-xs text-ash/70 leading-relaxed">
              <p className="mb-2">
                <strong className="text-white">Production line:</strong> {productLine === "standard" ? "Standard Drop" : "USA Maker Line"}
              </p>
              <p>
                Each piece is produced on-demand. Allow 7-10 business days for creation and delivery.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
