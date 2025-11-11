import { notFound } from "next/navigation";
import Image from "next/image";
import Badge from "@/components/Badge";
import BuyCta from "@/components/BuyCta";
import monuments from "@/data/monuments.json";
import { generateSEO } from "@/lib/seo";

interface MonumentPageProps {
  params: Promise<{
    slug: string;
  }>;
}

export async function generateStaticParams() {
  return monuments.map((monument) => ({
    slug: monument.slug,
  }));
}

export async function generateMetadata({ params }: MonumentPageProps) {
  const { slug } = await params;
  const monument = monuments.find((m) => m.slug === slug);

  if (!monument) {
    return {};
  }

  return generateSEO({
    title: `${monument.title} — VERSE`,
    description: monument.narrative,
    image: monument.image,
  });
}

export default async function MonumentPage({ params }: MonumentPageProps) {
  const { slug } = await params;
  const monument = monuments.find((m) => m.slug === slug);

  if (!monument) {
    notFound();
  }

  const isLennon = monument.slug === "lennon-cut";

  return (
    <article className="max-w-[72rem] mx-auto px-6 py-20">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 mb-20">
        {/* Image */}
        <div className="relative aspect-square bg-ink rounded-sm overflow-hidden">
          <Image
            src={monument.image}
            alt={`${monument.title} design on black long-sleeve tee`}
            fill
            sizes="(max-width: 1024px) 100vw, 50vw"
            className="object-contain"
            priority
          />
        </div>

        {/* Info */}
        <div className="flex flex-col">
          <div className="flex flex-wrap gap-2 mb-6">
            {monument.badges.map((badge) => (
              <Badge key={badge}>{badge}</Badge>
            ))}
          </div>

          <h1
            className={`text-4xl md:text-5xl mb-6 tracking-tight leading-tight ${
              isLennon ? "font-league" : "font-unifraktur"
            }`}
          >
            {monument.title}
          </h1>

          <p className="text-lg text-ash/90 mb-6 leading-relaxed">{monument.summary}</p>

          <p className="text-base leading-relaxed mb-10 text-white/90">{monument.narrative}</p>

          <div className="p-6 border border-hairline bg-white/[0.02] mb-10 rounded-sm">
            <h3 className="text-sm font-medium mb-3 tracking-wide">Origin Disclosure</h3>
            <p className="text-sm text-ash/90 leading-relaxed">
              {monument.originDisclosure}
            </p>
          </div>

          <div className="mt-auto flex flex-col gap-3">
            <BuyCta
              productId={monument.id}
              variant="primary"
              className="w-full md:w-auto min-w-[240px]"
              addToCart={true}
              monument={{
                id: monument.id,
                title: monument.title,
                image: monument.image,
                slug: monument.slug,
              }}
            >
              Acquire this monument
            </BuyCta>
            <p className="text-xs text-ash/70 leading-relaxed">
              Each piece is produced on-demand. Allow 7-10 business days for creation and delivery.
            </p>
          </div>
        </div>
      </div>

      {/* Long Body */}
      <div className="max-w-3xl mx-auto border-t border-hairline pt-20">
        <div className="prose prose-invert prose-lg max-w-none">
          <div className="text-base leading-relaxed whitespace-pre-line text-ash/90">
            {monument.longBody}
          </div>
        </div>
      </div>

      {/* City Story */}
      {monument.cityStory && (
        <details className="max-w-3xl mx-auto mt-16 border border-hairline p-8 rounded-sm bg-white/[0.02] group">
          <summary className="cursor-pointer text-lg font-medium mb-0 hover:text-ash transition-colors tracking-tight list-none flex items-center justify-between">
            <span>A City Story</span>
            <span className="text-ash group-open:rotate-180 transition-transform duration-300">▼</span>
          </summary>
          <div className="pt-6 text-base text-ash/90 leading-relaxed whitespace-pre-line">
            {monument.cityStory}
          </div>
        </details>
      )}

      {/* Form Story */}
      {monument.formStory && (
        <details className="max-w-3xl mx-auto mt-16 border border-hairline p-8 rounded-sm bg-white/[0.02] group">
          <summary className="cursor-pointer text-lg font-medium mb-0 hover:text-ash transition-colors tracking-tight list-none flex items-center justify-between">
            <span>Form & Construction</span>
            <span className="text-ash group-open:rotate-180 transition-transform duration-300">▼</span>
          </summary>
          <div className="pt-6 space-y-4 text-sm text-ash/90 leading-relaxed">
            <p>
              <strong className="text-white font-medium">Garment:</strong> {monument.formStory.garment}
            </p>
            <p>
              <strong className="text-white font-medium">Weight:</strong> {monument.formStory.weight}
            </p>
            <p>
              <strong className="text-white font-medium">Fit:</strong> {monument.formStory.fit}
            </p>
            <p>
              <strong className="text-white font-medium">Fabric:</strong> {monument.formStory.fabric}
            </p>
            <p>
              <strong className="text-white font-medium">Construction:</strong> {monument.formStory.construction}
            </p>
            <p>
              <strong className="text-white font-medium">Print Method:</strong> {monument.formStory.printMethod}
            </p>
            <p>
              <strong className="text-white font-medium">Care:</strong> {monument.formStory.care}
            </p>
          </div>
        </details>
      )}

      {/* Lennon Design Spec */}
      {isLennon && (
        <details className="max-w-3xl mx-auto mt-16 border border-hairline p-8 rounded-sm bg-white/[0.02] group">
          <summary className="cursor-pointer text-lg font-medium mb-0 hover:text-ash transition-colors tracking-tight list-none flex items-center justify-between">
            <span>Design Specification</span>
            <span className="text-ash group-open:rotate-180 transition-transform duration-300">▼</span>
          </summary>
          <div className="pt-6 space-y-6 text-sm text-ash/90 leading-relaxed">
            <p>
              <strong className="text-white font-medium">Geometry:</strong> Three-line
              vertical stack, tight leading, centered alignment. Letters scaled
              to maximum width of printable area while maintaining legibility.
            </p>
            <p>
              <strong className="text-white font-medium">Typography:</strong> League Gothic
              or similar condensed sans-serif. All caps. Optical adjustments for
              vertical rhythm.
            </p>
            <p>
              <strong className="text-white font-medium">Reference:</strong> Inspired by
              John Lennon's own typographic directness—plain, earnest,
              unapologetic block text as seen in his personal wardrobe circa
              1980.
            </p>
            <p>
              <strong className="text-white font-medium">Placement:</strong> Centered on
              chest. Sufficient negative space above and below to let the
              statement breathe.
            </p>
          </div>
        </details>
      )}
    </article>
  );
}
