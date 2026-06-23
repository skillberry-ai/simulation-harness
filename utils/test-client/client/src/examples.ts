const modules = import.meta.glob('../../examples/*', {
  query: '?raw',
  import: 'default',
  eager: true,
});
export const EXAMPLES: Record<string, string> = Object.fromEntries(
  Object.entries(modules).map(([path, raw]) => [path.split('/').pop()!, raw as string]),
);
