"use client";

import { useState } from "react";
import Link from "next/link";

function generateRandomCode(length = 8) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // Avoid ambiguous characters
  let code = "";
  for (let i = 0; i < length; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length));
  });
  return code;
}

export default function QuickReferralPage() {
  const [step, setStep] = useState<"form" | "generated">("form");
  const [paymentInfo, setPaymentInfo] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"paypal" | "venmo">("paypal");
  const [referralCode, setReferralCode] = useState("");
  const [discountCode, setDiscountCode] = useState("");
  const [referralLink, setReferralLink] = useState("");

  const handleGenerate = (e: React.FormEvent) => {
    e.preventDefault();

    if (!paymentInfo.trim()) {
      alert("Please enter your PayPal or Venmo info");
      return;
    }

    // Generate random codes
    const refCode = generateRandomCode(8);
    const discCode = generateRandomCode(6) + "10"; // 6 chars + "10" for 10% off
    const link = `https://ripnyc.vercel.app/r/${refCode}`;

    setReferralCode(refCode);
    setDiscountCode(discCode);
    setReferralLink(link);

    // TODO: Send this to your backend to save the referral
    console.log({
      paymentMethod,
      paymentInfo,
      referralCode: refCode,
      discountCode: discCode,
      timestamp: new Date().toISOString(),
    });

    setStep("generated");
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    alert("Copied to clipboard!");
  };

  if (step === "generated") {
    return (
      <div className="max-w-3xl mx-auto px-6 py-20">
        <div className="mb-8">
          <Link
            href="/partners"
            className="text-ash hover:text-white transition-colors text-sm"
          >
            ← Back to Monument Circle
          </Link>
        </div>

        <h1 className="text-4xl md:text-5xl font-unifraktur mb-6 tracking-tight">
          You're all set
        </h1>
        <p className="text-lg text-ash/90 mb-12 leading-relaxed">
          Your referral link and discount code are ready. Share them, earn 15% on every sale.
        </p>

        <div className="space-y-8">
          {/* Referral Link */}
          <div className="p-6 border border-hairline bg-white/[0.02]">
            <h2 className="text-sm font-medium mb-3 text-ash">Your referral link</h2>
            <div className="flex gap-3">
              <input
                type="text"
                value={referralLink}
                readOnly
                className="flex-1 px-4 py-3 bg-ink border border-hairline text-white font-mono text-sm"
              />
              <button
                onClick={() => copyToClipboard(referralLink)}
                className="px-6 py-3 bg-white text-ink hover:bg-ash transition-colors text-sm font-medium"
              >
                Copy
              </button>
            </div>
            <p className="text-xs text-ash/70 mt-3">
              Share this link. Anyone who clicks it gets a 30-day cookie tracked to you.
            </p>
          </div>

          {/* Discount Code */}
          <div className="p-6 border border-hairline bg-white/[0.02]">
            <h2 className="text-sm font-medium mb-3 text-ash">Your discount code</h2>
            <div className="flex gap-3">
              <input
                type="text"
                value={discountCode}
                readOnly
                className="flex-1 px-4 py-3 bg-ink border border-hairline text-white font-mono text-sm"
              />
              <button
                onClick={() => copyToClipboard(discountCode)}
                className="px-6 py-3 bg-white text-ink hover:bg-ash transition-colors text-sm font-medium"
              >
                Copy
              </button>
            </div>
            <p className="text-xs text-ash/70 mt-3">
              Saves your audience <strong>10% at checkout</strong>. Also tracks the sale to you.
            </p>
          </div>

          {/* Earnings */}
          <div className="p-6 border border-hairline bg-white/[0.02]">
            <h2 className="text-sm font-medium mb-3">You earn</h2>
            <div className="space-y-2 text-sm text-ash/90">
              <p>• <strong className="text-white">15% commission</strong> on Bangladesh Vibe line (or $6/tee floor)</p>
              <p>• <strong className="text-white">20% commission</strong> on USA Maker line (or $8/tee floor)</p>
              <p>• Payouts monthly (NET-15) via {paymentMethod === "paypal" ? "PayPal" : "Venmo"}: <code className="text-white">{paymentInfo}</code></p>
              <p className="text-xs text-ash/70 pt-2">Minimum $50 payout; balances roll over.</p>
            </div>
          </div>

          {/* Compliance */}
          <div className="p-6 border border-ash/30 bg-white/[0.02]">
            <h2 className="text-sm font-medium mb-3 text-ash">Required disclosure</h2>
            <p className="text-xs text-ash/90 leading-relaxed mb-3">
              You <strong className="text-white">must</strong> disclose your affiliate relationship when sharing:
            </p>
            <div className="p-4 bg-ink border border-hairline">
              <p className="text-xs text-ash/90 font-mono">
                #ad — I earn a commission if you use my code {discountCode}
              </p>
            </div>
            <p className="text-xs text-ash/70 mt-3">
              FTC requires clear disclosure. Posts without it may void your commission.
            </p>
          </div>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-4 pt-8 border-t border-hairline">
            <Link
              href="/"
              className="flex-1 px-8 py-4 bg-white text-ink text-center font-medium hover:bg-ash transition-colors"
            >
              View monuments
            </Link>
            <button
              onClick={() => {
                setStep("form");
                setPaymentInfo("");
                setReferralCode("");
                setDiscountCode("");
                setReferralLink("");
              }}
              className="flex-1 px-8 py-4 border border-hairline text-center hover:border-white transition-colors"
            >
              Generate another
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <article className="max-w-3xl mx-auto px-6 py-20">
      <div className="mb-8">
        <Link
          href="/partners"
          className="text-ash hover:text-white transition-colors text-sm"
        >
          ← Back to Monument Circle
        </Link>
      </div>

      <h1 className="text-4xl md:text-5xl font-unifraktur mb-6 tracking-tight">
        Quick referral
      </h1>
      <p className="text-lg text-ash/90 mb-12 leading-relaxed">
        Instant setup. Just enter your payment info, get your link and code, start earning 15-20%.
      </p>

      <form onSubmit={handleGenerate} className="space-y-8">
        {/* Payment Method */}
        <div>
          <label className="block text-sm font-medium mb-3">How do you want to get paid?</label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="payment"
                value="paypal"
                checked={paymentMethod === "paypal"}
                onChange={(e) => setPaymentMethod(e.target.value as "paypal" | "venmo")}
                className="w-4 h-4"
              />
              <span className="text-ash/90">PayPal</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="payment"
                value="venmo"
                checked={paymentMethod === "venmo"}
                onChange={(e) => setPaymentMethod(e.target.value as "paypal" | "venmo")}
                className="w-4 h-4"
              />
              <span className="text-ash/90">Venmo</span>
            </label>
          </div>
        </div>

        {/* Payment Info */}
        <div>
          <label htmlFor="paymentInfo" className="block text-sm font-medium mb-2">
            {paymentMethod === "paypal" ? "PayPal email" : "Venmo username"}
          </label>
          <input
            type={paymentMethod === "paypal" ? "email" : "text"}
            id="paymentInfo"
            value={paymentInfo}
            onChange={(e) => setPaymentInfo(e.target.value)}
            required
            className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
            placeholder={paymentMethod === "paypal" ? "you@example.com" : "@username"}
          />
        </div>

        {/* What you get */}
        <div className="p-6 border border-hairline bg-white/[0.02]">
          <h2 className="text-sm font-medium mb-4">What you'll get</h2>
          <div className="space-y-3 text-sm text-ash/90">
            <p>• <strong className="text-white">Unique referral link</strong> (30-day cookie tracking)</p>
            <p>• <strong className="text-white">10% discount code</strong> for your audience</p>
            <p>• <strong className="text-white">15-20% commission</strong> on every sale (or $6-8/tee floor)</p>
            <p>• Monthly payouts via {paymentMethod === "paypal" ? "PayPal" : "Venmo"}</p>
          </div>
        </div>

        {/* Disclosures */}
        <div className="p-6 border border-hairline/50 bg-white/[0.02]">
          <p className="text-xs text-ash/90 leading-relaxed mb-4">
            By generating a referral link, you agree to:
          </p>
          <ul className="text-xs text-ash/70 space-y-2 leading-relaxed">
            <li>• FTC-compliant disclosure (#ad or paid partnership) on all posts</li>
            <li>• No bidding on "Verse-Monuments" or brand terms</li>
            <li>• Reverent tone—no exploitation or tragedy-bait</li>
            <li>• Commission reversals on refunded orders</li>
          </ul>
        </div>

        {/* Submit */}
        <button
          type="submit"
          className="w-full px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300"
        >
          Generate my referral link
        </button>
      </form>
    </article>
  );
}
