// Time helpers. Everything is shown in the viewer's own time zone and locale.

export const MINUTE = 60_000;
export const HOUR = 60 * MINUTE;
export const DAY = 24 * HOUR;

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

// Building an Intl formatter is far slower than using one, and every row needs two.
const formatters = new Map();
function formatter(kind, locale, options) {
  const key = `${kind}|${locale ?? ''}`;
  let format = formatters.get(key);
  if (!format) formatters.set(key, (format = new Intl.DateTimeFormat(locale, options)));
  return format;
}

export function clockTime(ms, locale) {
  return formatter('clock', locale, { hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
}

/**
 * A clock time with enough of the day to be unambiguous: "9:58 PM" today, "yesterday 9:58 PM",
 * "Fri 9:58 PM" within the past week, and "Oct 14, 9:58 PM" beyond that.
 */
export function momentLabel(ms, now = Date.now(), locale) {
  ms = Math.min(ms, now); // a few minutes ahead (clock skew) is still "now", not tomorrow
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / DAY);
  const clock = clockTime(ms, locale);
  if (days <= 0) return clock;
  if (days === 1) return `yesterday ${clock}`;
  if (days < 7) return `${new Date(ms).toLocaleDateString(locale, { weekday: 'short' })} ${clock}`;
  return `${new Date(ms).toLocaleDateString(locale, { month: 'short', day: 'numeric' })}, ${clock}`;
}

export function fullTime(ms, locale) {
  return formatter('full', locale, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(ms));
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

/**
 * Day header text: { title: "Today" | "Yesterday" | "Monday", detail: "Wed, Oct 15" }. When the
 * title already names the weekday, the detail leaves it out ("Monday · Oct 13", not "Monday Mon, Oct 13").
 */
export function dayLabel(ms, now = Date.now(), locale) {
  ms = Math.min(ms, now); // an item a few minutes "in the future" belongs to today, not tomorrow
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / DAY);
  const sameYear = new Date(ms).getFullYear() === new Date(now).getFullYear();
  const detail = new Date(ms).toLocaleDateString(locale, {
    ...(days <= 1 ? { weekday: 'short' } : {}),
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
