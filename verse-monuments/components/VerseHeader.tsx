"use client";

import Link from "next/link";
import { useCart } from "@/contexts/CartContext";

export default function VerseHeader() {
  const { itemCount, openCart } = useCart();

  return (
    <header className="sticky top-0 z-50 border-b border-hairline bg-ink/95 backdrop-blur-sm" role="banner">
      <div className="max-w-[72rem] mx-auto px-6 py-6 flex items-center justify-between">
        <Link
          href="/"
          className="text-2xl font-unifraktur tracking-wide hover:opacity-70 transition-opacity duration-300"
          aria-label="VERSE home"
        >
          VERSE
        </Link>

        <nav aria-label="Main navigation">
          <ul className="flex items-center gap-8 text-sm tracking-wide">
            <li>
              <Link
                href="/#monuments"
                className="hover:text-ash transition-colors duration-300 relative after:absolute after:bottom-[-4px] after:left-0 after:w-0 after:h-[1px] after:bg-ash after:transition-all after:duration-300 hover:after:w-full"
              >
                Shop
              </Link>
            </li>
            <li>
              <Link
                href="/meaning"
                className="hover:text-ash transition-colors duration-300 relative after:absolute after:bottom-[-4px] after:left-0 after:w-0 after:h-[1px] after:bg-ash after:transition-all after:duration-300 hover:after:w-full"
              >
                Meaning
              </Link>
            </li>
            <li>
              <button
                onClick={openCart}
                className="relative hover:text-ash transition-colors duration-300 p-2"
                aria-label={`Shopping cart with ${itemCount} items`}
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <path d="M16 10a4 4 0 0 1-8 0" />
                </svg>
                {itemCount > 0 && (
                  <span className="absolute -top-1 -right-1 bg-white text-ink text-xs w-5 h-5 rounded-full flex items-center justify-center font-medium">
                    {itemCount}
                  </span>
                )}
              </button>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
