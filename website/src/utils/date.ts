export function formatDate(dateStr?: string, short: boolean = false): string {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-IN', {
    weekday: short ? 'short' : 'long',
    year: 'numeric',
    month: short ? 'short' : 'long',
    day: 'numeric',
  });
}
