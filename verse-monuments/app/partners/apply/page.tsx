"use client";

import { useState } from "react";
import Link from "next/link";

export default function ApplyPage() {
  const [submitted, setSubmitted] = useState(false);
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    instagram: "",
    tiktok: "",
    youtube: "",
    website: "",
    audience: "",
    why: "",
    preferredCode: "",
    paypal: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // For now, just log to console and show confirmation
    // TODO: Implement actual submission to your backend/email
    console.log("Application submitted:", formData);

    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 500));

    setSubmitted(true);
  };

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  if (submitted) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-32 text-center">
        <h1 className="text-4xl md:text-5xl font-unifraktur mb-8 tracking-tight">
          Application received
        </h1>
        <p className="text-lg text-ash/90 mb-8 leading-relaxed">
          We'll review your application within 3-5 business days and reach out via email with next steps.
        </p>
        <p className="text-ash/90 mb-12">
          In the meantime, you can explore the collection.
        </p>
        <Link
          href="/"
          className="inline-block px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300"
        >
          Back to monuments
        </Link>
      </div>
    );
  }

  return (
    <article className="max-w-3xl mx-auto px-6 py-20">
      <div className="mb-12">
        <Link
          href="/partners"
          className="text-ash hover:text-white transition-colors text-sm"
        >
          ← Back to Monument Circle
        </Link>
      </div>

      <h1 className="text-4xl md:text-5xl font-unifraktur mb-6 tracking-tight">
        Apply to Monument Circle
      </h1>
      <p className="text-lg text-ash/90 mb-4 leading-relaxed">
        Brief form; we look for voice fit and care for craft. All fields required unless marked optional.
      </p>
      <p className="text-sm text-ash/70 mb-12 leading-relaxed">
        Too much paperwork, just want to earn a{" "}
        <Link href="/partners/quick" className="text-white hover:text-ash transition-colors underline">
          quick buck
        </Link>
        ?
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Personal Info */}
        <div className="space-y-6">
          <h2 className="text-xl font-medium border-b border-hairline pb-3">
            About you
          </h2>

          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              Full name
            </label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              required
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="Your name"
            />
          </div>

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
              placeholder="you@example.com"
            />
          </div>
        </div>

        {/* Social Links */}
        <div className="space-y-6">
          <h2 className="text-xl font-medium border-b border-hairline pb-3">
            Where you share
          </h2>

          <div>
            <label htmlFor="instagram" className="block text-sm font-medium mb-2">
              Instagram <span className="text-ash/50 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              id="instagram"
              name="instagram"
              value={formData.instagram}
              onChange={handleChange}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="@handle"
            />
          </div>

          <div>
            <label htmlFor="tiktok" className="block text-sm font-medium mb-2">
              TikTok <span className="text-ash/50 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              id="tiktok"
              name="tiktok"
              value={formData.tiktok}
              onChange={handleChange}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="@handle"
            />
          </div>

          <div>
            <label htmlFor="youtube" className="block text-sm font-medium mb-2">
              YouTube <span className="text-ash/50 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              id="youtube"
              name="youtube"
              value={formData.youtube}
              onChange={handleChange}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="@channel or URL"
            />
          </div>

          <div>
            <label htmlFor="website" className="block text-sm font-medium mb-2">
              Website <span className="text-ash/50 font-normal">(optional)</span>
            </label>
            <input
              type="url"
              id="website"
              name="website"
              value={formData.website}
              onChange={handleChange}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="https://yoursite.com"
            />
          </div>
        </div>

        {/* Audience */}
        <div className="space-y-6">
          <h2 className="text-xl font-medium border-b border-hairline pb-3">
            Your work
          </h2>

          <div>
            <label htmlFor="audience" className="block text-sm font-medium mb-2">
              Describe your audience
            </label>
            <textarea
              id="audience"
              name="audience"
              value={formData.audience}
              onChange={handleChange}
              required
              rows={4}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors resize-none"
              placeholder="Who follows you? What do they care about?"
            />
          </div>

          <div>
            <label htmlFor="why" className="block text-sm font-medium mb-2">
              Why Monument Circle?
            </label>
            <textarea
              id="why"
              name="why"
              value={formData.why}
              onChange={handleChange}
              required
              rows={6}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors resize-none"
              placeholder="What resonates about this work? How would you share it?"
            />
          </div>
        </div>

        {/* Preferences */}
        <div className="space-y-6">
          <h2 className="text-xl font-medium border-b border-hairline pb-3">
            Setup preferences
          </h2>

          <div>
            <label htmlFor="preferredCode" className="block text-sm font-medium mb-2">
              Preferred discount code <span className="text-ash/50 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              id="preferredCode"
              name="preferredCode"
              value={formData.preferredCode}
              onChange={handleChange}
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors uppercase"
              placeholder="YOURNAME10"
              maxLength={20}
            />
            <p className="text-xs text-ash/70 mt-2">
              We'll check availability and confirm via email. Alphanumeric only.
            </p>
          </div>

          <div>
            <label htmlFor="paypal" className="block text-sm font-medium mb-2">
              PayPal email for payouts
            </label>
            <input
              type="email"
              id="paypal"
              name="paypal"
              value={formData.paypal}
              onChange={handleChange}
              required
              className="w-full px-4 py-3 bg-white/[0.05] border border-hairline text-white placeholder-ash/50 focus:outline-none focus:border-white transition-colors"
              placeholder="paypal@example.com"
            />
          </div>
        </div>

        {/* Compliance */}
        <div className="p-6 border border-hairline bg-white/[0.02]">
          <p className="text-sm text-ash/90 leading-relaxed mb-4">
            By applying, you agree to:
          </p>
          <ul className="text-xs text-ash/70 space-y-2 leading-relaxed">
            <li>• FTC-compliant disclosure on all posts (#ad or paid partnership)</li>
            <li>• No bidding on brand terms without written approval</li>
            <li>• Reverent tone—no tragedy-bait or exploitation</li>
            <li>• Month-to-month partnership; either party can end with notice</li>
          </ul>
        </div>

        {/* Submit */}
        <div className="flex flex-col sm:flex-row gap-4">
          <button
            type="submit"
            className="flex-1 px-8 py-4 bg-white text-ink font-medium hover:bg-ash transition-colors duration-300"
          >
            Submit application
          </button>
          <Link
            href="/partners"
            className="flex-1 px-8 py-4 border border-hairline text-center hover:border-white transition-colors duration-300"
          >
            Cancel
          </Link>
        </div>
      </form>
    </article>
  );
}
