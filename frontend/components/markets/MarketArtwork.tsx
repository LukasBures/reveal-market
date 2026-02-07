"use client";

import Image from "next/image";
import { type ReactNode, useEffect, useState } from "react";

type Props = {
  src: string | null | undefined;
  alt: string;
  sizeClass?: string;
  roundedClass?: string;
  borderClass?: string;
  fallback?: ReactNode;
  priority?: boolean;
};

const DEFAULT_FALLBACK = (
  <div
    className="h-full w-full bg-[url('/brand/arrow-pattern.png')] bg-cover bg-center bg-no-repeat"
    aria-hidden="true"
  />
);

export function MarketArtwork({
  src,
  alt,
  sizeClass = "w-16 h-16",
  roundedClass = "rounded-xl",
  borderClass = "border border-white/10",
  fallback = DEFAULT_FALLBACK,
  priority = false,
}: Props) {
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    // Reset error state whenever the source changes so we can try again.
    setErrored(false);
  }, [src]);

  const sizeClasses = `${sizeClass} aspect-square`;
  return (
    <div
      className={`relative flex-shrink-0 overflow-hidden ${roundedClass} ${borderClass} bg-slate-800/60 ${sizeClasses}`}
    >
      {src && !errored ? (
        <Image
          src={src}
          alt={alt}
          fill
          sizes="(max-width: 768px) 96px, 120px"
          className="h-full w-full object-cover object-center"
          style={{ objectFit: "cover", objectPosition: "center" }}
          priority={priority}
          loading={priority ? "eager" : "lazy"}
          onError={() => setErrored(true)}
        />
      ) : (
        fallback
      )}
    </div>
  );
}
