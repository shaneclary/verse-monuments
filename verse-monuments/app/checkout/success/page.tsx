"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense } from "react";

function SuccessContent() {
  const searchParams = useSearchParams();
  const orderId = searchParams.get("orderId");

  return (
    <div className="max-w-2xl mx-auto px-6 py-32 text-center">
      <div className="mb-8">
        <svg
          className="w-20 h-20 mx-auto text-green-500"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M5 13l4 4L19 7"
          />
        </svg>
      </div>

      <h1 className="text-4xl md:text-5xl font-unifraktur mb-8 tracking-tight">
        Monument Acquired
      </h1>

      <p className="text-lg text-ash/90 mb-6 leading-relaxed">
        Your order has been confirmed and payment processed successfully.
      </p>

      {orderId && (
        <div className="p-6 border border-hairline bg-white/[0.02] mb-8 rounded-sm">
          <p className="text-sm text-ash/70 mb-2">Transaction ID</p>
          <p className="text-white font-mono text-sm">{orderId}</p>
        </div>
      )}

      <div className="mb-12 p-6 border border-hairline/50 bg-white/[0.02] text-sm text-ash/90 leading-relaxed rounded-sm">
        <h2 className="text-lg font-medium text-white mb-4">What happens next</h2>
        <ul className="space-y-3 text-left">
          <li className="flex items-start gap-3">
            <span className="text-white mt-1">1.</span>
            <span>You'll receive a confirmation email at the address provided within a few minutes.</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-white mt-1">2.</span>
            <span>Your monument will enter production within 24-48 hours.</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-white mt-1">3.</span>
            <span>Production takes 5-7 business days, followed by 2-3 days for shipping.</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-white mt-1">4.</span>
            <span>You'll receive tracking information once your order ships.</span>
          </li>
        </ul>
      </div>

      <p className="text-ash/90 mb-8 leading-relaxed">
        Each piece is produced on-demand with museum-grade quality. Allow 7-10 business days total for creation and delivery.
      </p>

      <div className="flex flex-col sm:flex-row gap-4 justify-center">
        <Link
          href="/#monuments"
          className="inline-block px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300"
        >
          Continue exploring
        </Link>
        <Link
          href="/meaning"
          className="inline-block px-8 py-4 border border-hairline hover:border-white transition-colors duration-300"
        >
          Read the meaning
        </Link>
      </div>

      <div className="mt-12 pt-12 border-t border-hairline">
        <p className="text-sm text-ash/70 mb-4">Questions about your order?</p>
        <p className="text-sm text-ash/90">
          Save your transaction ID and contact us at{" "}
          <a
            href="mailto:support@verse-monuments.com"
            className="text-white hover:text-ash transition-colors underline"
          >
            support@verse-monuments.com
          </a>
        </p>
      </div>
    </div>
  );
}

export default function CheckoutSuccessPage() {
  return (
    <Suspense fallback={
      <div className="max-w-2xl mx-auto px-6 py-32 text-center">
        <div className="text-ash/70">Loading...</div>
      </div>
    }>
      <SuccessContent />
    </Suspense>
  );
}
