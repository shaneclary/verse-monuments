"use client";

import { useCart } from "@/contexts/CartContext";
import Image from "next/image";
import Link from "next/link";

export default function Cart() {
  const { items, removeItem, updateQuantity, clearCart, isOpen, closeCart, itemCount } = useCart();

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 transition-opacity duration-300"
        onClick={closeCart}
        aria-hidden="true"
      />

      {/* Cart Drawer */}
      <aside
        className="fixed top-0 right-0 h-full w-full max-w-md bg-white shadow-2xl z-50 flex flex-col"
        role="dialog"
        aria-label="Shopping cart"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-6 border-b border-gray-200">
          <h2 className="text-2xl font-unifraktur text-ink tracking-wide">
            Collection ({itemCount})
          </h2>
          <button
            onClick={closeCart}
            className="text-ink hover:text-ash transition-colors p-2"
            aria-label="Close cart"
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Items */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {items.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <p className="text-ash mb-4">Your collection is empty</p>
              <button
                onClick={closeCart}
                className="text-sm text-ink underline hover:no-underline"
              >
                Continue exploring
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex gap-4 pb-6 border-b border-gray-200 last:border-0"
                >
                  <Link
                    href={`/monuments/${item.slug}`}
                    onClick={closeCart}
                    className="relative w-24 h-24 bg-ink rounded-sm overflow-hidden flex-shrink-0"
                  >
                    <Image
                      src={item.image}
                      alt={item.title}
                      fill
                      className="object-contain"
                    />
                  </Link>

                  <div className="flex-1 flex flex-col">
                    <Link
                      href={`/monuments/${item.slug}`}
                      onClick={closeCart}
                      className="text-ink font-medium hover:text-ash transition-colors mb-2"
                    >
                      {item.title}
                    </Link>

                    <div className="flex items-center gap-3 mt-auto">
                      <div className="flex items-center border border-gray-300 rounded">
                        <button
                          onClick={() => updateQuantity(item.id, item.quantity - 1)}
                          className="px-3 py-1 text-ink hover:bg-gray-100 transition-colors"
                          aria-label="Decrease quantity"
                        >
                          −
                        </button>
                        <span className="px-3 py-1 text-ink min-w-[2rem] text-center">
                          {item.quantity}
                        </span>
                        <button
                          onClick={() => updateQuantity(item.id, item.quantity + 1)}
                          className="px-3 py-1 text-ink hover:bg-gray-100 transition-colors"
                          aria-label="Increase quantity"
                        >
                          +
                        </button>
                      </div>

                      <button
                        onClick={() => removeItem(item.id)}
                        className="text-sm text-ash hover:text-ink transition-colors ml-auto"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {items.length > 0 && (
          <div className="border-t border-gray-200 px-6 py-6 space-y-4">
            <div className="flex items-center justify-between text-sm text-ash mb-4">
              <span>Pricing calculated at checkout</span>
            </div>

            <Link
              href="/checkout"
              onClick={closeCart}
              className="block w-full bg-ink text-white text-center px-8 py-4 text-sm font-medium tracking-wide hover:bg-ash transition-colors duration-300"
            >
              Proceed to checkout
            </Link>

            <button
              onClick={clearCart}
              className="w-full text-sm text-ash hover:text-ink transition-colors"
            >
              Clear collection
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
