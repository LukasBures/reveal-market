"use client";

import { useState } from "react";

type Props = {
  value: string;
  label?: string;
  className?: string;
};

export function MetadataCopyButton({ value, label = "Copy", className }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch (error) {
      if (typeof console !== "undefined") {
        console.error("Unable to copy value", error);
      }
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={className}
      aria-label={`Copy ${label}`}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
