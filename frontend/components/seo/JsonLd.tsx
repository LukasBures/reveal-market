type JsonLdProps = {
  data: Record<string, any> | null;
  id?: string;
};

export function JsonLd({ data, id }: JsonLdProps) {
  if (!data) return null;
  return (
    <script
      id={id}
      type="application/ld+json"
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}
