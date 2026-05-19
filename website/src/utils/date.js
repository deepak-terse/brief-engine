export function formatDisplayDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  const dayName = d.toLocaleDateString('en-IN', { weekday: 'long' });
  const monthDay = d.toLocaleDateString('en-IN', { month: 'long', day: 'numeric' });
  return `${dayName}, ${monthDay}`;
}

export function formatPillDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
}
