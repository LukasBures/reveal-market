import { JsonLd } from "@/components/seo/JsonLd";
import {
  DocsSlug,
  buildArticleJsonLd,
  buildBreadcrumbJsonLd,
  docsPath,
  getDocsMeta,
} from "@/lib/seo";

export function DocsStructuredData({ slug }: { slug: DocsSlug }) {
  const entry = getDocsMeta(slug);
  const path = docsPath(slug);
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Docs", path: "/docs" },
    { name: entry.title, path },
  ]);
  const article = buildArticleJsonLd({
    title: entry.title,
    description: entry.description,
    path,
    image: "/opengraph-image",
  });
  return (
    <>
      <JsonLd data={breadcrumbs} id={`${slug}-breadcrumbs`} />
      <JsonLd data={article} id={`${slug}-article`} />
    </>
  );
}
