import Image from "next/image";
import type { ReactNode } from "react";

type Props = {
  src: string | null | undefined;
  alt: string;
  sizeClass?: string;
  roundedClass?: string;
  borderClass?: string;
  fallback?: ReactNode;
};

const DEFAULT_FALLBACK = (
  <div className="h-full w-full bg-gradient-to-br from-brand-500/30 via-slate-800 to-slate-950" aria-hidden="true" />
);

export function MarketArtwork({
  src,
  alt,
  sizeClass = "w-16 h-16",
  roundedClass = "rounded-xl",
  borderClass = "border border-white/10",
  fallback = DEFAULT_FALLBACK,
}: Props) {
  const sizeClasses = `${sizeClass} aspect-square`;
  return (
    <div
      className={`relative flex-shrink-0 overflow-hidden ${roundedClass} ${borderClass} bg-slate-800/60 ${sizeClasses}`}
    >
      {src ? (
        <Image
          src={src}
          alt={alt}
          fill
          sizes="(max-width: 768px) 96px, 120px"
          className="h-full w-full object-cover object-center"
          style={{ objectFit: "cover", objectPosition: "center" }}
          priority={false}
          loading="lazy"
        />
      ) : (
        fallback
      )}
    </div>
  );
}
