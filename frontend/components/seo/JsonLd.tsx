type JsonLdProps = {
  data: Record<string, any> | null;
  id?: string;
};

const serializeJsonLd = (data: Record<string, any>) =>
  JSON.stringify(data).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");

export function JsonLd({ data, id }: JsonLdProps) {
  if (!data) return null;
  return (
    <script
      id={id}
      type="application/ld+json"
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
