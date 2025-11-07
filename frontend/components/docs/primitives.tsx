type CodeProps = {
  children: React.ReactNode;
  inline?: boolean;
};

export function Code({ children, inline = false }: CodeProps) {
  if (inline) {
    return (
      <code className="rounded-md bg-black/30 px-2 py-0.5 text-sm text-brand-200">
        {children}
      </code>
    );
  }

  return (
    <pre className="whitespace-pre-wrap rounded-2xl bg-black/50 p-4 text-sm text-brand-100">
      <code>{children}</code>
    </pre>
  );
}
