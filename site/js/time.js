// Time helpers. Everything is shown in the viewer's own time zone and locale.

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function parseTime(value) {
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : NaN;
}

/** Compact age for item rows: "just now", "12m ago", "3h ago", "2d ago". */
export function relativeTime(ms, now = Date.now()) {
  const diff = Math.max(0, now - ms);
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  return `${Math.floor(diff / DAY)}d ago`;
}

/** Wordier age for the "Updated …" label. */
export function updatedLabel(ms, now = Date.now()) {
  const diff = Math.max(0, now - ms);
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) {
    const minutes = Math.floor(diff / MINUTE);
    return `${minutes} min ago`;
  }
  if (diff < DAY) {
    const hours = Math.floor(diff / HOUR);
    return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  }
  const days = Math.floor(diff / DAY);
  return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

export function clockTime(ms, locale) {
  return new Date(ms).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' });
}

export function fullTime(ms, locale) {
  return new Date(ms).toLocaleString(locale, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

/** Local calendar day as YYYY-MM-DD, used to group items under day headers. */
export function dayKey(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function startOfDay(ms) {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** Day header text: { title: "Today" | "Yesterday" | "Monday", detail: "Wed, Oct 15" }. */
export function dayLabel(ms, now = Date.now(), locale) {
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / DAY);
  const sameYear = new Date(ms).getFullYear() === new Date(now).getFullYear();
  const detail = new Date(ms).toLocaleDateString(locale, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
  let title;
  if (days <= 0) title = 'Today';
  else if (days === 1) title = 'Yesterday';
  else title = new Date(ms).toLocaleDateString(locale, { weekday: 'long' });
  return { title, detail };
}
